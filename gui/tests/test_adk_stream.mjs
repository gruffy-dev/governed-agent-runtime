import assert from "node:assert/strict";
import test from "node:test";
import {AdkStream} from "../src/mosaic_gui/assets/adk_stream.mjs";

class TestAdkStream {
    static frame(text, partial, extra = {}) {
        return "data: " + JSON.stringify({content: {role: "model", parts: [{text}]}, partial, ...extra}) + "\n\n";
    }
    static run() {
        test("incremental deltas are replaced by the final aggregate, not duplicated", () => {
            const values = [];
            const stream = new AdkStream(value => values.push(value));
            const wire = this.frame("Hello ", true) + this.frame("world", true) + this.frame("Hello world", false, {id: "synthetic-final"});
            for (const character of wire) stream.feed(character);
            stream.finish();
            assert.equal(values.at(-1), "Hello world");
            assert.deepEqual(values, ["Hello ", "Hello world", "Hello world"]);
        });
        test("CRLF, comments, Unicode and multiple assistant turns are handled", () => {
            const values = [];
            const stream = new AdkStream(value => values.push(value));
            stream.feed(": keepalive\r\n\r\n" + this.frame("First ✓", false).replaceAll("\n", "\r\n"));
            stream.feed(this.frame("Second", true) + this.frame("Second", false));
            stream.finish();
            assert.equal(values.at(-1), "First ✓\n\nSecond");
        });
        test("thoughts, tools, state, branches and user events are not displayed", () => {
            const values = [];
            const stream = new AdkStream(value => values.push(value));
            for (const event of [{content: {role: "user", parts: [{text: "private"}]}}, {content: {role: "model", parts: [{text: "private", thought: true}]}}, {content: {role: "model", parts: [{functionCall: {name: "private"}}, {text: "private"}]}}, {branch: "private", content: {role: "model", parts: [{text: "private"}]}}, {actions: {stateDelta: {private: "private"}}}]) stream.feed("data: " + JSON.stringify(event) + "\n\n");
            stream.feed(this.frame("Public answer", false));
            stream.finish();
            assert.deepEqual(values, ["Public answer"]);
        });
        test("model and server errors do not become successful EOF or leak details", () => {
            for (const event of [{error: "private diagnostic"}, {errorCode: "private_code", errorMessage: "private diagnostic"}]) {
                const stream = new AdkStream(() => {});
                assert.throws(() => stream.feed("data: " + JSON.stringify(event) + "\n\n"), error => !error.message.includes("private"));
            }
            const stream = new AdkStream(() => {});
            stream.feed(this.frame("Incomplete", true));
            assert.throws(() => stream.finish());
            assert.throws(() => new AdkStream(() => {}).finish());
        });
        test("duplicate final IDs and oversized or malformed records are rejected safely", () => {
            const values = [];
            const stream = new AdkStream(value => values.push(value));
            stream.feed(this.frame("Done", false, {id: "same"}) + this.frame("Done", false, {id: "same"}));
            assert.deepEqual(values, ["Done"]);
            assert.throws(() => new AdkStream(() => {}).feed("x".repeat(2 * 1024 * 1024 + 1)));
            assert.throws(() => new AdkStream(() => {}).feed("data: invalid\n\n"));
        });
    }
}
TestAdkStream.run();
