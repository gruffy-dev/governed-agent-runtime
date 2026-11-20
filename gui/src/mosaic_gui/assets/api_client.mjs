export class ApiClient {
    #origin;
    constructor(origin) {
        /**
         * Bind browser requests to one operator-configured backend origin.
         * :param origin: Public MOSAIC API origin, never a credential-bearing URL.
         */
        this.#origin = origin;
    }
    async request(path, {method = "GET", body, signal, submissionKey} = {}) {
        /**
         * Make a bounded JSON request using the protected browser cookie.
         * :param path: Owned public API path.
         * :param method: HTTP operation.
         * :param body: Optional JSON request body held only for this request.
         * :param signal: Optional cancellation signal for superseded user operations.
         * :param submissionKey: Optional key for replay-safe job submission.
         * :return: Decoded JSON or null for an empty success.
         */
        const timeout = AbortSignal.timeout(15000);
        let response;
        try { response = await fetch(this.#origin + path, {
            method, credentials: "include", cache: "no-store", redirect: "error",
            headers: {
                ...(body === undefined ? {} : {"Content-Type": "application/json"}),
                ...(submissionKey ? {"Idempotency-Key": submissionKey} : {}),
            },
            body: body === undefined ? undefined : JSON.stringify(body),
            signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
        }); } catch (error) {
            if (signal?.aborted) throw error;
            throw new Error("Unable to reach the backend. Check its address and browser access configuration.");
        }
        if (!response.ok) throw await this.#failure(response);
        if (response.status === 204) return null;
        try { return await response.json(); }
        catch { throw new Error("The backend returned an invalid response."); }
    }
    async stream(jobId, after, signal) {
        /**
         * Attach to an owned job's replay and live events.
         * :param jobId: Server-generated job identifier.
         * :param after: Last complete SSE frame already consumed.
         * :param signal: Cancellation signal for this subscriber.
         * :return: Fetch response whose stream must be consumed or cancelled.
         */
        let response;
        try { response = await fetch(this.#origin + "/api/v1/conversations/jobs/" + encodeURIComponent(jobId) + "/events?after=" + after, {
            method: "GET", credentials: "include", cache: "no-store", redirect: "error", signal,
        }); } catch (error) {
            if (signal.aborted) throw error;
            throw new Error("Unable to reach the backend. Check its address and browser access configuration.");
        }
        if (!response.ok) throw await this.#failure(response);
        if (!response.headers.get("content-type")?.startsWith("text/event-stream") || !response.body) {
            throw Object.assign(new Error("The backend did not return a usable response stream."), {correlationId: response.headers.get("x-correlation-id")});
        }
        return response;
    }
    async #failure(response) {
        /**
         * Map failures to safe user guidance without displaying private response data.
         * :param response: Rejected public API response.
         * :return: Error carrying safe status and correlation metadata.
         */
        let body = {};
        try { body = await response.json(); } catch { /* Non-JSON failures use generic guidance. */ }
        const message = response.status === 401 ? "Your access has expired. Please sign in again."
            : response.status === 403 ? "This browser is not authorised. Check the configured GUI origin."
            : response.status === 404 ? "This conversation is unavailable. Start a new conversation."
            : response.status === 409 ? "This conversation cannot continue. Start a new conversation; saved history remains available."
            : "The request could not be completed. Check the backend and try again.";
        return Object.assign(new Error(message), {
            status: response.status,
            code: typeof body.error_code === "string" ? body.error_code : "request_failed",
            correlationId: response.headers.get("x-correlation-id"),
        });
    }
}
