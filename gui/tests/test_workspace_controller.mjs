import assert from "node:assert/strict";
import test from "node:test";
import {WorkspaceController} from "../src/mosaic_gui/assets/workspace_controller.mjs";

class TestWorkspaceController {
    static setup() {
        const originals = Object.fromEntries(["document", "window", "fetch", "requestAnimationFrame"].map(key => [key, globalThis[key]]));
        const elements = new Map();
        const listeners = new Map();
        const requests = [];
        const element = id => {
            if (!elements.has(id)) elements.set(id, {id, value: "", disabled: false, dataset: {}, scrollHeight: 0, scrollTop: 0, clientHeight: 100,
                setAttribute() {}, append() {}, addEventListener() {}, querySelectorAll: () => []});
            return elements.get(id);
        };
        globalThis.document = {createElement: () => element("pilot-token"), getElementById: element,
            addEventListener: (name, callback) => listeners.set(name, callback)};
        globalThis.window = {addEventListener() {}, dash_clientside: {set_props: (id, props) => Object.assign(element(id), props)}};
        globalThis.requestAnimationFrame = callback => callback();
        const detail = {conversation_id: "synthetic-chat", title: null, can_continue: true, is_interrupted: false, messages: []};
        const state = {failCreation: false};
        globalThis.fetch = async (url, options) => {
            requests.push({url, options});
            const path = new URL(url).pathname;
            if (path === "/api/v1/workspace") return Response.json({user_id: "synthetic-user", skills: []});
            if (path === "/api/v1/conversations" && options.method === "POST") {
                if (state.failCreation) return Response.json({}, {status: 503});
                return Response.json(detail, {status: 201});
            }
            if (path === "/api/v1/conversations") return Response.json({conversations: []});
            if (path.endsWith("/stream")) return new Response('data: {"content":{"role":"model","parts":[{"text":"Synthetic answer"}]},"partial":false}\n\n');
            if (path === "/api/v1/conversations/synthetic-chat") return Response.json(detail);
            throw new Error("Unexpected synthetic request: " + path);
        };
        new WorkspaceController({dataset: {backendUrl: "https://api.example.com"}});
        return {element, requests, state,
            click: id => listeners.get("click")({target: {closest: () => element(id)}}),
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
                assert.equal(fixture.requests.some(request => request.url.endsWith("/stream")), false);
                fixture.state.failCreation = false;
                fixture.click("send-message");
                await this.settle();
                assert.equal(fixture.creations().length, 2);
            } finally {fixture.restore();}
        });
    }
}
TestWorkspaceController.run();
