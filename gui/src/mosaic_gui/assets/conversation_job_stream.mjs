import {AdkStream} from "./adk_stream.mjs";

export class ConversationJobStream {
    static isActive(job) {
        return ["queued", "running", "stopping"].includes(job?.status);
    }

    static path(jobId) {
        return "/api/v1/conversations/jobs/" + encodeURIComponent(jobId);
    }

    static async follow(client, jobId, signal, onText, onEvent) {
        /**
         * Follow a job, reconnecting once from the last complete frame after a dropped stream.
         * :param client: Authenticated browser API client.
         * :param jobId: Owned job to follow.
         * :param signal: Lifetime of this browser subscription.
         * :param onText: Current answer projection.
         * :param onEvent: Public event observer for activity and history reconciliation.
         * :return: Persisted job outcome and an optional stream error for display.
         */
        const projection = new AdkStream(onText, onEvent);
        for (let attempt = 0; attempt < 2; attempt++) {
            let failure = null;
            try {
                const response = await client.stream(jobId, projection.lastSequence, signal);
                await this.#read(response, projection);
            } catch (error) {
                if (signal.aborted || error.status === 401) throw error;
                failure = error;
            }
            const job = await client.request(this.path(jobId), {signal});
            if (!this.isActive(job) || attempt === 1) return {job, failure};
            projection.resetConnection();
        }
    }

    static async #read(response, projection) {
        /**
         * Decode a single subscription and release its reader on completion or failure.
         * :param response: Fetch response carrying public SSE.
         * :param projection: Accumulated answer and replay cursor.
         */
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        try {
            while (true) {
                const {value, done} = await reader.read();
                if (done) break;
                projection.feed(decoder.decode(value, {stream: true}));
            }
            projection.feed(decoder.decode());
        } catch (error) {
            error.correlationId ||= response.headers.get("x-correlation-id");
            throw error;
        } finally {
            try {await reader.cancel();} catch { /* The connection may already be closed. */ }
            finally {reader.releaseLock();}
        }
    }
}
