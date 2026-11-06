export class InvocationActivity {
    #skills;
    #selected = [];
    #declared = new Set();
    #capabilities = new Map();
    #active = new Map();
    #seen = new Set();
    #sequence = 0;
    #reliableCounts = true;
    #onChange;
    constructor(skills, onChange) {
        /**
         * Project native tool activity into bounded, temporary display metadata.
         * :param skills: Authorised workspace metadata used for Skill titles.
         * :param onChange: Callback receiving safe labels, never raw tool payloads.
         */
        this.#skills = new Map(skills.map(skill => [skill.skill_id, skill.display_name]));
        this.#onChange = onChange;
    }
    accept(event) {
        /**
         * Observe complete native tool events without retaining arguments or evidence.
         * :param event: Native ADK event from the current response stream.
         */
        if (event.branch || event.partial === true || !Array.isArray(event.content?.parts)) return;
        for (const part of event.content.parts) {
            if (!part || part.thought) continue;
            const call = part.functionCall || part.function_call;
            const result = part.functionResponse || part.function_response;
            if (call && event.content.role === "model") this.#call(call);
            if (result) this.#result(result);
        }
    }
    writing() {
        /**
         * Report answer text arriving without claiming pending checks succeeded.
         */
        this.#publish("Writing response");
    }
    #call(call) {
        /**
         * Track supported calls by ID, reading only an authorised capability name.
         * :param call: Native function-call part; other arguments are ignored.
         */
        const labels = {discover_skills: "Finding relevant skills", load_skills: "Loading selected skills", discover_capabilities: "Identifying available checks", execute_capability: "Running a check", request_goal_clarification: "Preparing a clarification"};
        if (!Object.hasOwn(labels, call.name) || this.#active.size >= 64) return;
        const id = typeof call.id === "string" && call.id.length <= 200 ? call.id : null;
        if (id && this.#seen.has(id)) return;
        if (this.#seen.size >= 512) return;
        if (id) this.#seen.add(id);
        else this.#reliableCounts = false;
        const capability = call.name === "execute_capability" ? this.#capabilities.get(call.args?.capability_name) : null;
        const activity = {name: call.name, label: capability?.description || labels[call.name], platform: capability?.platform || null};
        this.#active.set(id || `unidentified-${++this.#sequence}`, activity);
        this.#publishActive();
    }
    #result(result) {
        /**
         * Confirm selection and discovery only from a matching tool response.
         * :param result: Native function response; evidence and instructions stay unused.
         */
        let key = typeof result.id === "string" ? result.id : null;
        if (!key) {
            const matches = [...this.#active].filter(([, entry]) => entry.name === result.name);
            if (matches.length !== 1) return;
            key = matches[0][0];
        }
        const active = this.#active.get(key);
        if (!active || active.name !== result.name) return;
        this.#active.delete(key);
        const response = result.response;
        if (result.name === "load_skills" && response?.status === "loaded" && Array.isArray(response.loaded_skills)) {
            this.#selected = [];
            this.#declared.clear();
            this.#capabilities.clear();
            for (const skill of response.loaded_skills.slice(0, 32)) {
                if (!this.#skills.has(skill?.name)) continue;
                const label = this.#label(this.#skills.get(skill.name));
                if (label && !this.#selected.includes(label)) this.#selected.push(label);
                for (const name of [...(Array.isArray(skill.required_capability_names) ? skill.required_capability_names : []), ...(Array.isArray(skill.optional_capability_names) ? skill.optional_capability_names : [])].slice(0, 256)) {
                    if (typeof name === "string" && name.length <= 160 && this.#declared.size < 256) this.#declared.add(name);
                }
            }
        }
        if (result.name === "discover_capabilities" && response?.status === "available" && Array.isArray(response.capabilities)) {
            for (const capability of response.capabilities.slice(0, 256)) {
                if (!capability?.available || !this.#declared.has(capability.name)) continue;
                const description = this.#label(capability.description);
                if (!description) continue;
                const families = {kubernetes: "Kubernetes / OpenShift", openshift: "OpenShift", splunk: "Splunk", mq: "MQ", observability: "Observability"};
                const family = capability.name.split(".")[0];
                this.#capabilities.set(capability.name, {description, platform: Object.hasOwn(families, family) ? families[family] : "Platform"});
            }
        }
        if (this.#active.size) this.#publishActive();
        else this.#publish(response?.status === "awaiting_clarification" || (typeof response?.status === "string" && response.status.startsWith("target_")) ? "Waiting for the model to clarify the request" : "Waiting for the next model response");
    }
    #label(value) {
        /**
         * Accept compact catalogue labels while excluding addresses and control text.
         * :param value: Approved metadata label, never a tool argument or evidence.
         * :return: Plain text label or null when unsuitable for public display.
         */
        if (typeof value !== "string" || !value.trim() || value.length > 240 || /[\x00-\x1f\x7f<>/@\\]|https?:|\b(?:[\w-]+\.)+[\w-]+\b/i.test(value)) return null;
        return value.trim();
    }
    #publishActive() {
        /**
         * Describe observed active work, counting only calls with reliable IDs.
         */
        const entries = [...this.#active.values()];
        if (entries.length === 1) this.#publish(entries[0].label, entries[0].platform);
        else this.#publish(this.#reliableCounts ? `Running tools · ${entries.length} active` : "Running tools", [...new Set(entries.map(entry => entry.platform).filter(Boolean))].join(" + ") || null);
    }
    #publish(operation, platform = null) {
        /**
         * Emit a copied public view without retaining or exposing provider payloads.
         * :param operation: Display text derived from observed activity.
         * :param platform: Optional semantic platform family, never an endpoint address.
         */
        this.#onChange({skills: [...this.#selected], operation, platform});
    }
}
