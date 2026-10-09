import asyncio
import unittest
from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from mosaic.components.ada.ada_application_error import AdaApplicationError
from mosaic.components.ada.ada_application_lifecycle import AdaApplicationLifecycle
from mosaic.components.ada.ada_asgi_transport import AdaAsgiTransport
from mosaic.models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration


class TestAdaAsgiTransport(unittest.IsolatedAsyncioTestCase):
    async def test_json_body_and_lifespan_state_without_credentials(self) -> None:
        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, str]]:
            yield {'infrastructure': 'synthetic'}

        app = FastAPI(lifespan=lifespan)

        @app.post('/sessions')
        async def create(request: Request) -> dict[str, Any]:
            return {
                'body': await request.json(),
                'headers': dict(request.headers),
                'state': request.state.infrastructure,
            }

        configuration = AdaApplicationAdapterConfiguration()
        lifecycle = AdaApplicationLifecycle(app, configuration)
        transport = AdaAsgiTransport(app, configuration, lifespan_state=lifecycle.state)
        async with lifecycle.running():
            result = await transport.request_json(
                'POST', '/sessions', {'user_id': 'synthetic-user'}
            )
        self.assertEqual(result['body'], {'user_id': 'synthetic-user'})
        self.assertEqual(result['state'], 'synthetic')
        self.assertEqual(result['headers'], {'content-type': 'application/json'})

    async def test_stream_is_incremental_and_explicit_close_cleans_up(self) -> None:
        for version in ('2.3', '2.4'):
            with self.subTest(version=version):
                gate = asyncio.Event()
                closed = asyncio.Event()

                async def events(
                    gate: asyncio.Event = gate, closed: asyncio.Event = closed
                ) -> AsyncIterator[bytes]:
                    try:
                        yield b'data: first\n\n'
                        await gate.wait()
                        yield b'data: last\n\n'
                    finally:
                        closed.set()

                app = FastAPI()

                @app.post('/run_sse')
                async def run() -> StreamingResponse:
                    return StreamingResponse(events(), media_type='text/event-stream')

                transport = AdaAsgiTransport(
                    app, AdaApplicationAdapterConfiguration(asgi_spec_version=version)
                )
                async with aclosing(
                    transport.stream_response('POST', '/run_sse')
                ) as stream:
                    start = await asyncio.wait_for(anext(stream), 1)
                    first = await asyncio.wait_for(anext(stream), 1)
                    self.assertEqual(start['status'], 200)
                    self.assertEqual(first['body'], b'data: first\n\n')
                    self.assertFalse(gate.is_set())
                await asyncio.wait_for(closed.wait(), 1)

    async def test_application_owned_stream_survives_subscriber_cancellation(
        self,
    ) -> None:
        gate = asyncio.Event()
        observed = asyncio.Event()
        browser_queue: asyncio.Queue[bytes] = asyncio.Queue()
        stored: list[bytes] = []
        app = FastAPI()

        async def events() -> AsyncIterator[bytes]:
            yield b'first'
            await gate.wait()
            yield b'last'

        @app.post('/run_sse')
        async def run() -> StreamingResponse:
            return StreamingResponse(events())

        transport = AdaAsgiTransport(app, AdaApplicationAdapterConfiguration())

        async def collect() -> None:
            async with aclosing(
                transport.stream_response('POST', '/run_sse')
            ) as stream:
                async for message in stream:
                    if message['type'] == 'http.response.body' and message.get('body'):
                        stored.append(message['body'])
                        browser_queue.put_nowait(message['body'])

        async def subscribe() -> None:
            await browser_queue.get()
            observed.set()
            await asyncio.Event().wait()

        producer = asyncio.create_task(collect())
        subscriber = asyncio.create_task(subscribe())
        try:
            await asyncio.wait_for(observed.wait(), 1)
            subscriber.cancel()
            await asyncio.gather(subscriber, return_exceptions=True)
            self.assertFalse(producer.done())
            gate.set()
            await asyncio.wait_for(producer, 1)
            self.assertEqual(stored, [b'first', b'last'])
        finally:
            producer.cancel()
            subscriber.cancel()
            await asyncio.gather(producer, subscriber, return_exceptions=True)

    async def test_rejected_status_does_not_expose_private_body(self) -> None:
        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send({'type': 'http.response.start', 'status': 404, 'headers': []})
            await send(
                {'type': 'http.response.body', 'body': b'synthetic-private-diagnostic'}
            )

        transport = AdaAsgiTransport(app, AdaApplicationAdapterConfiguration())
        with self.assertRaises(AdaApplicationError) as caught:
            await transport.request_json('GET', '/missing')
        self.assertEqual(caught.exception.status_code, 404)
        self.assertNotIn('synthetic-private-diagnostic', str(caught.exception))

    async def test_failed_or_incomplete_app_is_sanitized(self) -> None:
        for failure in ('before', 'after', 'incomplete'):
            with self.subTest(failure=failure):

                async def app(
                    scope: Scope, receive: Receive, send: Send, failure: str = failure
                ) -> None:
                    if failure != 'before':
                        await send(
                            {
                                'type': 'http.response.start',
                                'status': 200,
                                'headers': [],
                            }
                        )
                        await send(
                            {
                                'type': 'http.response.body',
                                'body': b'partial',
                                'more_body': True,
                            }
                        )
                    if failure != 'incomplete':
                        raise RuntimeError('synthetic-private-diagnostic')

                transport = AdaAsgiTransport(app, AdaApplicationAdapterConfiguration())
                with self.assertRaises(AdaApplicationError) as caught:
                    await asyncio.wait_for(transport.request_json('GET', '/failure'), 1)
                self.assertNotIn('synthetic-private-diagnostic', str(caught.exception))

    async def test_response_and_chunk_limits(self) -> None:
        for chunks in ([b'12345'], [b'123', b'456']):
            with self.subTest(chunks=chunks):

                async def app(
                    scope: Scope,
                    receive: Receive,
                    send: Send,
                    chunks: list[bytes] = chunks,
                ) -> None:
                    await send(
                        {'type': 'http.response.start', 'status': 200, 'headers': []}
                    )
                    for chunk in chunks:
                        await send(
                            {
                                'type': 'http.response.body',
                                'body': chunk,
                                'more_body': True,
                            }
                        )
                    await send({'type': 'http.response.body', 'body': b''})

                transport = AdaAsgiTransport(
                    app, AdaApplicationAdapterConfiguration(maximum_response_bytes=4)
                )
                with self.assertRaises(AdaApplicationError):
                    await transport.request_json('GET', '/large')

    async def test_bounded_queue_applies_backpressure(self) -> None:
        sent: list[int] = []
        blocked = asyncio.Event()

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            for index in range(10):
                if index == 1:
                    blocked.set()
                await send(
                    {'type': 'http.response.body', 'body': b'x', 'more_body': True}
                )
                sent.append(index)
            await send({'type': 'http.response.body', 'body': b''})

        transport = AdaAsgiTransport(
            app, AdaApplicationAdapterConfiguration(response_queue_capacity=1)
        )
        async with aclosing(transport.stream_response('GET', '/stream')) as stream:
            await anext(stream)
            await asyncio.wait_for(blocked.wait(), 1)
            self.assertLessEqual(len(sent), 1)
            async for message in stream:
                self.assertIn(
                    message['type'], ('http.response.start', 'http.response.body')
                )
        self.assertEqual(len(sent), 10)

    async def test_invalid_json_and_route_rejected(self) -> None:
        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'not-json'})

        transport = AdaAsgiTransport(app, AdaApplicationAdapterConfiguration())
        for path in ('relative', '/route?query=value', '/route#fragment', '/valid'):
            with self.subTest(path=path), self.assertRaises(AdaApplicationError):
                await transport.request_json('GET', path)
