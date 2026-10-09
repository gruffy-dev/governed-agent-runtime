import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any, Literal

from starlette.types import ASGIApp, Message

from .ada_application_error import AdaApplicationError
from ...models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration


class AdaAsgiTransport:
    def __init__(
        self,
        application: ASGIApp,
        configuration: AdaApplicationAdapterConfiguration,
        *,
        lifespan_state: dict[str, Any] | None = None,
    ) -> None:
        """
        Bind internal HTTP dispatch to a private ASGI application reference.

        The app must not be mounted on the public router. Public adapters must
        derive paths and bodies from trusted context rather than proxy caller
        input. This transport accepts no user credentials or network endpoint.

        :param application: Unmodified private ADA ASGI application.
        :param configuration: Queue, response size and protocol configuration.
        :param lifespan_state: Infrastructure state supplied by ASGI startup.
        """
        self._application = application
        self._configuration = configuration
        self._lifespan_state = lifespan_state if lifespan_state is not None else {}

    async def request_json(
        self,
        method: Literal['GET', 'POST'],
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        """
        Read a bounded internal JSON response without exposing failure bodies.

        :param method: Internal HTTP method.
        :param path: Server-constructed private API path, without a query string.
        :param payload: Server-constructed JSON request body.

        :return: Parsed private session API response for subsequent projection.

        :raises AdaApplicationError: If status, body size or JSON shape is invalid.
        """
        body = bytearray()
        async with aclosing(self.stream_response(method, path, payload)) as messages:
            async for message in messages:
                if message['type'] == 'http.response.start':
                    status_code = message['status']
                    if not 200 <= status_code < 300:
                        raise AdaApplicationError(
                            'Private application rejected the request.',
                            status_code=status_code,
                        )
                else:
                    body.extend(message.get('body', b''))
                    if len(body) > self._configuration.maximum_response_bytes:
                        raise AdaApplicationError(
                            'Private application response exceeded its size limit.'
                        )
        try:
            parsed = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise AdaApplicationError(
                'Private application returned invalid JSON.'
            ) from None
        if not isinstance(parsed, (dict, list)):
            raise AdaApplicationError(
                'Private application returned an invalid JSON shape.'
            )
        return parsed

    async def stream_response(
        self,
        method: Literal['GET', 'POST'],
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> AsyncIterator[Message]:
        """
        Yield response headers and body chunks before private execution finishes.

        The consuming application task owns execution. Closing this iterator
        cancels private execution; browser subscribers must never own it.
        Request scopes and queues are independent for every invocation.

        :param method: Internal HTTP method.
        :param path: Server-constructed private route without query parameters.
        :param payload: Server-constructed JSON request body.

        :return: Incremental ASGI response messages, not public SSE events.

        :raises AdaApplicationError: If the private app fails or violates the protocol.
        """
        if not path.startswith('/') or '?' in path or '#' in path:
            raise AdaApplicationError(
                'Private route must be an absolute path without query parameters.'
            )
        body = b'' if payload is None else json.dumps(payload).encode('utf-8')
        queue: asyncio.Queue[Message] = asyncio.Queue(
            maxsize=self._configuration.response_queue_capacity
        )
        request_sent = False
        response_started = False
        response_complete = False
        disconnected = asyncio.Event()

        async def receive() -> Message:
            """
            Deliver the private body once and keep its connection alive.

            :return: ASGI request body or deliberate internal disconnection.
            """
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            await disconnected.wait()
            return {'type': 'http.disconnect'}

        async def send(message: Message) -> None:
            """
            Validate and enqueue bounded incremental response messages.

            :param message: Response message from the private application.

            :raises AdaApplicationError: If ordering or payload size is invalid.
            """
            nonlocal response_started, response_complete
            if response_complete:
                raise AdaApplicationError(
                    'Private application sent data after response completion.'
                )
            if message['type'] == 'http.response.start':
                if response_started:
                    raise AdaApplicationError(
                        'Private application started its response twice.'
                    )
                response_started = True
            elif message['type'] == 'http.response.body':
                if not response_started:
                    raise AdaApplicationError(
                        'Private application sent a body before response headers.'
                    )
                if (
                    len(message.get('body', b''))
                    > self._configuration.maximum_response_bytes
                ):
                    raise AdaApplicationError(
                        'Private application chunk exceeded its size limit.'
                    )
                response_complete = not message.get('more_body', False)
            else:
                raise AdaApplicationError(
                    'Private application sent an unsupported response message.'
                )
            await queue.put(dict(message))

        scope = {
            'type': 'http',
            'asgi': {
                'version': '3.0',
                'spec_version': self._configuration.asgi_spec_version,
            },
            'http_version': '1.1',
            'method': method,
            'scheme': 'http',
            'path': path,
            'raw_path': path.encode('utf-8'),
            'query_string': b'',
            'root_path': '',
            'headers': [(b'content-type', b'application/json')],
            'client': None,
            'server': None,
            'state': self._lifespan_state.copy(),
        }
        task = asyncio.create_task(self._application(scope, receive, send))
        try:
            while True:
                message = await self._next_message(queue, task)
                yield message
                if message['type'] == 'http.response.body' and not message.get(
                    'more_body', False
                ):
                    break
            try:
                await task
            except Exception:  # noqa: BLE001 - SDK diagnostics must not cross the public boundary.
                raise AdaApplicationError(
                    'Private application execution failed.'
                ) from None
        finally:
            disconnected.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _next_message(
        self,
        queue: asyncio.Queue[Message],
        application_task: asyncio.Task[None],
    ) -> Message:
        """
        Wait for a response message without hanging on an application failure.

        :param queue: Bounded request-local response queue.
        :param application_task: Private request execution task.

        :return: Next incremental response message.

        :raises AdaApplicationError: If execution finishes without a complete response.
        """
        if not queue.empty():
            return queue.get_nowait()
        message_task = asyncio.create_task(queue.get())
        try:
            completed, _ = await asyncio.wait(
                (message_task, application_task), return_when=asyncio.FIRST_COMPLETED
            )
            if message_task in completed:
                return message_task.result()
            if not queue.empty():
                return queue.get_nowait()
            raise AdaApplicationError(
                'Private application ended before a complete response.'
            )
        finally:
            message_task.cancel()
            await asyncio.gather(message_task, return_exceptions=True)
