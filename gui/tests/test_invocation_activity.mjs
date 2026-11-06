import assert from "node:assert/strict";
import test from "node:test";
import {InvocationActivity} from "../src/mosaic_gui/assets/invocation_activity.mjs";
import {AdkStream} from "../src/mosaic_gui/assets/adk_stream.mjs";

class TestInvocationActivity {
    static call(name, id, args = {}, extra = {}) {
        return {content: {role: "model", parts: [{functionCall: {name, id, args}}]}, ...extra};
    }
    static result(name, id, response) {
        return {content: {role: "user", parts: [{functionResponse: {name, id, response}}]}};
    }
    static selection(activity) {
        activity.accept(this.call("load_skills", "load"));
        activity.accept(this.result("load_skills", "load", {status: "loaded", loaded_skills: [{name: "investigate-logs", required_capability_names: ["splunk.pod.logs.read"], optional_capability_names: ["kubernetes.pods.status.read"]}]}));
        activity.accept(this.call("discover_capabilities", "discovery"));
        activity.accept(this.result("discover_capabilities", "discovery", {status: "available", capabilities: [{name: "splunk.pod.logs.read", available: true, description: "Read recent application logs."}, {name: "kubernetes.pods.status.read", available: true, description: "Read workload readiness."}]}));
    }
    static run() {
        test("confirmed selection and discovered metadata describe real platform work only", () => {
            const views = [];
            const activity = new InvocationActivity([{skill_id: "investigate-logs", display_name: "Investigate application logs"}], view => views.push(view));
            activity.accept(this.call("load_skills", "partial", {skill_names: ["private"]}, {partial: true}));
            assert.equal(views.length, 0);
            this.selection(activity);
            activity.accept(this.call("execute_capability", "logs", {capability_name: "splunk.pod.logs.read", semantic_arguments: {token: "private", index: "private"}}));
            assert.deepEqual(views.at(-1), {skills: ["Investigate application logs"], platform: "Splunk", operation: "Read recent application logs."});
            activity.accept(this.result("execute_capability", "logs", {status: "success", evidence: {private: "private"}}));
            assert.equal(views.at(-1).operation, "Waiting for the next model response");
            activity.writing();
            assert.equal(views.at(-1).operation, "Writing response");
            assert.equal(JSON.stringify(views).includes("private"), false);
        });
        test("parallel calls use IDs for matching, counting and duplicate suppression", () => {
            const views = [];
            const activity = new InvocationActivity([{skill_id: "investigate-logs", display_name: "Log investigation"}], view => views.push(view));
            this.selection(activity);
            activity.accept(this.call("execute_capability", "logs", {capability_name: "splunk.pod.logs.read"}));
            activity.accept(this.call("execute_capability", "pods", {capability_name: "kubernetes.pods.status.read"}));
            activity.accept(this.call("execute_capability", "pods", {capability_name: "kubernetes.pods.status.read"}));
            assert.equal(views.at(-1).operation, "Running tools · 2 active");
            assert.equal(views.at(-1).platform, "Splunk + Kubernetes / OpenShift");
            activity.accept(this.result("execute_capability", "pods", {status: "failed", error_message: "private diagnostic"}));
            assert.equal(views.at(-1).platform, "Splunk");
            activity.accept(this.result("execute_capability", "pods", {status: "success"}));
            assert.equal(views.at(-1).platform, "Splunk");
            assert.equal(JSON.stringify(views).includes("private"), false);
        });
        test("missing IDs omit counts, ambiguous completions do not invent finished work", () => {
            const views = [];
            const activity = new InvocationActivity([], view => views.push(view));
            activity.accept(this.call("execute_capability"));
            activity.accept(this.call("execute_capability"));
            assert.equal(views.at(-1).operation, "Running tools");
            const count = views.length;
            activity.accept(this.result("execute_capability", undefined, {status: "success"}));
            assert.equal(views.length, count);
        });
        test("failed, unmatched, hidden and address-bearing metadata do not become public labels", () => {
            const views = [];
            const activity = new InvocationActivity([{skill_id: "investigate-logs", display_name: "Log investigation"}], view => views.push(view));
            activity.accept(this.result("load_skills", "unmatched", {status: "loaded", loaded_skills: [{name: "private"}]}));
            activity.accept(this.call("load_skills", "failed"));
            activity.accept(this.result("load_skills", "failed", {status: "not_found", loaded_skills: [{name: "investigate-logs"}]}));
            assert.deepEqual(views.at(-1).skills, []);
            activity.accept(this.call("private", "unknown"));
            activity.accept(this.call("load_skills", "hidden", {}, {branch: "private"}));
            this.selection(activity);
            activity.accept(this.call("discover_capabilities", "unsafe"));
            activity.accept(this.result("discover_capabilities", "unsafe", {status: "available", capabilities: [{name: "private.hidden.read", available: true, description: "private"}, {name: "splunk.pod.logs.read", available: true, description: "Connect to https://private.example.test"}]}));
            activity.accept(this.call("execute_capability", "unknown-capability", {capability_name: "private.hidden.read"}));
            assert.equal(views.at(-1).operation, "Running a check");
            assert.equal(JSON.stringify(views).includes("private"), false);
        });
        test("fragmented native SSE supplies tool progress without polluting answer text", () => {
            const views = [], answers = [];
            const activity = new InvocationActivity([], view => views.push(view));
            const stream = new AdkStream(text => {answers.push(text); activity.writing();}, event => activity.accept(event));
            const events = [this.call("discover_skills", "discovery"), this.result("discover_skills", "discovery", {status: "available", private: "private"}), {partial: true, content: {role: "model", parts: [{thought: true, text: "private"}, {text: "Hello", thoughtSignature: "private"}]}}, {content: {role: "model", parts: [{text: "Hello"}]}}];
            for (const event of events) for (const character of "data: " + JSON.stringify(event) + "\n\n") stream.feed(character);
            stream.finish();
            assert.equal(answers.at(-1), "Hello");
            assert.equal(views[0].operation, "Finding relevant skills");
            assert.equal(views.at(-1).operation, "Writing response");
            assert.equal(JSON.stringify(views).includes("private"), false);
        });
    }
}
TestInvocationActivity.run();
