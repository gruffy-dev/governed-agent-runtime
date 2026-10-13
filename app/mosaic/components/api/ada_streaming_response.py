import json
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Any, Self

import anyio
from starlette.responses import StreamingResponse
from starlette.types import Message, Receive, Scope, Send

from ..ada.ada_application_error import AdaApplicationError


class AdaStreamingResponse(StreamingResponse):
    def __init__(
        self,
        stream: AsyncGenerator[Message, None],
        maximum_event_bytes: int,
        public_agent_name: str,
        on_close: Callable[[bool], Awaitable[None]] | None = None,
    ) -> None:
        """
        Relay ADK text events without reconciling partial and final answers.

        :param stream: Private stream whose successful headers were checked.
        :param maximum_event_bytes: Existing transport bound applied per SSE frame.
        :param public_agent_name: Agent allowed to supply browser-visible text.
        :param on_close: Optional availability finaliser called once after private cleanup.
        """
        self._stream = stream
        self._maximum_event_bytes = maximum_event_bytes
        self._public_agent_name = public_agent_name
        self._on_close = on_close
        self._normal_eof = False
        self._failed = False
        self._body_stream = self._body()
        super().__init__(
            self._body_stream,
            media_type='text/event-stream',
            headers={
                'Cache-Control': 'no-store',
                'X-Accel-Buffering': 'no',
            },
        )

    @classmethod
    async def create(
        cls,
        stream: AsyncGenerator[Message, None],
        maximum_event_bytes: int,
        public_agent_name: str,
        on_close: Callable[[bool], Awaitable[None]] | None = None,
    ) -> Self:
        """
        Check private HTTP success and content type before committing public headers.

        :param stream: Owned private invocation iterator, closed on preparation failure.
        :param maximum_event_bytes: Maximum retained SSE frame size.
        :param public_agent_name: Configured public assistant author.
        :param on_close: Availability finaliser for this response's owned reservation.

        :return: Browser-owned streaming response with ADK data framing.

        :raises AdaApplicationError: If private headers are absent or not SSE.
        """
        try:
            start = await anext(stream)
            headers = dict(start.get('headers', []))
            if (
                start['type'] != 'http.response.start'
                or not 200 <= start.get('status', 0) < 300
                or headers.get(b'content-type', b'').lower().split(b';', 1)[0].strip()
                != b'text/event-stream'
            ):
                raise AdaApplicationError(
                    'Private execution did not start an SSE response.'
                )
            return cls(stream, maximum_event_bytes, public_agent_name, on_close)
        except BaseException:
            with anyio.CancelScope(shield=True):
                await stream.aclose()
            raise

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Close private execution after completion, disconnect or failed browser writes.

        :param scope: Browser request ASGI scope.
        :param receive: Browser request and disconnect receiver.
        :param send: Browser response writer.
        """
        try:
            await super().__call__(scope, receive, send)
        finally:
            with anyio.CancelScope(shield=True):
                await self._body_stream.aclose()
                await self._close()

    async def _close(self) -> None:
        """
        Finalise availability once after private cleanup and before clean public EOF.

        The outer response also calls this if sending headers or body fails.
        Shield cleanup from the browser's cancellation scope; do not continue
        model execution or reclaim another request's reservation.
        """
        with anyio.CancelScope(shield=True):
            await self._stream.aclose()
            on_close = self._on_close
            self._on_close = None
            if on_close is not None:
                await on_close(self._normal_eof and not self._failed)

    async def _body(self) -> AsyncGenerator[bytes, None]:
        """
        Forward allowlisted ADK records and replace private failures with a safe error.

        EOF is not a success sentinel. The GUI interprets ADK partial, final and
        error records. No background work, text reconciliation or replay is added.

        :return: ADK-shaped SSE frames, with no custom lifecycle event names.
        """
        try:
            async for record in self._records():
                frame = self._public_frame(record)
                if frame is not None:
                    yield frame
            self._normal_eof = True
        except Exception:  # noqa: BLE001 - private diagnostics must not reach browsers.
            yield b'data: {"error":"Invocation failed"}\n\n'
        finally:
            await self._close()

    async def _records(self) -> AsyncIterator[dict[str, Any]]:
        """
        Read bounded JSON data records across fragmented UTF-8 and SSE line endings.

        :return: Complete ADK record objects; comments and framing metadata are ignored.

        :raises ValueError: If a frame is malformed, oversized or truncated.
        """
        line = bytearray()
        data: list[str] = []
        frame_bytes = 0
        skip_lf = False
        async for message in self._stream:
            if message['type'] != 'http.response.body':
                raise ValueError('Unexpected private response message.')
            for value in message.get('body', b''):
                if skip_lf:
                    skip_lf = False
                    if value == 10:
                        continue
                frame_bytes += 1
                if frame_bytes > self._maximum_event_bytes:
                    raise ValueError('Private SSE frame exceeded its bound.')
                if value not in (10, 13):
                    line.append(value)
                    continue
                skip_lf = value == 13
                decoded = line.decode('utf-8')
                line.clear()
                if decoded:
                    field, _, text = decoded.partition(':')
                    if field == 'data':
                        data.append(text.removeprefix(' '))
                else:
                    frame_bytes = 0
                    if data:
                        record = json.loads('\n'.join(data))
                        data.clear()
                        if not isinstance(record, dict):
                            raise ValueError('Private SSE data must be an object.')
                        yield record
        if line or data:
            raise ValueError('Private SSE frame was truncated.')

    def _public_frame(self, record: dict[str, Any]) -> bytes | None:
        """
        Retain ADK answer shape while excluding thoughts, tools, state and diagnostics.

        Preserve partial and final text unchanged, including final repeated text.
        Metadata kept here describes the answer; the GUI must not render it as text.

        :param record: Private ADK JSON event or generator-error record.

        :return: Safe ADK data frame, or None for non-public content.

        :raises ValueError: If ADK reports an error or public text has an invalid shape.
        :raises TypeError: If an answer text part is not a string.
        """
        if any(
            record.get(key)
            for key in ('error', 'error_details', 'errorCode', 'errorMessage')
        ):
            raise ValueError('Private execution failed.')
        if record.get('interrupted') or record.get('finishReason') not in (None, 'STOP'):
            self._failed = True
        content = record.get('content')
        if (
            record.get('author') != self._public_agent_name
            or record.get('branch')
            or not isinstance(content, dict)
            or content.get('role') != 'model'
        ):
            return None
        parts = content.get('parts')
        if not isinstance(parts, list) or any(
            not isinstance(part, dict) for part in parts
        ):
            raise ValueError('Invalid private model parts.')
        public_parts = []
        for part in parts:
            if part.get('thought') or 'text' not in part:
                continue
            if not isinstance(part['text'], str):
                raise TypeError('Invalid private model text.')
            public_parts.append({'text': part['text']})
        if not public_parts:
            return None
        public = {
            key: record[key]
            for key in (
                'id',
                'invocationId',
                'author',
                'timestamp',
                'partial',
                'turnComplete',
                'finishReason',
                'interrupted',
            )
            if key in record and isinstance(record[key], (str, bool, int, float))
        }
        public['content'] = {'role': 'model', 'parts': public_parts}
        encoded = json.dumps(public, ensure_ascii=False, allow_nan=False).encode(
            'utf-8'
        )
        return b'data: ' + encoded + b'\n\n'
