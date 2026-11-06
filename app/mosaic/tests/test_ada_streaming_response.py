import asyncio
import json
import unittest
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI
from starlette.requests import ClientDisconnect
from starlette.responses import StreamingResponse
from starlette.types import Message

from mosaic.components.ada.ada_application_error import AdaApplicationError
from mosaic.components.ada.ada_asgi_transport import AdaAsgiTransport
from mosaic.components.api.ada_streaming_response import AdaStreamingResponse
from mosaic.models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration


class TestAdaStreamingResponse(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.closed = False
        self.record = {
            'id': 'synthetic-event',
            'invocationId': 'synthetic-invocation',
            'author': 'mosaic',
            'partial': True,
            'content': {'role': 'model', 'parts': [{'text': 'Hello'}]},
        }

    async def _stream(
        self,
        chunks: list[bytes],
        status: int = 200,
        content_type: bytes = b'text/event-stream; charset=utf-8',
        fail: bool = False,
    ) -> AsyncGenerator[Message, None]:
        try:
            yield {
                'type': 'http.response.start',
                'status': status,
                'headers': [(b'content-type', content_type)],
            }
            for chunk in chunks:
                yield {'type': 'http.response.body', 'body': chunk, 'more_body': True}
            if fail:
                raise RuntimeError('synthetic-private-transport-detail')
            yield {'type': 'http.response.body', 'body': b'', 'more_body': False}
        finally:
            self.closed = True

    @staticmethod
    def _frame(record: dict[str, Any]) -> bytes:
        return b'data: ' + json.dumps(record, ensure_ascii=False).encode() + b'\n\n'

    async def _collect(
        self, chunks: list[bytes], bound: int = 8192
    ) -> list[dict[str, Any]]:
        response = await AdaStreamingResponse.create(
            self._stream(chunks), bound, 'mosaic'
        )
        body = b''.join([chunk async for chunk in response.body_iterator])
        self.assertNotIn(b'event:', body)
        self.assertTrue(self.closed)
        return [
            json.loads(line[5:])
            for line in body.splitlines()
            if line.startswith(b'data:')
        ]

    async def test_native_deltas_and_repeated_final_text_are_unchanged(self) -> None:
        records = [
            self.record,
            dict(self.record, content={'role': 'model', 'parts': [{'text': ' there'}]}),
            dict(
                self.record,
                partial=False,
                content={'role': 'model', 'parts': [{'text': 'Hello there'}]},
            ),
        ]
        result = await self._collect(
            [b''.join(self._frame(record) for record in records)]
        )
        self.assertEqual(result, records)

    async def test_fragmented_utf8_and_sse_line_endings(self) -> None:
        self.record['content']['parts'][0]['text'] = 'Hello café\nthere'
        for separator in (b'\n', b'\r\n', b'\r'):
            with self.subTest(separator=separator):
                self.closed = False
                body = b': comment' + separator + b'id: ignored' + separator
                body += self._frame(self.record).replace(b'\n', separator)
                result = await self._collect([bytes([byte]) for byte in body])
                self.assertEqual(result, [self.record])

    async def test_tools_thoughts_signatures_state_and_other_authors_are_excluded(
        self,
    ) -> None:
        record = dict(
            self.record,
            actions={'stateDelta': {'secret': 'synthetic-private-state'}},
            customMetadata={'secret': 'synthetic-private-metadata'},
            content={
                'role': 'model',
                'parts': [
                    {
                        'text': 'Hello',
                        'thoughtSignature': 'synthetic-private-signature',
                    },
                    {'text': 'synthetic-private-thought', 'thought': True},
                    {
                        'functionCall': {
                            'name': 'synthetic-tool',
                            'args': {'secret': 'synthetic-private-argument'},
                        }
                    },
                    {
                        'functionResponse': {
                            'name': 'synthetic-tool',
                            'response': {'secret': 'synthetic-private-result'},
                        }
                    },
                ],
            },
        )
        records = [
            record,
            dict(self.record, author='other-agent'),
            dict(self.record, branch='internal.branch'),
            dict(
                self.record,
                content={'role': 'user', 'parts': [{'text': 'private input'}]},
            ),
            dict(
                self.record,
                content={
                    'role': 'model',
                    'parts': [{'functionCall': {'name': 'tool'}}],
                },
            ),
        ]
        result = await self._collect([b''.join(self._frame(item) for item in records)])
        self.assertEqual(result, [self.record])
        self.assertNotIn('synthetic-private', json.dumps(result))

    async def test_private_errors_become_one_generic_adk_error_then_stop(self) -> None:
        for error in (
            {
                'error': 'synthetic-private-error',
                'error_details': 'synthetic-private-detail',
            },
            {
                'errorCode': 'synthetic-private-code',
                'errorMessage': 'synthetic-private-message',
            },
        ):
            with self.subTest(error=error):
                self.closed = False
                result = await self._collect(
                    [self._frame(error), self._frame(self.record)]
                )
                self.assertEqual(result, [{'error': 'Invocation failed'}])

    async def test_native_activity_survives_the_public_filter_without_private_payloads(
        self,
    ) -> None:
        parts = [
            {
                'functionCall': {
                    'name': 'load_skills',
                    'id': 'load',
                    'args': {'private': 'private'},
                }
            },
            {
                'functionResponse': {
                    'name': 'load_skills',
                    'id': 'load',
                    'response': {
                        'status': 'loaded',
                        'catalogue_commit_sha': 'private',
                        'loaded_skills': [
                            {
                                'name': 'inspect-logs',
                                'instructions': 'private',
                                'required_capability_names': ['splunk.pod.logs.read'],
                                'optional_capability_names': [],
                            }
                        ],
                    },
                }
            },
            {
                'functionCall': {
                    'name': 'discover_capabilities',
                    'id': 'discovery',
                    'args': {'target_name': 'private'},
                }
            },
            {
                'functionResponse': {
                    'name': 'discover_capabilities',
                    'id': 'discovery',
                    'response': {
                        'status': 'available',
                        'target': {'endpoint': 'private'},
                        'capabilities': [
                            {
                                'name': 'splunk.pod.logs.read',
                                'available': True,
                                'description': 'Read recent application logs.',
                                'provider': 'private',
                                'required_semantic_argument_names': ['private'],
                            }
                        ],
                    },
                }
            },
            {
                'functionCall': {
                    'name': 'execute_capability',
                    'id': 'check',
                    'args': {
                        'capability_name': 'splunk.pod.logs.read',
                        'semantic_arguments': {'token': 'private'},
                    },
                }
            },
            {
                'functionResponse': {
                    'name': 'execute_capability',
                    'id': 'check',
                    'response': {
                        'status': 'failed',
                        'evidence': 'private',
                        'error_message': 'private',
                    },
                }
            },
        ]
        records = [
            dict(
                self.record,
                partial=False,
                actions={'stateDelta': {'private': 'private'}},
                content={
                    'role': 'model' if 'functionCall' in part else 'user',
                    'parts': [part],
                },
            )
            for part in parts
        ]
        projected = await self._collect(
            [b''.join(self._frame(record) for record in records)]
        )
        self.assertEqual(len(projected), 6)
        calls = [record['content']['parts'][0] for record in projected]
        self.assertEqual(
            calls[0]['functionCall'], {'name': 'load_skills', 'id': 'load', 'args': {}}
        )
        self.assertEqual(
            calls[1]['functionResponse']['response']['loaded_skills'],
            [
                {
                    'name': 'inspect-logs',
                    'required_capability_names': ['splunk.pod.logs.read'],
                    'optional_capability_names': [],
                }
            ],
        )
        self.assertEqual(
            calls[3]['functionResponse']['response']['capabilities'],
            [
                {
                    'name': 'splunk.pod.logs.read',
                    'available': True,
                    'description': 'Read recent application logs.',
                }
            ],
        )
        self.assertEqual(
            calls[4]['functionCall']['args'],
            {'capability_name': 'splunk.pod.logs.read'},
        )
        self.assertEqual(calls[5]['functionResponse']['response'], {})
        self.assertNotIn('private', json.dumps(projected))

    async def test_partial_hidden_unmatched_and_undeclared_activity_is_not_exposed(
        self,
    ) -> None:
        records = [
            dict(
                self.record,
                content={
                    'role': 'model',
                    'parts': [
                        {
                            'functionCall': {
                                'name': 'load_skills',
                                'id': 'partial',
                                'args': {},
                            }
                        }
                    ],
                },
            ),
            dict(
                self.record,
                partial=False,
                content={
                    'role': 'user',
                    'parts': [
                        {
                            'functionResponse': {
                                'name': 'load_skills',
                                'id': 'unmatched',
                                'response': {'status': 'loaded', 'private': 'private'},
                            }
                        }
                    ],
                },
            ),
            dict(
                self.record,
                partial=False,
                branch='private',
                content={
                    'role': 'model',
                    'parts': [
                        {
                            'functionCall': {
                                'name': 'discover_skills',
                                'id': 'hidden',
                                'args': {},
                            }
                        }
                    ],
                },
            ),
            dict(
                self.record,
                partial=False,
                content={
                    'role': 'model',
                    'parts': [
                        {
                            'functionCall': {
                                'name': 'execute_capability',
                                'id': 'call',
                                'args': {'capability_name': 'private.unknown.read'},
                            }
                        }
                    ],
                },
            ),
        ]
        projected = await self._collect(
            [b''.join(self._frame(record) for record in records)]
        )
        self.assertEqual(len(projected), 1)
        self.assertEqual(
            projected[0]['content']['parts'],
            [
                {
                    'functionCall': {
                        'name': 'execute_capability',
                        'id': 'call',
                        'args': {},
                    }
                }
            ],
        )

    async def test_invalid_truncated_and_oversized_frames_fail_safely(self) -> None:
        for body in (
            b'data: invalid-json\n\n',
            b'data: []\n\n',
            b'data: {"unfinished":',
            b'data: \xff\n\n',
            self._frame(
                dict(self.record, content={'role': 'model', 'parts': [{'text': 1}]})
            ),
            self._frame(dict(self.record, timestamp=float('nan'))),
            b':' + b'x' * 1024,
        ):
            with self.subTest(body=body):
                self.closed = False
                result = await self._collect([body], bound=512)
                self.assertEqual(result, [{'error': 'Invocation failed'}])

    async def test_transport_failure_after_text_is_sanitised(self) -> None:
        response = await AdaStreamingResponse.create(
            self._stream([self._frame(self.record)], fail=True), 8192, 'mosaic'
        )
        chunks = [chunk async for chunk in response.body_iterator]
        self.assertEqual(json.loads(chunks[0][5:]), self.record)
        self.assertEqual(chunks[1], b'data: {"error":"Invocation failed"}\n\n')
        self.assertTrue(self.closed)

    async def test_preflight_rejection_closes_private_stream(self) -> None:
        for status, content_type in (
            (404, b'text/event-stream'),
            (200, b'application/json'),
        ):
            with self.subTest(status=status, content_type=content_type):
                self.closed = False
                with self.assertRaises(AdaApplicationError):
                    await AdaStreamingResponse.create(
                        self._stream(
                            [b'synthetic-private-detail'], status, content_type
                        ),
                        8192,
                        'mosaic',
                    )
                self.assertTrue(self.closed)

    async def test_eof_does_not_invent_completion(self) -> None:
        self.assertEqual(await self._collect([self._frame(self.record)]), [self.record])

    async def test_frame_limit_is_not_a_total_stream_limit(self) -> None:
        body = self._frame(self.record)
        self.assertEqual(
            await self._collect([body * 10], bound=len(body)), [self.record] * 10
        )

    async def test_browser_disconnect_and_write_failure_close_real_private_execution(
        self,
    ) -> None:
        for version in ('2.3', '2.4'):
            with self.subTest(version=version):
                private_closed = asyncio.Event()
                first_sent = asyncio.Event()
                finalised: list[bool] = []
                private = FastAPI()

                async def events(
                    private_closed: asyncio.Event = private_closed,
                ) -> AsyncGenerator[bytes, None]:
                    try:
                        yield self._frame(self.record)
                        await asyncio.Event().wait()
                    finally:
                        private_closed.set()

                @private.post('/run_sse')
                async def run() -> StreamingResponse:
                    return StreamingResponse(events(), media_type='text/event-stream')

                transport = AdaAsgiTransport(
                    private,
                    AdaApplicationAdapterConfiguration(asgi_spec_version=version),
                )

                async def on_close(
                    normal_eof: bool,
                    private_closed: asyncio.Event = private_closed,
                    finalised: list[bool] = finalised,
                ) -> None:
                    self.assertTrue(private_closed.is_set())
                    finalised.append(normal_eof)

                response = await AdaStreamingResponse.create(
                    transport.stream_response('POST', '/run_sse'),
                    8192,
                    'mosaic',
                    on_close,
                )

                async def receive(first_sent: asyncio.Event = first_sent) -> Message:
                    await first_sent.wait()
                    return {'type': 'http.disconnect'}

                async def send(
                    message: Message,
                    first_sent: asyncio.Event = first_sent,
                    version: str = version,
                ) -> None:
                    if message['type'] == 'http.response.body' and message.get('body'):
                        first_sent.set()
                        if version == '2.4':
                            raise OSError('Synthetic browser connection closed')

                scope = {
                    'type': 'http',
                    'asgi': {'version': '3.0', 'spec_version': version},
                }
                if version == '2.4':
                    with self.assertRaises(ClientDisconnect):
                        await asyncio.wait_for(response(scope, receive, send), 2)
                else:
                    await asyncio.wait_for(response(scope, receive, send), 2)
                await asyncio.wait_for(private_closed.wait(), 2)
                self.assertEqual(finalised, [False])

    async def test_browser_gets_first_event_before_private_completion(self) -> None:
        gate = asyncio.Event()
        first_sent = asyncio.Event()
        captured: list[bytes] = []
        finalised: list[bool] = []

        async def stream() -> AsyncGenerator[Message, None]:
            yield {
                'type': 'http.response.start',
                'status': 200,
                'headers': [(b'content-type', b'text/event-stream')],
            }
            yield {
                'type': 'http.response.body',
                'body': self._frame(
                    dict(
                        self.record,
                        partial=False,
                        content={
                            'role': 'model',
                            'parts': [
                                {
                                    'functionCall': {
                                        'name': 'discover_skills',
                                        'id': 'discovery',
                                        'args': {'private': 'private'},
                                    }
                                }
                            ],
                        },
                    )
                ),
                'more_body': True,
            }
            await gate.wait()
            yield {
                'type': 'http.response.body',
                'body': self._frame(dict(self.record, partial=False)),
            }

        async def on_close(normal_eof: bool) -> None:
            finalised.append(normal_eof)

        response = await AdaStreamingResponse.create(stream(), 8192, 'mosaic', on_close)

        async def receive() -> Message:
            await asyncio.Event().wait()
            return {'type': 'http.disconnect'}

        async def send(message: Message) -> None:
            if message['type'] == 'http.response.body' and message.get('body'):
                captured.append(message['body'])
                first_sent.set()

        task = asyncio.create_task(
            response({'type': 'http', 'asgi': {'spec_version': '2.3'}}, receive, send)
        )
        try:
            await asyncio.wait_for(first_sent.wait(), 2)
            self.assertFalse(task.done())
            self.assertEqual(len(captured), 1)
            self.assertEqual(
                json.loads(captured[0][5:])['content']['parts'],
                [
                    {
                        'functionCall': {
                            'name': 'discover_skills',
                            'id': 'discovery',
                            'args': {},
                        },
                    }
                ],
            )
            gate.set()
            await asyncio.wait_for(task, 2)
            self.assertEqual(len(captured), 2)
            self.assertEqual(finalised, [True])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
