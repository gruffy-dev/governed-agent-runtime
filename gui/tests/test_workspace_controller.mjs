import assert from "node:assert/strict";
import test from "node:test";
import {WorkspaceController} from "../src/mosaic_gui/assets/workspace_controller.mjs";

class TestWorkspaceController {
    static setup(initialState = {}) {
        const originals = Object.fromEntries(["document", "window", "fetch", "requestAnimationFrame", "setInterval", "clearInterval", "performance"].map(key => [key, globalThis[key]]));
        const elements = new Map();
        const listeners = new Map();
        const requests = [];
        const timers = new Map();
        const element = id => {
            if (!elements.has(id)) elements.set(id, {id, value: "", disabled: false, dataset: {}, scrollHeight: 0, scrollTop: 0, clientHeight: 100,
                setAttribute() {}, append() {}, addEventListener(name, callback) {listeners.set(id + ":" + name, callback);}, querySelectorAll: () => []});
            return elements.get(id);
        };
        globalThis.document = {createElement: () => element("pilot-token"), getElementById: element,
            addEventListener: (name, callback) => listeners.set(name, callback)};
        globalThis.window = {addEventListener() {}, confirm: () => true, dash_clientside: {set_props: (id, props) => Object.assign(element(id), props)}};
        globalThis.requestAnimationFrame = callback => callback();
        const detail = {conversation_id: "synthetic-chat", title: null, can_continue: true, is_interrupted: false, messages: initialState.messages || [], latest_job: initialState.latestJob || null};
        const state = {failCreation: false, failureStatus: 503, correlationId: null, failSignIn: false, failStream: false, manualStream: null, skills: [], catalogue: [], version: 1, now: 0, ...initialState};
        globalThis.performance = {now: () => state.now};
        globalThis.setInterval = callback => {const id = {}; timers.set(id, callback); return id;};
        globalThis.clearInterval = id => timers.delete(id);
        globalThis.fetch = async (url, options) => {
            requests.push({url, options});
            const path = new URL(url).pathname;
            const failure = () => Response.json({detail: "private synthetic diagnostic"}, {status: state.failureStatus, headers: state.correlationId ? {"X-Correlation-ID": state.correlationId} : {}});
            if (path === "/api/v1/auth/token") return state.failSignIn ? failure() : new Response(null, {status: 204});
            if (path === "/api/v1/workspace") return Response.json({user_id: "synthetic-user", skills: state.skills, withdrawn_skill_ids: state.withdrawn, version: state.version});
            if (path === "/api/v1/skills/catalogue") {
                const params = new URL(url).searchParams;
                const query = params.get("q");
                if (query) return Response.json({items: state.catalogue.filter(skill => skill.skill_id.includes(query)), next_offset: null});
                if (params.has("function") && state.functionPageSize) {
                    const offset = Number(params.get("offset"));
                    const end = offset + state.functionPageSize;
                    if (offset === state.failFunctionOffset) return failure();
                    return Response.json({
                        items: state.catalogue.slice(offset, end),
                        next_offset: end < state.catalogue.length ? end : null,
                    });
                }
                if (params.has("function")) {
                    const functionName = params.get("function");
                    const items = state.functions
                        ? state.catalogue.filter(skill => skill.groups.includes("example/" + functionName))
                        : state.catalogue;
                    return Response.json({items, next_offset: null});
                }
                if (params.has("domain")) return Response.json({items: state.functions || ["function"], next_offset: null});
                return Response.json(params.has("offset") ?
                    {items: ["second-domain"], next_offset: null} : {items: ["example"], next_offset: 1});
            }
            if (path === "/api/v1/workspace/skills") {
                const body = JSON.parse(options.body);
                if (body.expected_version !== state.version) return Response.json({}, {status: 409});
                state.skills = state.catalogue.filter(skill => body.skill_ids.includes(skill.skill_id));
                state.withdrawn = state.withdrawn?.filter(id => body.skill_ids.includes(id));
                return Response.json({user_id: "synthetic-user", skills: state.skills, withdrawn_skill_ids: state.withdrawn, version: ++state.version});
            }
            if (path === "/api/v1/conversations" && options.method === "POST") {
                if (state.failCreation) return failure();
                return Response.json(detail, {status: 201});
            }
            if (path === "/api/v1/conversations") return Response.json({conversations: state.conversations || []});
            if (path === "/api/v1/conversations/synthetic-chat/jobs") {
                if (state.failSubmission) return failure();
                detail.latest_job = {job_id: "synthetic-job", status: "running"};
                return Response.json(detail.latest_job, {status: 202});
            }
            if (path === "/api/v1/conversations/jobs/synthetic-job/stop") {
                detail.latest_job.status = "cancelled";
                state.stopStream?.();
                return Response.json(detail.latest_job);
            }
            if (path === "/api/v1/conversations/jobs/synthetic-job") {
                detail.latest_job.status = state.jobStatus || (detail.latest_job.status === "cancelled" ? "cancelled" : state.failStream ? "failed" : "succeeded");
                return Response.json(detail.latest_job);
            }
            if (path === "/api/v1/conversations/jobs/synthetic-job/events") {
                let body = state.manualStream ? state.manualStream(options.signal, Number(new URL(url).searchParams.get("after")))
                    : state.failStream ? 'data: {"error":"private synthetic diagnostic"}\n\n'
                    : 'data: {"content":{"role":"model","parts":[{"text":"Synthetic answer"}]},"partial":false}\n\n';
                if (body instanceof ReadableStream) {
                    const reader = body.getReader();
                    let ended = false;
                    body = new ReadableStream({
                        start(controller) {
                            state.stopStream = () => {
                                ended = true;
                                controller.close();
                                reader.cancel().catch(() => {});
                            };
                        },
                        async pull(controller) {
                            const {value, done} = await reader.read();
                            if (ended) return;
                            if (done) {ended = true; controller.close();}
                            else controller.enqueue(value);
                        },
                        cancel() {ended = true; return reader.cancel();},
                    });
                }
                return new Response(body, {headers: {"Content-Type": "text/event-stream", ...(state.correlationId ? {"X-Correlation-ID": state.correlationId} : {})}});
            }
            if (path === "/api/v1/conversations/synthetic-chat") return Response.json(detail);
            throw new Error("Unexpected synthetic request: " + path);
        };
        new WorkspaceController({dataset: {backendUrl: "https://api.example.com"}});
        return {element, requests, state, timers,
            tick: milliseconds => {state.now += milliseconds; for (const callback of timers.values()) callback();},
            click: id => {
                if (id.startsWith("skill-") || ["show-chat", "show-skill-browser", "save-skills", "cancel-skills"].includes(id)) {
                    if (!element(id).disabled) window.mosaicSkillAction(id);
                } else if (id === "new-conversation") {
                    if (!element(id).disabled) window.mosaicConversationAction();
                } else if (id === "send-message" || id === "stop-stream") {
                    if (!element(id).disabled) window.mosaicComposerAction(id, element("message-input").value);
                } else if (id.startsWith("conversation-")) {
                    window.mosaicConversationAction(id.slice("conversation-".length));
                } else {
                    const control = id === "sign-in" ? "sign-in-form:submit" : id + ":click";
                    if (!element(id).disabled) listeners.get(control)({preventDefault() {}});
                }
            },
            input: (id, value) => window.mosaicSkillAction(id, value),
            creations: () => requests.filter(request => new URL(request.url).pathname === "/api/v1/conversations" && request.options.method === "POST"),
            restore: () => {
                for (const [key, value] of Object.entries(originals)) {
                    if (value === undefined) delete globalThis[key];
                    else globalThis[key] = value;
                }
            }};
    }
    static async settle() {
        for (let index = 0; index < 12; ++index) await new Promise(resolve => setImmediate(resolve));
    }
    static run() {
        test("completed Mermaid responses render through Dash and stale results cannot restore old chat", async () => {
            const source = "```mermaid\nflowchart LR\nA --> B\n```";
            const fixture = this.setup({
                messages: [{role: "assistant", text: source}],
                conversations: [{conversation_id: "synthetic-chat", last_activity_at: "2026-01-01", title: "Diagram"}],
            });
            try {
                await this.settle();
                fixture.click("conversation-synthetic-chat");
                await this.settle();
                const request = fixture.element("transcript-render-request").data;
                assert.deepEqual(request.messages, [{role: "assistant", text: source}]);
                assert.deepEqual(Object.keys(request).sort(), ["messages", "sequence"]);
                const diagram = [{type: "Div", props: {children: "Rendered diagram"}}];
                window.mosaicTranscript({sequence: request.sequence, children: diagram});
                assert.deepEqual(fixture.element("message-transcript").children, diagram);
                fixture.click("new-conversation");
                await this.settle();
                window.mosaicTranscript({sequence: request.sequence, children: diagram});
                assert.deepEqual(fixture.element("message-transcript").children, []);
                fixture.click("sign-out");
                await this.settle();
                window.mosaicTranscript({sequence: request.sequence, children: diagram});
                assert.equal(fixture.element("message-transcript").children, "");
                assert.equal(fixture.element("transcript-render-request").data, null);
                assert.equal(fixture.element("transcript-render-result").data, null);
            } finally {fixture.restore();}
        });
        test("unlabelled code fences reach Python rendering without a Mermaid keyword", async () => {
            for (const source of ["```\nflowchart LR\nA --> B\n```", "~~~\nsequenceDiagram\nA->>B: Hello\n~~~"]) {
                const fixture = this.setup({
                    messages: [{role: "assistant", text: source}],
                    conversations: [{conversation_id: "synthetic-chat", last_activity_at: "2026-01-01", title: "Diagram"}],
                });
                try {
                    await this.settle();
                    fixture.click("conversation-synthetic-chat");
                    await this.settle();
                    assert.equal(fixture.element("transcript-render-request").data.messages[0].text, source);
                } finally {fixture.restore();}
            }
        });
        test("Mermaid rendering waits for stream completion and preserves source", async () => {
            let stream;
            const messages = [];
            const fixture = this.setup({messages, manualStream: () => new ReadableStream({start(controller) {stream = controller;}})});
            try {
                await this.settle();
                fixture.element("message-input").value = "Show a diagram";
                fixture.click("send-message");
                await this.settle();
                const source = "```mermaid\nflowchart LR\nA --> B\n```";
                const event = partial => new TextEncoder().encode("data: " + JSON.stringify({content: {role: "model", parts: [{text: source}]}, partial}) + "\n\n");
                stream.enqueue(event(true));
                await this.settle();
                assert.equal(fixture.element("transcript-render-request").data, undefined);
                messages.push({role: "user", text: "Show a diagram"}, {role: "assistant", text: source});
                stream.enqueue(event(false));
                stream.close();
                await this.settle();
                assert.equal(fixture.element("transcript-render-request").data.messages[1].text, source);
            } finally {fixture.restore();}
        });
        test("Marketplace sends browser API results back to Dash and preserves the chat draft", async () => {
            const fixture = this.setup();
            try {
                await this.settle();
                fixture.element("message-input").value = "Keep this chat draft";
                fixture.click("show-skill-browser");
                const event = fixture.element("skill-editor-event").data;
                assert.equal(event.action, "open");
                window.mosaicSkillState({sequence: event.sequence, request: {id: event.sequence, kind: "workspace"}});
                await this.settle();
                const result = fixture.element("skill-editor-event").data;
                assert.equal(result.action, "result");
                assert.equal(result.value.data.version, 1);
                assert.equal(result.value.data.user_id, undefined);
                window.mosaicSkillState({sequence: result.sequence, request: null});
                fixture.click("show-chat");
                assert.equal(fixture.element("message-input").value, "Keep this chat draft");
            } finally {fixture.restore();}
        });
        test("Sidebar navigation publishes row IDs separately from private titles", async () => {
            const fixture = this.setup({conversations: [{
                conversation_id: "synthetic-chat",
                title: "Private conversation title",
                last_activity_at: "2026-11-12T10:30:00Z",
                is_interrupted: true,
            }]});
            try {
                await this.settle();
                assert.deepEqual(fixture.element("conversation-row-ids").data, ["synthetic-chat"]);
                const sidebar = fixture.element("conversation-sidebar-view");
                assert.equal(sidebar.data.conversations[0].title, "Private conversation title");
                assert.equal(sidebar.data.active, null);
                fixture.click("conversation-unknown");
                assert.equal(fixture.requests.some(request => request.url.endsWith("/unknown")), false);
                fixture.click("conversation-synthetic-chat");
                await this.settle();
                assert.equal(sidebar.data.active, "synthetic-chat");
                fixture.click("new-conversation");
                await this.settle();
                assert.equal(sidebar.data.active, null);
                assert.equal(fixture.creations().length, 0);
            } finally {fixture.restore();}
        });
        test("login, blank sends and New conversation do not create sessions; first send creates once", async () => {
            const fixture = this.setup();
            try {
                await this.settle();
                assert.equal(fixture.creations().length, 0);
                assert.equal(fixture.element("send-message").disabled, false);
                fixture.click("new-conversation");
                await this.settle();
                fixture.element("message-input").value = "   ";
                fixture.click("send-message");
                await this.settle();
                assert.equal(fixture.creations().length, 0);
                fixture.element("message-input").value = "First message";
                fixture.click("send-message");
                fixture.click("send-message");
                await this.settle();
                assert.equal(fixture.creations().length, 1);
                fixture.element("message-input").value = "Second message";
                fixture.click("send-message");
                await this.settle();
                assert.equal(fixture.creations().length, 1);
                fixture.click("new-conversation");
                await this.settle();
                assert.equal(fixture.creations().length, 1);
                assert.equal(fixture.element("conversation-title").children, "New conversation");
            } finally {fixture.restore();}
        });
        test("creation failure retains the draft text and does not send or automatically retry", async () => {
            const fixture = this.setup();
            try {
                await this.settle();
                fixture.state.failCreation = true;
                fixture.element("message-input").value = "Keep this message";
                fixture.click("send-message");
                await this.settle();
                assert.equal(fixture.creations().length, 1);
                assert.equal(fixture.element("message-input").value, "Keep this message");
                assert.equal(fixture.element("send-message").disabled, false);
                assert.equal(fixture.requests.some(request => request.url.endsWith("/synthetic-chat/jobs")), false);
                fixture.state.failCreation = false;
                fixture.click("send-message");
                await this.settle();
                assert.equal(fixture.creations().length, 2);
            } finally {fixture.restore();}
        });
        test("request errors show only safe guidance and a valid UUID reference", async () => {
            for (const [status, reference] of [[503, "12345678-1234-1234-1234-123456789abc"], [401, "12345678-1234-1234-1234-123456789abc"], [503, null], [503, "<script>private</script>"], [503, "x".repeat(1000)]]) {
                const fixture = this.setup();
                try {
                    await this.settle();
                    Object.assign(fixture.state, {failCreation: true, failureStatus: status, correlationId: reference});
                    fixture.element("message-input").value = "Synthetic message";
                    fixture.click("send-message");
                    await this.settle();
                    const message = fixture.element(status === 401 ? "sign-in-error" : "workspace-alert").children;
                    assert.equal(message.includes("Reference:"), typeof reference === "string" && reference.startsWith("12345678-"));
                    if (reference?.startsWith("12345678-")) assert.ok(message.endsWith("Reference: " + reference));
                    assert.equal(message.includes("private"), false);
                } finally {fixture.restore();}
            }
        });
        test("sign-in rejection includes its reference without displaying the token", async () => {
            const fixture = this.setup();
            try {
                await this.settle();
                Object.assign(fixture.state, {failSignIn: true, failureStatus: 401, correlationId: "12345678-1234-1234-1234-123456789abc"});
                fixture.element("pilot-token").value = "synthetic-private-credential";
                fixture.click("sign-in");
                await this.settle();
                const message = fixture.element("sign-in-error").children;
                assert.ok(message.endsWith("Reference: " + fixture.state.correlationId));
                assert.equal(message.includes("synthetic-private-credential"), false);
                assert.equal(message.includes("private synthetic diagnostic"), false);
            } finally {fixture.restore();}
        });
        test("SSE failure retains the stream response reference after history refresh", async () => {
            const fixture = this.setup();
            try {
                await this.settle();
                Object.assign(fixture.state, {failStream: true, correlationId: "12345678-1234-1234-1234-123456789abc"});
                fixture.element("message-input").value = "Synthetic message";
                fixture.click("send-message");
                await this.settle();
                const message = fixture.element("workspace-alert").children;
                assert.ok(message.endsWith("Reference: " + fixture.state.correlationId));
                assert.equal(message.includes("private"), false);
                assert.equal(fixture.element("invocation-activity").style.display, "none");
                assert.equal(fixture.timers.size, 0);
            } finally {fixture.restore();}
        });
        test("progress follows stream activity, elapsed time never invents stages, and completion removes it", async () => {
            const fixture = this.setup();
            try {
                await this.settle();
                fixture.state.skills = [{skill_id: "inspect-logs", display_name: "Inspect application logs", groups: ["logs"]}];
                fixture.click("new-conversation");
                await this.settle();
                let source;
                fixture.state.manualStream = () => new ReadableStream({start(controller) {source = controller;}});
                fixture.element("message-input").value = "Investigate this application";
                fixture.click("send-message");
                await this.settle();
                assert.equal(fixture.element("invocation-activity").style.display, "flex");
                assert.equal(fixture.timers.size, 1);
                fixture.tick(4500);
                assert.equal(fixture.element("invocation-elapsed").children, "4s elapsed");
                assert.equal(fixture.element("invocation-stage").children, "Waiting for a response");
                const feed = event => source.enqueue(new TextEncoder().encode("data: " + JSON.stringify(event) + "\n\n"));
                feed({content: {role: "model", parts: [{functionCall: {name: "load_skills", id: "load"}}]}});
                feed({content: {role: "user", parts: [{functionResponse: {name: "load_skills", id: "load", response: {status: "loaded", loaded_skills: [{name: "inspect-logs", required_capability_names: ["splunk.index.errors.read"]}]}}}]}});
                feed({content: {role: "model", parts: [{functionCall: {name: "discover_capabilities", id: "discovery"}}]}});
                feed({content: {role: "user", parts: [{functionResponse: {name: "discover_capabilities", id: "discovery", response: {status: "available", capabilities: [{name: "splunk.index.errors.read", available: true, description: "Read application error counts."}]}}}]}});
                feed({content: {role: "model", parts: [{functionCall: {name: "execute_capability", id: "check", args: {capability_name: "splunk.index.errors.read", semantic_arguments: {private: "private"}}}}]}});
                await this.settle();
                assert.deepEqual(fixture.element("invocation-skill-view").data, ["Inspect application logs"]);
                assert.equal(fixture.element("invocation-stage").children, "Splunk · Read application error counts.");
                feed({content: {role: "user", parts: [{functionResponse: {name: "execute_capability", id: "check", response: {status: "success"}}}]}});
                feed({partial: true, content: {role: "model", parts: [{text: "An answer"}]}});
                await this.settle();
                assert.equal(fixture.element("invocation-stage").children, "Writing response");
                feed({content: {role: "model", parts: [{text: "An answer"}]}});
                source.close();
                await this.settle();
                assert.equal(fixture.element("invocation-activity").style.display, "none");
                assert.equal(fixture.element("invocation-skill-view").data, null);
                assert.equal(fixture.timers.size, 0);
            } finally {fixture.restore();}
        });
        test("reopening a running job replays after a dropped frame without duplicating text", async () => {
            const messages = [{role: "user", text: "Resume this answer"}];
            const subscriptions = [];
            const fixture = this.setup({
                messages,
                latestJob: {job_id: "synthetic-job", status: "running"},
                jobStatus: "running",
                conversations: [{conversation_id: "synthetic-chat", title: "Saved chat"}],
                manualStream: (_signal, after) => new ReadableStream({
                    start(controller) {subscriptions.push({controller, after});},
                }),
            });
            const frame = (id, text, partial = true) => new TextEncoder().encode(
                "id: " + id + "\ndata: " + JSON.stringify({partial, content: {role: "model", parts: [{text}]}}) + "\n\n"
            );
            const answer = () => fixture.element("message-transcript").children.at(-1).props.children[1].props.children;
            try {
                await this.settle();
                fixture.click("conversation-synthetic-chat");
                await this.settle();
                assert.equal(subscriptions[0].after, 0);
                subscriptions[0].controller.enqueue(frame(1, "First "));
                subscriptions[0].controller.enqueue(new TextEncoder().encode("id: 2\ndata: {"));
                await this.settle();
                assert.equal(answer(), "First ");
                subscriptions[0].controller.error(new Error("Synthetic connection dropped"));
                await this.settle();
                assert.equal(subscriptions[1].after, 1);
                subscriptions[1].controller.enqueue(frame(1, "First "));
                subscriptions[1].controller.enqueue(frame(2, "second"));
                await this.settle();
                assert.equal(answer(), "First second");
                fixture.state.jobStatus = "succeeded";
                messages.push({role: "assistant", text: "First second"});
                subscriptions[1].controller.enqueue(frame(3, "First second", false));
                subscriptions[1].controller.close();
                await this.settle();
                assert.equal(answer(), "First second");
                assert.equal(fixture.element("message-transcript").children.length, 2);
                assert.equal(fixture.requests.some(request => request.options.method === "POST"), false);
            } finally {fixture.restore();}
        });
        test("a failed acknowledgement leaves the draft and reuses its submission key", async () => {
            const fixture = this.setup({failSubmission: true});
            try {
                await this.settle();
                fixture.element("message-input").value = "Keep this draft";
                fixture.click("send-message");
                await this.settle();
                assert.equal(fixture.element("message-input").value, "Keep this draft");
                fixture.state.failSubmission = false;
                fixture.click("send-message");
                await this.settle();
                const submissions = fixture.requests.filter(request => request.url.endsWith("/synthetic-chat/jobs"));
                assert.equal(submissions.length, 2);
                assert.match(submissions[0].options.headers["Idempotency-Key"], /^[0-9a-f-]{36}$/);
                assert.equal(submissions[1].options.headers["Idempotency-Key"], submissions[0].options.headers["Idempotency-Key"]);
                assert.equal(fixture.creations().length, 1);
            } finally {fixture.restore();}
        });
        test("cancellation, sign-out and late callbacks cannot leave progress or timers behind", async () => {
            for (const action of ["stop-stream", "sign-out"]) {
                const fixture = this.setup();
                try {
                    await this.settle();
                    fixture.state.manualStream = signal => new ReadableStream({start(controller) {
                        signal.addEventListener("abort", () => controller.error(new DOMException("Aborted", "AbortError")), {once: true});
                    }});
                    fixture.element("message-input").value = "Synthetic long request";
                    fixture.click("send-message");
                    await this.settle();
                    const staleTick = [...fixture.timers.values()][0];
                    fixture.click(action);
                    await this.settle();
                    const stopRequests = fixture.requests.filter(request => request.url.endsWith("/synthetic-job/stop"));
                    assert.equal(stopRequests.length, action === "stop-stream" ? 1 : 0);
                    if (action === "stop-stream") {
                        assert.equal(stopRequests[0].options.method, "POST");
                        assert.equal(fixture.element("send-message").disabled, false);
                    }
                    assert.equal(fixture.timers.size, 0);
                    assert.equal(fixture.element("invocation-activity").style.display, "none");
                    staleTick();
                    assert.equal(fixture.element("invocation-elapsed").children, "");
                } finally {fixture.restore();}
            }
        });
    }
}
TestWorkspaceController.run();
