import assert from "node:assert/strict";
import test from "node:test";
import {ApiClient} from "../src/mosaic_gui/assets/api_client.mjs";

class TestApiClient {
    static run() {
        test("JSON requests use cookies, no-store and forbid redirects without bearer propagation", async () => {
            const original = globalThis.fetch;
            let captured;
            globalThis.fetch = async (url, options) => {captured = {url, options}; return new Response(null, {status: 204});};
            try {
                assert.equal(await new ApiClient("https://api.example.com").request("/api/v1/auth/token", {method: "POST", body: {token: "synthetic-token"}}), null);
                assert.equal(captured.url, "https://api.example.com/api/v1/auth/token");
                assert.equal(captured.options.credentials, "include");
                assert.equal(captured.options.redirect, "error");
                assert.equal(captured.options.cache, "no-store");
                assert.equal(captured.options.headers.Authorization, undefined);
                assert.equal(JSON.parse(captured.options.body).token, "synthetic-token");
            } finally {globalThis.fetch = original;}
        });
        test("stream submits text only and retains its explicit cancellation signal", async () => {
            const original = globalThis.fetch;
            let captured;
            const controller = new AbortController();
            globalThis.fetch = async (url, options) => {captured = {url, options}; return new Response("data: {}\n\n", {headers: {"Content-Type": "text/event-stream"}});};
            try {
                await new ApiClient("https://api.example.com").stream("synthetic-id", "Synthetic text", controller.signal);
                assert.deepEqual(JSON.parse(captured.options.body), {text: "Synthetic text"});
                assert.equal(captured.options.signal, controller.signal);
                assert.equal(captured.options.credentials, "include");
                assert.equal(captured.options.headers.Authorization, undefined);
            } finally {globalThis.fetch = original;}
        });
        test("authentication failures contain guidance, not private response detail", async () => {
            const original = globalThis.fetch;
            globalThis.fetch = async () => new Response(JSON.stringify({detail: "private synthetic diagnostic", error_code: "unauthorized"}), {status: 401, headers: {"X-Correlation-ID": "synthetic-correlation"}});
            try {
                await assert.rejects(new ApiClient("https://api.example.com").request("/api/v1/workspace"), error => error.status === 401 && !error.message.includes("private") && error.correlationId === "synthetic-correlation");
            } finally {globalThis.fetch = original;}
        });
        test("an unusable stream keeps its response correlation reference", async () => {
            const original = globalThis.fetch;
            const reference = "12345678-1234-1234-1234-123456789abc";
            globalThis.fetch = async () => Response.json({detail: "private synthetic diagnostic"}, {headers: {"X-Correlation-ID": reference}});
            try {
                await assert.rejects(new ApiClient("https://api.example.com").stream("synthetic-id", "Synthetic text", new AbortController().signal), error => error.correlationId === reference && !error.message.includes("private"));
            } finally {globalThis.fetch = original;}
        });
    }
}
TestApiClient.run();
