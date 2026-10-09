import unittest
from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Any
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from starlette.types import Message

from mosaic.components.ada.ada_application_error import AdaApplicationError
from mosaic.components.ada.ada_asgi_transport import AdaAsgiTransport
from mosaic.components.ada.ada_invocation_api import AdaInvocationApi
from mosaic.models.api.submit_message_request import SubmitMessageRequest
from mosaic.models.identity.trusted_request_context import TrustedRequestContext


class TestAdaInvocationApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.context = TrustedRequestContext(
            app_name='synthetic-app', user_id='synthetic-user'
        )
        self.conversation_id = uuid4()
        self.transport = Mock(spec=AdaAsgiTransport)
        self.transport.request_json = AsyncMock(
            return_value={
                'id': str(self.conversation_id),
                'appName': self.context.app_name,
                'userId': self.context.user_id,
            }
        )
        self.api = AdaInvocationApi(self.transport)
        self.message = SubmitMessageRequest(text='Synthetic greeting')

    async def test_stream_body_is_constructed_from_trusted_identity_only(self) -> None:
        calls: list[tuple[str, str, dict[str, Any]]] = []

        async def stream(
            method: str, path: str, payload: dict[str, Any]
        ) -> AsyncIterator[Message]:
            calls.append((method, path, payload))
            self.transport.request_json.assert_awaited_once_with(
                'GET',
                f'/apps/synthetic-app/users/synthetic-user/sessions/{self.conversation_id}',
            )
            yield {'type': 'http.response.start', 'status': 200, 'headers': []}
            yield {'type': 'http.response.body', 'body': b'data: {}\n\n'}

        self.transport.stream_response.side_effect = stream
        messages = [
            message
            async for message in self.api.stream(
                self.context, self.conversation_id, self.message
            )
        ]
        self.assertEqual(len(messages), 2)
        self.assertEqual(
            calls,
            [
                (
                    'POST',
                    '/run_sse',
                    {
                        'app_name': 'synthetic-app',
                        'user_id': 'synthetic-user',
                        'session_id': str(self.conversation_id),
                        'new_message': {
                            'role': 'user',
                            'parts': [{'text': 'Synthetic greeting'}],
                        },
                        'streaming': True,
                    },
                )
            ],
        )

    async def test_foreign_or_unknown_conversation_never_executes(self) -> None:
        self.transport.request_json.side_effect = AdaApplicationError(
            'Unavailable.', status_code=404
        )
        with self.assertRaises(AdaApplicationError) as caught:
            await anext(
                self.api.stream(self.context, self.conversation_id, self.message)
            )
        self.assertEqual(caught.exception.status_code, 404)
        self.transport.stream_response.assert_not_called()

    async def test_inconsistent_upstream_ownership_never_executes(self) -> None:
        self.transport.request_json.return_value['userId'] = 'another-synthetic-user'
        with self.assertRaises(AdaApplicationError):
            await anext(
                self.api.stream(self.context, self.conversation_id, self.message)
            )
        self.transport.stream_response.assert_not_called()

    async def test_unvalidated_input_is_rejected_before_dispatch(self) -> None:
        with self.assertRaises(AdaApplicationError):
            await anext(
                self.api.stream(
                    self.context,
                    self.conversation_id,
                    {'text': 'hello', 'user_id': 'other'},
                )
            )
        self.transport.request_json.assert_not_awaited()
        self.transport.stream_response.assert_not_called()

    async def test_invalid_conversation_reference_never_executes(self) -> None:
        with self.assertRaises(AdaApplicationError):
            await anext(self.api.stream(self.context, '../other-session', self.message))
        self.transport.request_json.assert_not_awaited()
        self.transport.stream_response.assert_not_called()

    async def test_rejected_execution_does_not_yield_private_error_body(self) -> None:
        async def stream(*args: object) -> AsyncIterator[Message]:
            yield {'type': 'http.response.start', 'status': 404}
            yield {'type': 'http.response.body', 'body': b'synthetic-private-detail'}

        self.transport.stream_response.side_effect = stream
        with self.assertRaises(AdaApplicationError) as caught:
            await anext(
                self.api.stream(self.context, self.conversation_id, self.message)
            )
        self.assertEqual(caught.exception.status_code, 404)
        self.assertNotIn('synthetic-private-detail', str(caught.exception))

    async def test_closing_consumer_closes_private_stream(self) -> None:
        closed: list[bool] = []

        async def stream(*args: object) -> AsyncIterator[Message]:
            try:
                yield {'type': 'http.response.start', 'status': 200}
                yield {'type': 'http.response.body', 'body': b'data: {}\n\n'}
            finally:
                closed.append(True)

        self.transport.stream_response.side_effect = stream
        async with aclosing(
            self.api.stream(self.context, self.conversation_id, self.message)
        ) as response:
            await anext(response)
        self.assertEqual(closed, [True])
