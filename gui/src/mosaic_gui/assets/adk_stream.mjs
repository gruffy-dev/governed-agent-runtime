export class AdkStream {
    #buffer = "";
    #completed = [];
    #partial = "";
    #finalIds = new Set();
    #sawFinal = false;
    #onText;
    constructor(onText) {
        /**
         * Bind native ADK text projection to one incremental display callback.
         * :param onText: Callback receiving only the current displayable answer.
         */
        this.#onText = onText;
    }
    feed(chunk) {
        /**
         * Decode fragmented SSE records, accepting LF or CRLF boundaries.
         * :param chunk: UTF-8-decoded fragment from the native ADK stream.
         */
        this.#buffer += chunk;
        let boundary;
        while ((boundary = /\r?\n\r?\n/.exec(this.#buffer))) {
            const frame = this.#buffer.slice(0, boundary.index);
            this.#buffer = this.#buffer.slice(boundary.index + boundary[0].length);
            if (frame.length > 2 * 1024 * 1024) throw new Error("The response exceeded its display limit.");
            this.#frame(frame);
        }
        if (this.#buffer.length > 2 * 1024 * 1024) throw new Error("The response exceeded its display limit.");
    }
    finish() {
        /**
         * Require a complete final text turn instead of treating HTTP EOF as success.
         * :raises Error: If SSE ended in an incomplete record or model turn.
         */
        if (this.#buffer.trim() || this.#partial || !this.#sawFinal) {
            throw new Error("The response ended before completion. Check the conversation status.");
        }
    }
    #frame(frame) {
        /**
         * Select model text only; replace each partial turn with its final aggregate.
         * :param frame: Complete SSE record, including optional comments.
         */
        const data = frame.split(/\r?\n/).filter(line => line.startsWith("data:")).map(line => line.slice(5).replace(/^ /, "")).join("\n");
        if (!data) return;
        let event;
        try { event = JSON.parse(data); } catch { throw new Error("The backend returned an invalid stream record."); }
        if (!event || typeof event !== "object" || Array.isArray(event)) throw new Error("The backend returned an invalid stream record.");
        if (event.error || event.errorCode || event.error_code) throw new Error("The model could not complete this response. Start a new conversation if it is marked interrupted.");
        if (event.branch || event.content?.role !== "model" || !Array.isArray(event.content.parts)) return;
        if (event.content.parts.some(part => part?.functionCall || part?.function_call || part?.functionResponse || part?.function_response)) return;
        const text = event.content.parts.filter(part => !part?.thought && typeof part?.text === "string").map(part => part.text).join("");
        if (!text) return;
        if (event.partial === true) this.#partial += text;
        else {
            if (event.id && this.#finalIds.has(event.id)) return;
            if (event.id) this.#finalIds.add(event.id);
            this.#completed.push(text);
            this.#partial = "";
            this.#sawFinal = true;
        }
        const display = [...this.#completed, ...(this.#partial ? [this.#partial] : [])].join("\n\n");
        if (display.length > 2 * 1024 * 1024) throw new Error("The response exceeded its display limit.");
        this.#onText(display);
    }
}
