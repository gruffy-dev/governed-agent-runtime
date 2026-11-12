import {ApiClient} from "./api_client.mjs";
import {AdkStream} from "./adk_stream.mjs";
import {InvocationActivity} from "./invocation_activity.mjs";

export class WorkspaceController {
    #client;
    #epoch = 0;
    #signedIn = false;
    #busy = false;
    #streamController = null;
    #operation = null;
    #workspace = null;
    #skillEditor = null;
    #conversation = null;
    #conversations = [];
    #messages = [];
    #activityTimer = null;
    #activitySkills = null;
    #activityStage = null;
    constructor(root) {
        /**
         * Initialise a browser-only workspace with no persistent token or chat state.
         * :param root: Mounted Dash root containing only public backend configuration.
         */
        this.#client = new ApiClient(root.dataset.backendUrl);
        const input = document.createElement("input");
        Object.assign(input, {id: "pilot-token", type: "password", className: "form-control", autocomplete: "off", spellcheck: false});
        input.setAttribute("aria-describedby", "sign-in-error");
        document.getElementById("token-input-slot").append(input);
        document.addEventListener("click", event => this.#click(event));
        window.mosaicConversationAction = id => {
            if (id === undefined) this.#newConversation();
            else if (this.#conversations.some(conversation => conversation.id === id)) this.#loadConversation(id);
        };
        window.mosaicSkillAction = (id, value) => this.#skillControl(id, value);
        document.addEventListener("keydown", event => this.#key(event));
        document.getElementById("sign-in-form").addEventListener("submit", event => {event.preventDefault(); this.#signIn();});
        for (const side of ["history", "skills"]) this.#resize(side);
        window.addEventListener("beforeunload", event => {
            if (this.#streamController) {event.preventDefault(); event.returnValue = "";}
        });
        this.#bootstrap();
    }
    static start() {
        /**
         * Mount once after Dash has rendered its shell and public set_props API.
         */
        const mount = () => {
            const root = document.getElementById("mosaic-root");
            if (!root || !window.dash_clientside?.set_props || !document.getElementById("token-input-slot")) return false;
            if (!root.dataset.mounted) {root.dataset.mounted = "true"; new WorkspaceController(root);}
            return true;
        };
        if (!mount()) {
            const observer = new MutationObserver(() => {if (mount()) observer.disconnect();});
            observer.observe(document.documentElement, {childList: true, subtree: true});
        }
    }
    #props(id, props) {
        /**
         * Update a Dash component locally without a server callback or credential store.
         * :param id: Existing component identifier.
         * :param props: Safe UI properties to update through Dash's supported API.
         */
        window.dash_clientside.set_props(id, props);
    }
    #element(type, props, namespace = "dash_html_components") {
        /**
         * Build a local Dash component description for Bootstrap and Markdown content.
         * :param type: Supported Dash component type.
         * :param props: Safe component properties; text is never interpolated as HTML.
         * :param namespace: Installed Dash component namespace.
         * :return: Dash-renderable component description.
         */
        return {namespace, type, props};
    }
    async #bootstrap() {
        /**
         * Restore cookie identity if valid, always opening a fresh conversation.
         */
        const epoch = this.#epoch;
        this.#busy = true;
        this.#controls();
        try {
            const workspace = await this.#client.request("/api/v1/workspace");
            if (epoch !== this.#epoch) return;
            await this.#enter(workspace, epoch);
        } catch (error) {
            if (epoch === this.#epoch) {
                if (this.#signedIn) this.#failure(error);
                else if (error.status !== 401) this.#loginError(this.#errorMessage({message: "The backend is unavailable. Check the connection and try again.", correlationId: error.correlationId}));
            }
        } finally {
            if (epoch === this.#epoch) {this.#busy = false; this.#controls();}
        }
    }
    async #signIn() {
        /**
         * Exchange a transient native input token directly with the public backend.
         */
        if (this.#busy) return;
        const input = document.getElementById("pilot-token");
        let token = input.value.trim();
        input.value = "";
        if (!token) {this.#loginError("Enter the access token provided by your administrator."); return;}
        const epoch = ++this.#epoch;
        this.#busy = true;
        this.#props("sign-in-error", {is_open: false});
        this.#controls();
        try {
            await this.#client.request("/api/v1/auth/token", {method: "POST", body: {token}});
            token = "";
            if (epoch !== this.#epoch) return;
            const workspace = await this.#client.request("/api/v1/workspace");
            if (epoch === this.#epoch) await this.#enter(workspace, epoch);
        } catch (error) {
            if (epoch === this.#epoch) {
                if (this.#signedIn) this.#failure(error);
                else this.#loginError(this.#errorMessage(error));
            }
        } finally {
            token = "";
            if (epoch === this.#epoch) {this.#busy = false; this.#controls();}
        }
    }
    async #enter(workspace, epoch) {
        /**
         * Load an authenticated workspace with an unsaved blank chat, never resuming history.
         * :param workspace: Safe owner and assigned Skill metadata from the backend.
         * :param epoch: Sign-in generation preventing previous-user responses appearing.
         */
        this.#workspace = workspace;
        this.#signedIn = true;
        this.#props("user-label", {children: workspace.user_id});
        this.#props("sign-out", {style: {display: "inline-block"}});
        this.#props("login-screen", {style: {display: "none"}});
        this.#props("workspace-navigation", {style: {display: "flex"}});
        this.#props("workspace-main", {className: "page-main workspace-page"});
        this.#showWorkspaceView(false);
        this.#setPanelVisibility("skills", false);
        this.#renderSkills();
        this.#select(null);
        await this.#refreshHistory(epoch);
    }
    async #signOut() {
        /**
         * Clear the cookie and all visible identity/history, guarding late responses.
         */
        if (this.#streamController && !window.confirm("Signing out stops this response and may make this conversation read-only. Continue?")) return;
        ++this.#epoch;
        this.#reset();
        this.#busy = true;
        this.#controls();
        try {await this.#client.request("/api/v1/auth/logout", {method: "POST"});}
        catch (error) {this.#loginError(this.#errorMessage({message: "Sign-out could not be confirmed. Retry Sign out before using another account.", correlationId: error.correlationId})); this.#props("sign-out", {style: {display: "inline-block"}});}
        finally {this.#busy = false; this.#controls();}
    }
    #reset() {
        /**
         * Remove previous-user data from memory and the UI without browser storage.
         */
        this.#clearActivity();
        this.#operation?.abort();
        this.#streamController?.abort();
        this.#signedIn = false;
        this.#workspace = this.#conversation = null;
        this.#closeSkillEditor();
        this.#props("saved-skill-view", {data: null});
        this.#props("workspace-navigation", {style: {display: "none"}});
        this.#props("workspace-main", {className: "page-main"});
        this.#conversations = this.#messages = [];
        this.#props("conversation-row-ids", {data: []});
        this.#props("conversation-sidebar-view", {data: null});
        this.#streamController = this.#operation = null;
        document.getElementById("pilot-token").value = "";
        this.#props("message-input", {value: ""});
        for (const id of ["user-label", "messages", "skill-count"]) this.#props(id, {children: ""});
        this.#props("workspace-alert", {is_open: false});
        this.#props("sign-out", {style: {display: "none"}});
        this.#props("workspace-screen", {style: {display: "none"}});
        this.#props("login-screen", {style: {display: "flex"}});
    }
    async #newConversation() {
        /**
         * Open an unsaved blank chat without switching away from an active stream.
         */
        if (this.#busy || this.#streamController || !this.#signedIn) return;
        const epoch = this.#epoch;
        this.#busy = true;
        this.#controls();
        try {
            const workspace = await this.#client.request("/api/v1/workspace");
            if (epoch !== this.#epoch) return;
            this.#workspace = workspace;
            this.#renderSkills();
            this.#select(null);
            await this.#refreshHistory(epoch);
        } catch (error) {if (epoch === this.#epoch) this.#failure(error);}
        finally {if (epoch === this.#epoch) {this.#busy = false; this.#controls();}}
    }
    async #loadConversation(id) {
        /**
         * Load persisted user/assistant history without replaying interrupted streams.
         * :param id: Conversation selected from this user's server-owned history list.
         */
        if (this.#busy || this.#streamController || !this.#signedIn) return;
        const epoch = this.#epoch;
        this.#busy = true;
        this.#operation = new AbortController();
        this.#controls();
        try {
            const detail = await this.#client.request("/api/v1/conversations/" + encodeURIComponent(id), {signal: this.#operation.signal});
            if (epoch === this.#epoch) this.#select(detail);
        } catch (error) {if (epoch === this.#epoch) this.#failure(error);}
        finally {if (epoch === this.#epoch) {this.#busy = false; this.#operation = null; this.#controls();}}
    }
    #select(detail) {
        /**
         * Display owned persisted messages and the backend's continuation permission.
         * :param detail: Public conversation detail, or null for an unsaved blank chat.
         */
        this.#conversation = detail;
        this.#messages = (detail?.messages || []).map(message => ({role: message.role, text: message.text}));
        this.#props("message-input", {value: ""});
        this.#props("conversation-title", {children: detail?.title || "New conversation"});
        this.#props("workspace-alert", {is_open: detail?.can_continue === false, color: "warning", children: detail?.is_interrupted ? "Interrupted — this conversation cannot continue. Saved history is available. Start a new conversation." : "This conversation is unavailable while an invocation is active. Start a new conversation or reopen it later."});
        this.#renderMessages();
        this.#controls();
    }
    async #submit() {
        /**
         * Save a blank chat on its first send, then stream text without automatic retry.
         */
        if (this.#busy || this.#streamController || !this.#signedIn || this.#conversation?.can_continue === false) return;
        const input = document.getElementById("message-input");
        const text = input.value.trim();
        if (!text) return;
        const epoch = this.#epoch;
        if (!this.#conversation) {
            this.#busy = true;
            this.#controls();
            try {
                const detail = await this.#client.request("/api/v1/conversations", {method: "POST", body: {}});
                if (epoch !== this.#epoch) return;
                this.#conversation = detail;
            } catch (error) {
                if (epoch === this.#epoch) this.#failure(error);
                return;
            } finally {
                if (epoch === this.#epoch) {this.#busy = false; this.#controls();}
            }
        }
        const id = this.#conversation.conversation_id;
        const controller = new AbortController();
        this.#streamController = controller;
        this.#startActivity(controller);
        this.#props("message-input", {value: ""});
        this.#props("workspace-alert", {is_open: false});
        this.#messages.push({role: "user", text}, {role: "assistant", text: ""});
        const answerIndex = this.#messages.length - 1;
        this.#renderMessages();
        this.#controls();
        let reader;
        let failure = null;
        let correlationId = null;
        try {
            const response = await this.#client.stream(id, text, controller.signal);
            correlationId = response.headers.get("x-correlation-id");
            reader = response.body.getReader();
            const decoder = new TextDecoder();
            const activity = new InvocationActivity(this.#workspace?.skills || [], view => {
                if (epoch === this.#epoch && this.#streamController === controller) this.#renderActivity(view);
            });
            const projection = new AdkStream(answer => {
                if (epoch !== this.#epoch) return;
                activity.writing();
                this.#messages[answerIndex].text = answer;
                this.#renderMessages();
            }, event => activity.accept(event));
            while (true) {
                const {value, done} = await reader.read();
                if (done) break;
                projection.feed(decoder.decode(value, {stream: true}));
            }
            projection.feed(decoder.decode());
            projection.finish();
        } catch (error) {
            failure = controller.signal.aborted ? new Error("Response stopped. This conversation may be read-only; saved history remains available.") : error;
            if (!controller.signal.aborted && !failure.correlationId) failure.correlationId = correlationId;
            controller.abort();
        } finally {
            if (this.#streamController === controller) this.#clearActivity();
            try {if (reader) {await reader.cancel(); reader.releaseLock();}} catch { /* The transport may already be closed. */ }
            if (epoch !== this.#epoch) return;
            this.#streamController = null;
            this.#busy = true;
            this.#controls();
            if (failure?.status === 401) {this.#failure(failure); this.#busy = false; this.#controls(); return;}
            try {
                const detail = await this.#client.request("/api/v1/conversations/" + encodeURIComponent(id));
                if (epoch !== this.#epoch) return;
                this.#select(detail);
                await this.#refreshHistory(epoch);
                const workspace = await this.#client.request("/api/v1/workspace");
                if (epoch === this.#epoch) {this.#workspace = workspace; this.#renderSkills();}
            } catch (error) {
                if (epoch === this.#epoch) {
                    this.#conversation.can_continue = false;
                    this.#failure(error);
                }
            } finally {
                if (epoch === this.#epoch) {
                    this.#busy = false;
                    if (failure) this.#failure(failure);
                    this.#controls();
                }
            }
        }
    }
    #startActivity(controller) {
        /**
         * Show elapsed waiting time without inventing model or tool activity.
         * :param controller: Current stream controller guarding stale timer callbacks.
         */
        this.#clearActivity();
        const started = performance.now();
        this.#props("invocation-activity", {style: {display: "flex"}});
        this.#renderActivity({skills: [], operation: "Waiting for a response", platform: null});
        const tick = () => {
            if (this.#streamController !== controller) return;
            const seconds = Math.floor((performance.now() - started) / 1000);
            this.#props("invocation-elapsed", {children: seconds < 60 ? `${seconds}s elapsed` : `${Math.floor(seconds / 60)}m ${seconds % 60}s elapsed`});
        };
        tick();
        this.#activityTimer = setInterval(tick, 1000);
    }
    #clearActivity() {
        /**
         * Remove transient activity and stop its timer on every terminal or identity path.
         */
        if (this.#activityTimer !== null) clearInterval(this.#activityTimer);
        this.#activityTimer = null;
        this.#activitySkills = this.#activityStage = null;
        this.#props("invocation-activity", {style: {display: "none"}});
        this.#props("invocation-stage", {children: ""});
        this.#props("invocation-skills", {children: ""});
        this.#props("invocation-elapsed", {children: ""});
    }
    #renderActivity(view) {
        /**
         * Render approved Skill titles and semantic operations as plain text.
         * :param view: Bounded activity projection with no provider addresses or payloads.
         */
        const stage = [view.platform, view.operation].filter(Boolean).join(" · ");
        if (stage !== this.#activityStage) {
            this.#activityStage = stage;
            this.#props("invocation-stage", {children: stage});
        }
        const skills = view.skills;
        const selection = JSON.stringify(skills);
        if (selection === this.#activitySkills) return;
        this.#activitySkills = selection;
        const children = skills.length === 1 ? `Skill: ${skills[0]}` : skills.length > 1 ? this.#element("Details", {children: [this.#element("Summary", {children: `${skills.length} selected skills`}), this.#element("Ul", {children: skills.map(title => this.#element("Li", {children: title}))})]}) : "";
        this.#props("invocation-skills", {children});
    }
    async #refreshHistory(epoch) {
        /**
         * Refresh only the authenticated user's public conversation summaries.
         * :param epoch: Current identity generation; stale responses are discarded.
         */
        const result = await this.#client.request("/api/v1/conversations");
        if (epoch !== this.#epoch) return;
        this.#conversations = result.conversations
            .sort((left, right) => right.last_activity_at.localeCompare(left.last_activity_at))
            .map(conversation => ({
                id: conversation.conversation_id,
                title: conversation.title,
                lastActivity: conversation.last_activity_at,
                interrupted: conversation.is_interrupted,
            }));
        this.#publishSidebarView();
        this.#props("conversation-row-ids", {data: this.#conversations.map(conversation => conversation.id)});
    }
    #publishSidebarView() {
        /**
         * Provide conversation display data to Dash's browser callback.
         */
        if (!this.#signedIn) return;
        this.#props("conversation-sidebar-view", {data: {
            conversations: this.#conversations,
            active: this.#conversation?.conversation_id ?? null,
            disabled: this.#busy || Boolean(this.#streamController),
        }});
    }
    #renderMessages() {
        /**
         * Render safe native Dash Markdown; keep ADK metadata and thought parts hidden.
         */
        const scroller = document.getElementById("messages");
        const atBottom = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 100;
        let children;
        if (!this.#messages.length) {
            children = [this.#element("Div", {className: "welcome", children: [this.#element("Img", {src: "/assets/tangram.svg", alt: "", className: "welcome-symbol"}), this.#element("H2", {children: "What would you like to work on?"}), this.#element("P", {children: "Ask a question or describe your Goal. MOSAIC brings together your assigned Skills and the capabilities they need."}), this.#element("Div", {className: "welcome-hint", children: "Open Current Skills to see what is available. You can read earlier conversations or start something new."})]})];
        } else {
            children = this.#messages.map(message => this.#element("Div", {className: "message message-" + message.role, children: [this.#element("Div", {className: "message-label", children: message.role === "user" ? "You" : "MOSAIC"}), message.role === "user" ? this.#element("Div", {className: "message-body", children: message.text}) : message.text ? this.#element("Markdown", {className: "message-body", children: message.text, dangerously_allow_html: false, link_target: "_blank", mathjax: false, highlight_config: {theme: "light"}}, "dash_core_components") : this.#element("Div", {className: "message-body", children: ""})]}));
        }
        this.#props("messages", {children});
        requestAnimationFrame(() => {
            if (atBottom) scroller.scrollTop = scroller.scrollHeight;
            for (const link of scroller.querySelectorAll("a")) link.rel = "noopener noreferrer";
        });
    }
    #renderSkills() {
        /**
         * Group assigned metadata by its most-specific catalogue path, without duplicates.
         */
        const skills = this.#workspace?.skills || [];
        this.#props("skill-count", {children: `${skills.length} assigned ${skills.length === 1 ? "Skill" : "Skills"}`});
        this.#props("saved-skill-view", {data: this.#workspace ? this.#workspaceSkillSelection(this.#workspace) : null});
    }
    #showWorkspaceView(skills) {
        /**
         * Switch workspace views while preserving the conversation and Skill draft.
         * :param skills: Whether to show the Skill browser.
         */
        if (!skills && this.#skillEditor?.bulk) {
            this.#cancelSkillBulk();
            this.#renderSkillBrowser();
        }
        this.#props("workspace-screen", {style: {display: skills ? "none" : "flex"}});
        this.#props("skill-editor", {style: {display: skills ? "flex" : "none"}});
        this.#props("show-chat", {"aria-current": skills ? null : "page"});
        this.#props("show-skill-browser", {"aria-current": skills ? "page" : null});
        if (skills && !this.#skillEditor) this.#openSkillEditor();
    }
    async #openSkillEditor() {
        /**
         * Start a draft from the latest saved workspace and load the first domain page.
         */
        const editor = {
            selected: new Map(), saved: new Set(), version: null, ready: false,
            domain: null, function: null, query: "", level: "domains",
            pages: {}, request: null, loading: null, bulk: null,
            functionMembers: new Map(), functionChecks: new AbortController(), checkingFunctions: new Set(),
        };
        this.#skillEditor = editor;
        this.#renderSkillBrowser();
        this.#controls();
        try {
            const workspace = await this.#client.request("/api/v1/workspace");
            if (this.#skillEditor !== editor) return;
            this.#workspace = workspace;
            this.#renderSkills();
            editor.version = workspace.version;
            editor.savedSkills = this.#workspaceSkillSelection(workspace);
            editor.selected = new Map(editor.savedSkills.map(skill => [skill.skill_id, skill]));
            editor.saved = new Set(editor.selected.keys());
            editor.ready = true;
            this.#renderCurrentSkills();
            if (editor.version === null) {
                this.#skillEditorFailure(new Error("This account has no workspace to edit. Contact your administrator."));
            }
            await this.#loadSkillPage("domains");
        } catch (error) {
            if (this.#skillEditor === editor) {
                this.#skillEditorFailure(error);
                this.#skillEditor = null;
                this.#renderSkillBrowser();
            }
        } finally {
            this.#controls();
        }
    }
    async #loadSkillPage(level, more = false) {
        /**
         * Load only the visible catalogue branch or search page.
         * :param level: Column or search result to populate.
         * :param more: Append the next page to the existing results.
         */
        const editor = this.#skillEditor;
        if (!editor?.ready) return;
        const previous = editor.pages[level];
        if (more && previous?.next_offset == null) return;
        this.#cancelSkillBulk();
        editor.request?.abort();
        const request = new AbortController();
        editor.request = request;
        editor.loading = level;
        const params = new URLSearchParams();
        if (level === "functions" || level === "skills") params.set("domain", editor.domain);
        if (level === "skills") params.set("function", editor.function);
        if (level === "search") params.set("q", editor.query);
        if (more) params.set("offset", previous.next_offset);
        this.#renderSkillBrowser();
        try {
            const page = await this.#client.request("/api/v1/skills/catalogue?" + params, {signal: request.signal});
            if (request.signal.aborted || this.#skillEditor !== editor) return;
            editor.pages[level] = {
                items: more ? [...previous.items, ...page.items] : page.items,
                next_offset: page.next_offset,
            };
        } catch (error) {
            if (!request.signal.aborted && this.#skillEditor === editor) this.#skillEditorFailure(error);
        } finally {
            if (!request.signal.aborted && this.#skillEditor === editor) {
                editor.loading = null;
                if (level === "skills" && editor.pages.skills?.next_offset === null) {
                    editor.functionMembers.set(this.#functionKey(editor.domain, editor.function), editor.pages.skills.items);
                }
                this.#renderSkillBrowser();
                this.#checkFunctionSelections();
            }
        }
    }
    #searchSkills(value) {
        /**
         * Load the debounced Dash search value and cancel superseded requests.
         * :param value: Text entered in the search field.
         */
        const editor = this.#skillEditor;
        if (!editor?.ready) return;
        this.#cancelSkillBulk();
        editor.request?.abort();
        editor.query = value.trim().slice(0, 200);
        delete editor.pages.search;
        editor.loading = editor.query ? "search" : null;
        this.#renderSkillBrowser();
        if (editor.query) this.#loadSkillPage("search");
        else {
            const level = editor.function ? "skills" : editor.domain ? "functions" : "domains";
            if (!editor.pages[level]) this.#loadSkillPage(level);
        }
    }
    #skillGroupLabel(group, fallback) {
        /**
         * Convert a catalogue group key into its display name.
         * :param group: Catalogue group key or reserved ungrouped marker.
         * :param fallback: Label for the reserved marker.
         *
         * :return: Group display name.
         */
        if (group === "~") return fallback;
        const label = group.replaceAll("-", " ");
        return label.charAt(0).toUpperCase() + label.slice(1);
    }
    #functionKey(domain, name) {
        return domain + "/" + name;
    }
    #selectedInFunction(editor, name) {
        const domain = editor.domain;
        const path = this.#functionKey(domain, name);
        return [...editor.selected.values()].some(skill => {
            if (skill.withdrawn) return false;
            if (name !== "~") return skill.groups.includes(path);
            if (domain === "~") return skill.groups.length === 0;
            // The catalogue puts domain-only members under General.
            return skill.groups.includes(domain) && !skill.groups.some(group => group.startsWith(domain + "/"));
        });
    }
    #functionSkillState(editor, name) {
        const members = editor.functionMembers.get(this.#functionKey(editor.domain, name));
        if (!members) return this.#selectedInFunction(editor, name) ? "mixed" : "false";
        const selected = members.filter(skill => editor.selected.has(skill.skill_id)).length;
        if (!selected) return "false";
        return selected === members.length ? "true" : "mixed";
    }
    async #fetchFunctionSkills(domain, name, signal, page) {
        const params = new URLSearchParams({domain, function: name});
        const candidates = new Map(page?.items.map(skill => [skill.skill_id, skill]));
        let offset = page ? page.next_offset : 0;
        while (offset != null) {
            params.set("offset", offset);
            const next = await this.#client.request("/api/v1/skills/catalogue?" + params, {signal});
            if (signal.aborted) return [];
            for (const skill of next.items) candidates.set(skill.skill_id, skill);
            if (next.next_offset != null && next.next_offset <= offset) {
                throw new Error("Could not load all Skills in this function. Try again.");
            }
            offset = next.next_offset;
        }
        return [...candidates.values()];
    }
    #checkFunctionSelections() {
        const editor = this.#skillEditor;
        if (!editor?.ready || editor.query || !editor.domain) return;
        const domain = editor.domain;
        const signal = editor.functionChecks.signal;
        for (const name of editor.pages.functions?.items || []) {
            const key = this.#functionKey(domain, name);
            if (editor.functionMembers.has(key) || editor.checkingFunctions.has(key) || !this.#selectedInFunction(editor, name)) continue;
            editor.checkingFunctions.add(key);
            const page = name === editor.function ? editor.pages.skills : undefined;
            this.#fetchFunctionSkills(domain, name, signal, page).then(members => {
                if (signal.aborted || editor.functionMembers.has(key)) return;
                editor.functionMembers.set(key, members);
                if (editor.domain === domain && !editor.query) this.#renderSkillBrowser();
            }).catch(() => {
                // The checkbox can retry explicitly and report errors through the editor.
            }).finally(() => editor.checkingFunctions.delete(key));
        }
    }
    async #toggleFunctionSkills(name) {
        /**
         * Select or clear all published Skills in the requested function.
         * :param name: Function in the current domain, whether open or closed.
         */
        const editor = this.#skillEditor;
        if (this.#busy || !editor?.ready || editor.version === null || editor.query ||
            !editor.domain || name == null || editor.loading === "functions" || editor.bulk) return;

        const domain = editor.domain;
        const key = this.#functionKey(domain, name);
        const clearSelection = this.#functionSkillState(editor, name) === "true";
        const bulk = {request: new AbortController(), name};
        editor.bulk = bulk;
        this.#props("skill-editor-alert", {is_open: false});
        this.#renderSkillBrowser();
        try {
            const page = name === editor.function ? editor.pages.skills : undefined;
            const members = editor.functionMembers.get(key) ??
                await this.#fetchFunctionSkills(domain, name, bulk.request.signal, page);
            if (editor.bulk !== bulk) return;
            for (const skill of members) {
                if (clearSelection) editor.selected.delete(skill.skill_id);
                else editor.selected.set(skill.skill_id, skill);
            }
            editor.functionMembers.set(key, members);
            if (name === editor.function && editor.loading !== "skills") {
                editor.pages.skills = {items: members, next_offset: null};
            }
            this.#cancelSkillBulk();
            this.#renderSkillBrowser();
            this.#renderCurrentSkills();
            this.#controls();
            this.#checkFunctionSelections();
        } catch (error) {
            if (editor.bulk !== bulk) return;
            this.#cancelSkillBulk();
            this.#skillEditorFailure(error);
            this.#renderSkillBrowser();
        }
    }
    #cancelSkillBulk() {
        /**
         * Cancel any remaining requests for the function selection.
         */
        const editor = this.#skillEditor;
        if (!editor?.bulk) return;
        editor.bulk.request.abort();
        editor.bulk = null;
    }
    #renderSkillBrowser() {
        /**
         * Publish only presentation data for Dash to render the catalogue.
         */
        const editor = this.#skillEditor;
        if (!editor) {
            this.#props("skill-catalogue-view", {data: null});
            return;
        }
        const functions = editor.pages.functions?.items || [];
        this.#props("skill-catalogue-view", {data: {
            ready: editor.ready,
            domain: editor.domain,
            function: editor.function,
            query: Boolean(editor.query),
            level: editor.level,
            pages: {...editor.pages},
            loading: editor.loading,
            bulk_function: editor.bulk?.name ?? null,
            function_disabled: Boolean(editor.version === null || editor.loading === "functions" || editor.bulk),
            function_states: Object.fromEntries(functions.map(name => [name, this.#functionSkillState(editor, name)])),
            selected: [...editor.selected.keys()],
        }});
    }
    #renderCurrentSkills() {
        /**
         * Update the selection panel and indicate changes that have yet to be saved.
         */
        const editor = this.#skillEditor;
        this.#props("skill-selection-view", {data: [...editor.selected.values()]});
        const available = [...editor.selected.values()].filter(skill => !skill.withdrawn).length;
        this.#props("skill-selection-count", {children: `${available} selected`});
        this.#props("skill-save-status", {children: this.#hasSkillChanges() ? "Unsaved changes" : ""});
    }
    #workspaceSkillSelection(workspace) {
        /**
         * Keep withdrawn references in drafts until their owner removes them.
         * :param workspace: Saved workspace metadata returned by the backend.
         *
         * :return: Available Skills and withdrawn references for Current Skills.
         */
        return [...workspace.skills, ...(workspace.withdrawn_skill_ids || []).map(skill_id => ({
            skill_id,
            display_name: this.#skillGroupLabel(skill_id, "Withdrawn Skill"),
            withdrawn: true,
        }))];
    }
    #hasSkillChanges() {
        /**
         * Compare the current draft with its saved baseline.
         *
         * :return: Whether any selected Skill differs from the baseline.
         */
        const editor = this.#skillEditor;
        return Boolean(editor?.ready && (
            editor.selected.size !== editor.saved.size || [...editor.selected.keys()].some(id => !editor.saved.has(id))
        ));
    }
    #skillBrowserAction(id) {
        /**
         * Handle column navigation, pagination and selection edits.
         * :param id: Identifier of the activated browser control.
         */
        const editor = this.#skillEditor;
        if (!editor?.ready) return;
        const [, action, level] = id.split("-");
        const target = id.slice(`skill-${action}-${level}-`.length);
        if (action === "more" || action === "retry") {
            this.#loadSkillPage(level, action === "more");
        } else if (action === "back") {
            this.#cancelSkillBulk();
            editor.level = level;
            this.#renderSkillBrowser();
        } else if (action === "path") {
            const item = target;
            if (!editor.pages[level]?.items.includes(item)) return;
            if (level === "domains") {
                editor.domain = item;
                editor.function = null;
                delete editor.pages.functions;
                delete editor.pages.skills;
                editor.level = "functions";
            } else {
                editor.function = item;
                delete editor.pages.skills;
                editor.level = "skills";
            }
            this.#loadSkillPage(editor.level);
        } else if (action === "function") {
            const name = level === "mobile" ? editor.function : target;
            if (editor.pages.functions?.items.includes(name)) this.#toggleFunctionSkills(name);
        } else if (!this.#busy && (action === "option" || action === "remove")) {
            const page = editor.pages[editor.query ? "search" : "skills"];
            const skill = action === "remove"
                ? editor.selected.get(id.slice("skill-remove-".length))
                : page?.items.find(item => item.skill_id === id.slice("skill-option-".length));
            if (!skill) return;
            if (editor.selected.has(skill.skill_id)) editor.selected.delete(skill.skill_id);
            else editor.selected.set(skill.skill_id, skill);
            this.#cancelSkillBulk();
            this.#renderSkillBrowser();
            this.#renderCurrentSkills();
            this.#controls();
            this.#checkFunctionSelections();
        }
    }
    #discardSkillChanges() {
        /**
         * Restore the latest saved selection while keeping the current catalogue path.
         */
        const editor = this.#skillEditor;
        if (this.#busy || !editor?.ready) return;
        this.#cancelSkillBulk();
        editor.selected = new Map(editor.savedSkills.map(skill => [skill.skill_id, skill]));
        this.#props("skill-editor-alert", {is_open: false});
        this.#renderSkillBrowser();
        this.#renderCurrentSkills();
        this.#controls();
        this.#checkFunctionSelections();
    }
    async #saveSkillSelection() {
        /**
         * Save the whole draft once and let the user review conflicts before retrying.
         */
        if (this.#busy || !this.#hasSkillChanges() || this.#skillEditor.version === null) return;
        if (this.#skillEditor.bulk) {
            this.#cancelSkillBulk();
            this.#renderSkillBrowser();
        }
        const epoch = this.#epoch;
        this.#busy = true;
        this.#controls();
        this.#props("skill-editor-alert", {is_open: false});
        try {
            const workspace = await this.#client.request("/api/v1/workspace/skills", {
                method: "POST",
                body: {expected_version: this.#skillEditor.version, skill_ids: [...this.#skillEditor.selected.keys()]},
            });
            if (epoch !== this.#epoch) return;
            this.#workspace = workspace;
            this.#renderSkills();
            const editor = this.#skillEditor;
            editor.version = workspace.version;
            editor.savedSkills = this.#workspaceSkillSelection(workspace);
            editor.selected = new Map(editor.savedSkills.map(skill => [skill.skill_id, skill]));
            editor.saved = new Set(editor.selected.keys());
            this.#renderSkillBrowser();
            this.#renderCurrentSkills();
            this.#props("skill-save-status", {children: "Skills saved"});
        } catch (error) {
            if (epoch !== this.#epoch) return;
            if (error.status === 409) await this.#reviewSkillConflict(epoch, error);
            else this.#skillEditorFailure(error);
        } finally {
            if (epoch === this.#epoch) {this.#busy = false; this.#controls();}
        }
    }
    async #reviewSkillConflict(epoch, error) {
        /**
         * Show the latest saved selection and retain the draft for an explicit retry.
         * :param epoch: Sign-in generation that started the save.
         * :param error: Rejected save with safe correlation metadata.
         */
        try {
            const workspace = await this.#client.request("/api/v1/workspace");
            if (epoch !== this.#epoch) return;
            this.#workspace = workspace;
            this.#renderSkills();
            const editor = this.#skillEditor;
            editor.version = workspace.version;
            editor.savedSkills = this.#workspaceSkillSelection(workspace);
            const savedById = new Map(editor.savedSkills.map(skill => [skill.skill_id, skill]));
            editor.saved = new Set(savedById.keys());
            for (const [id, skill] of editor.selected) {
                const latest = savedById.get(id);
                if (latest) editor.selected.set(id, latest);
                else if (skill.withdrawn) editor.selected.delete(id);
            }
            this.#renderSkillBrowser();
            this.#renderCurrentSkills();
            this.#checkFunctionSelections();
            const saved = editor.savedSkills.map(skill => skill.display_name + (skill.withdrawn ? " (withdrawn)" : "")).join(", ") || "None";
            const message = workspace.version === null
                ? "This workspace is no longer available. Cancel and contact your administrator."
                : `Skills changed elsewhere. Currently saved: ${saved}. Your draft is still selected. Review it before saving again.`;
            this.#skillEditorFailure({message, correlationId: error.correlationId});
        } catch (refreshError) {
            if (epoch === this.#epoch) this.#skillEditorFailure(refreshError);
        }
    }
    #skillEditorFailure(error) {
        /**
         * Show a safe error in the editor or return to sign-in on authentication loss.
         * :param error: Safe client failure.
         */
        if (error.status === 401) this.#failure(error);
        else this.#props("skill-editor-alert", {is_open: true, children: this.#errorMessage(error)});
    }
    #closeSkillEditor() {
        /**
         * Discard editor state and remove the draft from the interface.
         */
        this.#skillEditor?.request?.abort();
        this.#skillEditor?.functionChecks.abort();
        this.#cancelSkillBulk();
        this.#skillEditor = null;
        this.#props("skill-editor", {style: {display: "none"}});
        this.#renderSkillBrowser();
        this.#props("skill-selection-view", {data: null});
        this.#props("skill-save-status", {children: ""});
        this.#props("skill-search", {value: ""});
        this.#props("skill-selection-count", {children: ""});
        this.#props("skill-editor-alert", {is_open: false, children: ""});
    }
    #controls() {
        /**
         * Prevent simultaneous sends or conversation switches while a stream is active.
         */
        const streaming = Boolean(this.#streamController);
        const blocked = this.#busy || streaming;
        this.#props("sign-in", {disabled: this.#busy});
        const dirty = this.#hasSkillChanges();
        this.#props("skill-search", {disabled: !this.#skillEditor?.ready});
        this.#props("save-skills", {disabled: this.#busy || !dirty || this.#skillEditor.version === null});
        this.#props("cancel-skills", {disabled: this.#busy || !dirty});
        this.#props("new-conversation", {disabled: blocked || !this.#signedIn});
        this.#props("send-message", {disabled: blocked || !this.#signedIn || this.#conversation?.can_continue === false});
        this.#props("message-input", {disabled: blocked || !this.#signedIn || this.#conversation?.can_continue === false});
        this.#props("stop-stream", {style: {display: streaming ? "inline-block" : "none"}});
        this.#props("conversation-state", {children: streaming ? "Responding" : this.#conversation?.is_interrupted ? "Interrupted" : this.#conversation?.can_continue === false ? "Unavailable" : "Ready", color: streaming ? "secondary" : this.#conversation?.can_continue === false ? "warning" : "success"});
        this.#publishSidebarView();
    }
    #failure(error) {
        /**
         * Show safe failure guidance and remove previous-user content on authentication loss.
         * :param error: Safe client error; raw provider exception data is never rendered.
         */
        if (error.status === 401) {++this.#epoch; this.#reset(); this.#busy = false; this.#loginError(this.#errorMessage(error)); this.#controls();}
        else this.#props("workspace-alert", {is_open: true, color: "warning", children: this.#errorMessage(error)});
    }
    #errorMessage(error) {
        /**
         * Append a server-generated UUID reference to safe guidance, never raw diagnostics.
         * :param error: Safe client failure with an optional response correlation ID.
         * :return: Plain display text, unchanged when no valid reference is available.
         */
        const message = error.message || "The backend is unavailable. Check the connection and try again.";
        const reference = error.correlationId;
        return typeof reference === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(reference)
            ? `${message} Reference: ${reference}` : message;
    }
    #loginError(message) {
        /**
         * Display non-sensitive sign-in guidance without echoing entered credentials.
         * :param message: Safe fixed client error guidance.
         */
        this.#props("sign-in-error", {is_open: true, children: message});
    }
    #click(event) {
        /**
         * Handle browser controls for authentication, streaming and the Skills panel.
         * :param event: Browser click event.
         */
        const button = event.target.closest("button");
        if (!button || button.disabled) return;
        const id = button.id;
        if (id === "sign-in") this.#signIn();
        else if (id === "sign-out") this.#signOut();
        else if (id === "send-message") this.#submit();
        else if (id === "stop-stream") this.#streamController?.abort();
        else if (id === "skills-toggle" || id === "skills-show") this.#toggle("skills");
    }
    #skillControl(id, value) {
        /**
         * Handle component events dispatched by the Dash clientside callback.
         * :param id: ID of the Skills control.
         * :param value: Current value for the search input.
         */
        if (!this.#signedIn) return;
        if (id === "skill-search") this.#searchSkills(value || "");
        else if (id === "show-chat") this.#showWorkspaceView(false);
        else if (id === "show-skill-browser") this.#showWorkspaceView(true);
        else if (id === "save-skills") this.#saveSkillSelection();
        else if (id === "cancel-skills") this.#discardSkillChanges();
        else if (id.startsWith("skill-")) this.#skillBrowserAction(id);
    }
    #key(event) {
        /**
         * Support Enter-to-send and token sign-in without persisting either input.
         * :param event: Browser keyboard event.
         */
        if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
        if (event.target.id === "message-input") {event.preventDefault(); this.#submit();}
        else if (event.target.id === "pilot-token") {event.preventDefault(); this.#signIn();}
    }
    #toggle(side) {
        /**
         * Collapse or restore a side panel without changing the conversation or stream.
         * :param side: Conversations or Skills panel selector.
         */
        const hidden = window.getComputedStyle(document.getElementById(side + "-panel")).display !== "none";
        this.#setPanelVisibility(side, !hidden);
    }
    #setPanelVisibility(side, visible) {
        /**
         * Show a sidebar with its resizer or expose its compact restore button.
         * :param side: Conversations or Skills panel selector.
         * :param visible: Whether the sidebar is expanded.
         */
        this.#props(side + "-panel", {style: {display: visible ? "flex" : "none"}});
        this.#props(side + "-resizer", {style: {display: visible ? "block" : "none"}});
        this.#props(side + "-show", {style: {display: visible ? "none" : "inline-block"}});
    }
    #resize(side) {
        /**
         * Add bounded pointer and keyboard resizing without external storage.
         * :param side: Side panel whose CSS width is updated.
         */
        const handle = document.getElementById(side + "-resizer");
        const panel = document.getElementById(side + "-panel");
        const minimum = side === "history" ? 200 : 220;
        const maximum = side === "history" ? 380 : 420;
        const update = width => {
            const value = Math.max(minimum, Math.min(maximum, width));
            document.documentElement.style.setProperty("--" + side + "-width", value + "px");
            handle.setAttribute("aria-valuenow", String(value));
        };
        handle.addEventListener("pointerdown", event => {
            const start = event.clientX;
            const width = panel.getBoundingClientRect().width;
            handle.setPointerCapture(event.pointerId);
            document.body.classList.add("resize-active");
            const move = current => update(width + (current.clientX - start) * (side === "history" ? 1 : -1));
            const stop = () => {handle.removeEventListener("pointermove", move); document.body.classList.remove("resize-active");};
            handle.addEventListener("pointermove", move);
            handle.addEventListener("pointerup", stop, {once: true});
            handle.addEventListener("pointercancel", stop, {once: true});
        });
        handle.addEventListener("keydown", event => {
            if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
            event.preventDefault();
            update(panel.getBoundingClientRect().width + (event.key === "ArrowRight" ? 15 : -15) * (side === "history" ? 1 : -1));
        });
    }
}

if (typeof document !== "undefined") WorkspaceController.start();
