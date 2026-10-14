import {ApiClient} from "./api_client.mjs";
import {AdkStream} from "./adk_stream.mjs";

export class WorkspaceController {
    #client;
    #epoch = 0;
    #signedIn = false;
    #busy = false;
    #streamController = null;
    #operation = null;
    #workspace = null;
    #conversation = null;
    #conversations = [];
    #messages = [];
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
                else if (error.status !== 401) this.#loginError("The backend is unavailable. Check the connection and try again.");
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
                else this.#loginError(error.message);
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
        this.#props("workspace-screen", {style: {display: "flex"}});
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
        this.#operation?.abort();
        this.#streamController?.abort();
        this.#reset();
        this.#busy = true;
        this.#controls();
        try {await this.#client.request("/api/v1/auth/logout", {method: "POST"});}
        catch {this.#loginError("Sign-out could not be confirmed. Retry Sign out before using another account."); this.#props("sign-out", {style: {display: "inline-block"}});}
        finally {this.#busy = false; this.#controls();}
    }
    #reset() {
        /**
         * Remove previous-user data from memory and the UI without browser storage.
         */
        this.#signedIn = false;
        this.#workspace = this.#conversation = null;
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
        this.#props("message-input", {value: ""});
        this.#props("workspace-alert", {is_open: false});
        this.#messages.push({role: "user", text}, {role: "assistant", text: ""});
        const answerIndex = this.#messages.length - 1;
        this.#renderMessages();
        this.#controls();
        let reader;
        let failure = null;
        try {
            const response = await this.#client.stream(id, text, controller.signal);
            reader = response.body.getReader();
            const decoder = new TextDecoder();
            const projection = new AdkStream(answer => {
                if (epoch !== this.#epoch) return;
                this.#messages[answerIndex].text = answer;
                this.#renderMessages();
            });
            while (true) {
                const {value, done} = await reader.read();
                if (done) break;
                projection.feed(decoder.decode(value, {stream: true}));
            }
            projection.feed(decoder.decode());
            projection.finish();
        } catch (error) {
            failure = controller.signal.aborted ? new Error("Response stopped. This conversation may be read-only; saved history remains available.") : error;
            controller.abort();
        } finally {
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
            children = [this.#element("Div", {className: "welcome", children: [this.#element("Img", {src: "/assets/tangram.svg", alt: "", className: "welcome-symbol"}), this.#element("H2", {children: "What would you like to work on?"}), this.#element("P", {children: "Ask a question or describe your Goal. MOSAIC brings together your assigned Skills and the capabilities they need."}), this.#element("Div", {className: "welcome-hint", children: "Your Skills are shown on the right. You can read earlier conversations or start something new."})]})];
        } else {
            children = this.#messages.map(message => this.#element("Div", {className: "message message-" + message.role, children: [this.#element("Div", {className: "message-label", children: message.role === "user" ? "You" : "MOSAIC"}), message.role === "user" ? this.#element("Div", {className: "message-body", children: message.text}) : message.text ? this.#element("Markdown", {className: "message-body", children: message.text, dangerously_allow_html: false, link_target: "_blank", mathjax: false, highlight_config: {theme: "light"}}, "dash_core_components") : this.#element("Div", {className: "streaming-placeholder", children: "Working on your request"})]}));
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
        if (!skills.length) {this.#props("skills-list", {children: this.#element("P", {className: "empty-skills", children: "No Skills are assigned to your workspace. Contact your administrator to add them."})}); return;}
        const groups = new Map();
        for (const skill of skills) {
            const group = [...skill.groups].sort((left, right) => right.split("/").length - left.split("/").length || left.localeCompare(right))[0] || "Assigned Skills";
            if (!groups.has(group)) groups.set(group, []);
            groups.get(group).push(skill);
        }
        const items = [...groups].sort(([left], [right]) => left.localeCompare(right)).map(([group, assigned], index) => this.#element("AccordionItem", {
            item_id: "group-" + index,
            title: group.split("/").map(value => value.replaceAll("-", " ")).join(" › ") + ` (${assigned.length})`,
            children: assigned.map(skill => this.#element("Details", {className: "skill-entry", children: [this.#element("Summary", {children: skill.display_name}), this.#element("P", {className: "skill-description", children: skill.description})]})),
        }, "dash_bootstrap_components"));
        this.#props("skills-list", {children: this.#element("Accordion", {children: items, always_open: true, start_collapsed: false, active_item: items.map(item => item.props.item_id)}, "dash_bootstrap_components")});
    }
    #controls() {
        /**
         * Prevent simultaneous sends or conversation switches while a stream is active.
         */
        const streaming = Boolean(this.#streamController);
        const blocked = this.#busy || streaming;
        this.#props("sign-in", {disabled: this.#busy});
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
        if (error.status === 401) {++this.#epoch; this.#reset(); this.#busy = false; this.#loginError(error.message); this.#controls();}
        else this.#props("workspace-alert", {is_open: true, color: "warning", children: error.message || "The backend is unavailable. Check the connection and try again."});
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
        this.#props(side + "-panel", {style: {display: hidden ? "none" : "flex"}});
        this.#props(side + "-resizer", {style: {display: hidden ? "none" : "block"}});
        this.#props(side + "-show", {style: {display: hidden ? "inline-block" : "none"}});
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
