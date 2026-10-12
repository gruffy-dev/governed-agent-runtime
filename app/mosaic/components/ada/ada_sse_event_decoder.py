import json
from collections.abc import Iterator
from typing import Any

from .ada_application_error import AdaApplicationError
from ...models.api.invocation_stream_configuration import InvocationStreamConfiguration


class AdaSseEventDecoder:
    def __init__(self, configuration: InvocationStreamConfiguration) -> None:
        """
        Bind a request-local incremental decoder to its private frame-size limit.

        :param configuration: Validated stream buffering limits.
        """
        self._maximum_bytes = configuration.maximum_event_bytes
        self._line = bytearray()
        self._data: list[str] = []
        self._frame_bytes = 0
        self._skip_lf = False
        self._closed = False

    def feed(self, chunk: bytes) -> Iterator[dict[str, Any]]:
        """
        Decode complete private JSON records across arbitrary UTF-8 byte chunks.

        Accept LF, CRLF and CR line endings, multiline data fields and ignored
        SSE comments/metadata. Never interpret a transport chunk as an event.
        Consume this iterator completely before supplying the next chunk.

        :param chunk: Private ASGI body bytes, not a public response payload.

        :return: Internal JSON objects for allowlisted public projection.

        :raises AdaApplicationError: If framing, encoding, JSON or bounds are invalid.
        """
        if self._closed:
            raise AdaApplicationError('Private SSE decoder is closed.')
        try:
            for value in chunk:
                if self._skip_lf:
                    self._skip_lf = False
                    if value == 10:
                        continue
                self._frame_bytes += 1
                if self._frame_bytes > self._maximum_bytes:
                    raise ValueError('Frame limit exceeded.')
                if value in {10, 13}:
                    self._skip_lf = value == 13
                    record = self._complete_line()
                    if record is not None:
                        yield record
                else:
                    self._line.append(value)
        except (TypeError, ValueError, RecursionError):
            self._closed = True
            self._line.clear()
            self._data.clear()
            raise AdaApplicationError(
                'Private SSE record could not be decoded safely.'
            ) from None

    def finish(self) -> None:
        """
        Reject truncated records at EOF without treating EOF as invocation success.

        :raises AdaApplicationError: If a JSON data record or line is incomplete.
        """
        if self._closed:
            raise AdaApplicationError('Private SSE decoder is closed.')
        self._closed = True
        incomplete = bool(self._line or self._data)
        self._line.clear()
        self._data.clear()
        if incomplete:
            raise AdaApplicationError(
                'Private SSE stream ended with an incomplete record.'
            )

    def _complete_line(self) -> dict[str, Any] | None:
        """
        Consume one complete UTF-8 SSE line and dispatch on a blank delimiter.

        :return: Private JSON object on dispatch, or None for incomplete/no-data frames.

        :raises ValueError: If dispatched JSON is not a finite JSON object.
        :raises TypeError: If the private JSON payload is not an object.
        :raises UnicodeDecodeError: If the completed line is not valid UTF-8.
        """
        line = self._line.decode('utf-8')
        self._line.clear()
        if line:
            field, _, value = line.partition(':')
            if field == 'data':
                self._data.append(value.removeprefix(' '))
            return None
        data = '\n'.join(self._data)
        has_data = bool(self._data)
        self._data.clear()
        self._frame_bytes = 0
        if not has_data:
            return None
        record = json.loads(data)
        if not isinstance(record, dict):
            raise TypeError('Private SSE requires JSON objects.')
        json.dumps(record, allow_nan=False, ensure_ascii=False).encode('utf-8')
        return record
