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
        document.addEventListener("input", event => {
            if (event.target.id === "skill-search" && this.#skillEditor) {
                this.#searchSkills(event.target.value);
            }
        });
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
        this.#props("workspace-navigation", {style: {display: "none"}});
        this.#props("workspace-main", {className: "page-main"});
        this.#conversations = this.#messages = [];
        this.#streamController = this.#operation = null;
        document.getElementById("pilot-token").value = "";
        this.#props("message-input", {value: ""});
        for (const id of ["user-label", "messages", "conversation-list", "skills-list", "skill-count"]) this.#props(id, {children: ""});
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
        this.#renderHistory();
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
        this.#conversations = result.conversations.sort((left, right) => right.last_activity_at.localeCompare(left.last_activity_at));
        this.#renderHistory();
    }
    #renderHistory() {
        /**
         * Render a compact Bootstrap history list with visible interrupted labels.
         */
        const children = this.#conversations.map(conversation => this.#element("Button", {
            id: "conversation-" + conversation.conversation_id,
            className: "history-item" + (conversation.conversation_id === this.#conversation?.conversation_id ? " active" : ""),
            color: "link", disabled: this.#busy || Boolean(this.#streamController),
            children: [this.#element("Span", {className: "history-title", children: conversation.title || "New conversation"}), this.#element("Span", {className: "history-meta", children: [new Date(conversation.last_activity_at).toLocaleDateString(undefined, {month: "short", day: "numeric"}), ...(conversation.is_interrupted ? [this.#element("Span", {className: "interrupted-label", children: "Interrupted"})] : [])]})],
        }, "dash_bootstrap_components"));
        this.#props("conversation-list", {children});
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
        const children = this.#selectedSkillCards(this.#workspace ? this.#workspaceSkillSelection(this.#workspace) : []);
        this.#props("skills-list", {children: children.length ? children : this.#element("P", {
            className: "browser-empty", children: "No Skills are selected. Open the Skills tab to choose them.",
        })});
    }
    #showWorkspaceView(skills) {
        /**
         * Switch workspace views while preserving the conversation and Skill draft.
         * :param skills: Whether to show the Skill browser.
         */
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
            domain: null, function: null, query: "", level: "domains", timer: null,
            pages: {}, request: null, loading: null,
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
                this.#renderSkillBrowser();
            }
        }
    }
    #searchSkills(value) {
        /**
         * Debounce catalogue searches and cancel superseded requests.
         * :param value: Text entered in the search field.
         */
        const editor = this.#skillEditor;
        if (!editor?.ready) return;
        clearTimeout(editor.timer);
        editor.request?.abort();
        editor.query = value.trim().slice(0, 200);
        delete editor.pages.search;
        editor.loading = editor.query ? "search" : null;
        this.#renderSkillBrowser();
        if (editor.query) editor.timer = setTimeout(() => this.#loadSkillPage("search"), 250);
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
    #renderSkillBrowser() {
        /**
         * Render the current catalogue path and its independently paged columns.
         */
        const editor = this.#skillEditor;
        if (!editor) {
            this.#props("skill-browser-columns", {children: ""});
            this.#props("skill-browser-path", {children: ""});
            return;
        }
        const path = [this.#element("Button", {id: "skill-back-domains", className: "btn btn-link", children: "Domains"})];
        if (editor.domain) path.push(" › ", this.#element("Button", {
            id: "skill-back-functions", className: "btn btn-link", children: this.#skillGroupLabel(editor.domain, "Ungrouped"),
        }));
        if (editor.function) path.push(" › ", this.#skillGroupLabel(editor.function, "General"));
        this.#props("skill-browser-path", {children: editor.query ? "Across all domains" : path});
        const levels = editor.query ? [["search", "Search results"]] :
            [["domains", "Domain"], ["functions", "Function"], ["skills", "Skill"]];
        const columns = levels.map(([level, title]) => {
            const page = editor.pages[level];
            const items = (page?.items || []).map((item, index) => {
                if (typeof item !== "string") {
                    const path = item.groups.filter(group => group.includes("/")).join(" · ") || item.groups.join(" · ");
                    return this.#element("Div", {className: "browser-skill", key: level + "-" + item.skill_id, children: [
                        this.#element("Button", {
                            id: "skill-option-" + index, type: "button", className: "skill-option",
                            "aria-label": "Select " + item.display_name,
                            "aria-pressed": String(editor.selected.has(item.skill_id)),
                        }),
                        this.#skillDetails(item, true),
                        ...(level === "search" && path ? [this.#element("Small", {children: path.replaceAll("/", " › ").replaceAll("-", " ")})] : []),
                    ]});
                }
                const active = item === (level === "domains" ? editor.domain : editor.function);
                return this.#element("Button", {
                    id: "skill-path-" + level + "-" + index, type: "button", className: "browser-row",
                    "aria-pressed": String(active),
                    children: [this.#skillGroupLabel(item, level === "domains" ? "Ungrouped" : "General"), this.#element("Span", {"aria-hidden": "true", children: "›"})],
                });
            });
            if (editor.loading === level) items.push(this.#element("P", {className: "browser-empty", role: "status", children: "Loading…"}));
            else if (!items.length) {
                const parent = level === "functions" ? editor.domain : level === "skills" ? editor.function : true;
                const message = !editor.ready ? "Loading workspace…" : page ? "No matching Skills." :
                    parent ? "No results loaded." : level === "functions" ? "Choose a domain." : "Choose a function.";
                items.push(this.#element("P", {className: "browser-empty", children: message}));
                if (editor.ready && parent && !page) items.push(this.#element("Button", {
                    id: "skill-retry-" + level, type: "button", className: "btn btn-link btn-sm", children: "Try again",
                }));
            }
            if (page?.next_offset != null) items.push(this.#element("Button", {
                id: "skill-more-" + level, type: "button", className: "btn btn-link btn-sm",
                disabled: editor.loading !== null, children: "Load more",
            }));
            return this.#element("Section", {
                className: "browser-column" + (editor.query || level === editor.level ? " current-column" : ""),
                children: [this.#element("H2", {children: title}), this.#element("Div", {className: "browser-list", children: items})],
            });
        });
        this.#props("skill-browser-columns", {
            className: "browser-columns" + (editor.query ? " search-results" : ""), children: columns,
        });
    }
    #renderCurrentSkills() {
        /**
         * Update the selection panel and indicate changes that have yet to be saved.
         */
        const editor = this.#skillEditor;
        const items = this.#selectedSkillCards(editor.selected.values(), true);
        this.#props("current-skills", {children: items.length ? items : "No Skills selected."});
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
    #skillDetails(skill, open = false) {
        /**
         * Use the Skill name as the disclosure for its description.
         * :param skill: Skill metadata to display.
         * :param open: Whether the description is initially visible.
         *
         * :return: Native keyboard-accessible disclosure.
         */
        return this.#element("Details", {
            className: "skill-details", open,
            children: [
                this.#element("Summary", {children: skill.display_name}),
                this.#element("P", {className: "skill-description", children: skill.description}),
            ],
        });
    }
    #selectedSkillCards(skills, editable = false) {
        /**
         * Render the same domain, function and Skill cards in both workspace views.
         * :param skills: Saved Skills or the editor's draft selection.
         * :param editable: Whether to show removal controls.
         *
         * :return: Group headings and Skill cards in display order.
         */
        const ordered = [...skills].map(skill => {
            if (skill.withdrawn) return {skill, domain: "Withdrawn", category: null};
            const groups = [...skill.groups].sort();
            const path = groups.find(group => group.includes("/")) || groups[0] || "~";
            const [domain, category = "~"] = path.split("/");
            return {
                skill,
                domain: this.#skillGroupLabel(domain, "Ungrouped"),
                category: this.#skillGroupLabel(category, "General"),
            };
        }).sort((left, right) =>
            Number(Boolean(left.skill.withdrawn)) - Number(Boolean(right.skill.withdrawn)) ||
            left.domain.localeCompare(right.domain, "en-GB") ||
            (left.category || "").localeCompare(right.category || "", "en-GB") ||
            left.skill.display_name.localeCompare(right.skill.display_name, "en-GB") ||
            left.skill.skill_id.localeCompare(right.skill.skill_id, "en-GB"));
        const items = [];
        let currentDomain;
        let currentCategory;
        for (const {skill, domain, category} of ordered) {
            if (domain !== currentDomain || (skill.withdrawn && currentCategory !== null)) {
                items.push(this.#element("H3", {
                    className: skill.withdrawn ? "selected-domain withdrawn-heading" : "selected-domain",
                    children: domain,
                }));
                if (skill.withdrawn) items.push(this.#element("P", {
                    className: "withdrawn-note",
                    children: editable
                        ? "These Skills will not be used in new Goals. Remove them and click Save Skills to update your workspace."
                        : "These Skills will not be used in new Goals.",
                }));
                currentDomain = domain;
                currentCategory = null;
            }
            if (category !== currentCategory) {
                items.push(this.#element("H4", {className: "selected-category", children: category}));
                currentCategory = category;
            }
            items.push(this.#element("Div", {
                className: skill.withdrawn ? "selected-item withdrawn-item" : "selected-item",
                key: skill.skill_id,
                children: [
                    skill.withdrawn ? this.#element("Strong", {
                        className: "withdrawn-skill-name", children: skill.display_name,
                    }) : this.#skillDetails(skill),
                    ...(editable ? [this.#element("Button", {
                        id: "skill-remove-" + skill.skill_id, type: "button", className: "btn btn-link",
                        "aria-label": "Remove " + skill.display_name, children: "×",
                    })] : []),
                ],
            }));
        }
        return items;
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
        const [, action, level, index] = id.split("-");
        if (action === "more" || action === "retry") {
            this.#loadSkillPage(level, action === "more");
        } else if (action === "back") {
            editor.level = level;
            this.#renderSkillBrowser();
        } else if (action === "path") {
            const item = editor.pages[level]?.items[Number(index)];
            if (!item) return;
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
        } else if (!this.#busy && (action === "option" || action === "remove")) {
            const page = editor.pages[editor.query ? "search" : "skills"];
            const skill = action === "remove"
                ? editor.selected.get(id.slice("skill-remove-".length))
                : page?.items[Number(level)];
            if (!skill) return;
            if (editor.selected.has(skill.skill_id)) editor.selected.delete(skill.skill_id);
            else editor.selected.set(skill.skill_id, skill);
            const position = page?.items.findIndex(item => item.skill_id === skill.skill_id);
            if (position >= 0) this.#props("skill-option-" + position, {"aria-pressed": String(editor.selected.has(skill.skill_id))});
            this.#renderCurrentSkills();
            this.#controls();
        }
    }
    #discardSkillChanges() {
        /**
         * Restore the latest saved selection while keeping the current catalogue path.
         */
        const editor = this.#skillEditor;
        if (this.#busy || !editor?.ready) return;
        editor.selected = new Map(editor.savedSkills.map(skill => [skill.skill_id, skill]));
        this.#props("skill-editor-alert", {is_open: false});
        this.#renderSkillBrowser();
        this.#renderCurrentSkills();
        this.#controls();
    }
    async #saveSkillSelection() {
        /**
         * Save the whole draft once and let the user review conflicts before retrying.
         */
        if (this.#busy || !this.#hasSkillChanges() || this.#skillEditor.version === null) return;
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
            this.#renderCurrentSkills();
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
        clearTimeout(this.#skillEditor?.timer);
        this.#skillEditor?.request?.abort();
        this.#skillEditor = null;
        this.#props("skill-editor", {style: {display: "none"}});
        this.#renderSkillBrowser();
        this.#props("current-skills", {children: ""});
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
        this.#renderHistory();
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
         * Delegate Bootstrap button actions, including dynamically rendered history.
         * :param event: Browser click event.
         */
        const button = event.target.closest("button");
        if (!button || button.disabled) return;
        const id = button.id;
        if (id === "sign-in") this.#signIn();
        else if (id === "sign-out") this.#signOut();
        else if (id === "new-conversation") this.#newConversation();
        else if (id === "send-message") this.#submit();
        else if (id === "stop-stream") this.#streamController?.abort();
        else if (id === "show-chat" && this.#signedIn) this.#showWorkspaceView(false);
        else if (id === "show-skill-browser" && this.#signedIn) this.#showWorkspaceView(true);
        else if (id === "save-skills") this.#saveSkillSelection();
        else if (id === "cancel-skills") this.#discardSkillChanges();
        else if (id.startsWith("skill-")) this.#skillBrowserAction(id);
        else if (id === "history-toggle" || id === "history-show") this.#toggle("history");
        else if (id === "skills-toggle" || id === "skills-show") this.#toggle("skills");
        else if (id.startsWith("conversation-")) this.#loadConversation(id.slice(13));
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
