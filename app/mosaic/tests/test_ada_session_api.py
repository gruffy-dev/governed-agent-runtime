import unittest
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request

from mosaic.components.ada.ada_application_error import AdaApplicationError
from mosaic.components.ada.ada_asgi_transport import AdaAsgiTransport
from mosaic.components.ada.ada_session_api import AdaSessionApi
from mosaic.models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration
from mosaic.models.identity.trusted_request_context import TrustedRequestContext


class TestAdaSessionApi(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.context = TrustedRequestContext(app_name='synthetic-app', user_id='synthetic-user')
        self.transport = AsyncMock(spec=AdaAsgiTransport)
        self.api = AdaSessionApi(self.transport)

    async def test_creation_generates_uuid_and_accepts_no_caller_state(self) -> None:
        async def respond(method: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
            return {'id': payload['session_id'], 'appName': self.context.app_name, 'userId': self.context.user_id}

        self.transport.request_json.side_effect = respond
        result = await self.api.create(self.context)
        args = self.transport.request_json.call_args.args
        self.assertEqual(args[:2], ('POST', '/apps/synthetic-app/users/synthetic-user/sessions'))
        self.assertEqual(set(args[2]), {'session_id'})
        self.assertEqual(UUID(result['id']).version, 4)
        self.assertEqual(result['id'], args[2]['session_id'])

    async def test_get_uses_trusted_scope_and_exact_uuid(self) -> None:
        session_id = uuid4()
        self.transport.request_json.return_value = {
            'id': str(session_id), 'app_name': self.context.app_name, 'user_id': self.context.user_id,
        }
        result = await self.api.get(self.context, session_id)
        self.assertEqual(result['id'], str(session_id))
        self.transport.request_json.assert_awaited_once_with(
            'GET', f'/apps/synthetic-app/users/synthetic-user/sessions/{session_id}',
        )

    async def test_empty_list(self) -> None:
        self.transport.request_json.return_value = []
        self.assertEqual(await self.api.list(self.context), [])

    async def test_list_validates_all_records_before_return(self) -> None:
        own = {'id': str(uuid4()), 'appName': self.context.app_name, 'userId': self.context.user_id}
        foreign = dict(own, userId='another-synthetic-user')
        self.transport.request_json.return_value = [own]
        self.assertEqual(await self.api.list(self.context), [own])
        self.transport.request_json.return_value = [own, foreign]
        with self.assertRaises(AdaApplicationError):
            await self.api.list(self.context)

    async def test_missing_foreign_or_conflicting_identity_fails_closed(self) -> None:
        session_id = uuid4()
        own = {'id': str(session_id), 'appName': self.context.app_name, 'userId': self.context.user_id}
        for record in (
            {'id': str(session_id)},
            dict(own, appName='another-synthetic-app'),
            dict(own, userId='another-synthetic-user'),
            dict(own, app_name='another-synthetic-app'),
            dict(own, user_id='another-synthetic-user'),
            dict(own, id=str(uuid4())),
            dict(own, id=''),
        ):
            with self.subTest(record=record):
                self.transport.request_json.return_value = record
                with self.assertRaises(AdaApplicationError) as caught:
                    await self.api.get(self.context, session_id)
                self.assertNotIn('another-synthetic', str(caught.exception))

    async def test_malformed_response_shapes(self) -> None:
        self.transport.request_json.return_value = {}
        with self.assertRaises(AdaApplicationError):
            await self.api.list(self.context)
        self.transport.request_json.return_value = []
        with self.assertRaises(AdaApplicationError):
            await self.api.get(self.context, uuid4())

    async def test_invalid_path_identity_is_rejected_before_dispatch(self) -> None:
        for user_id in ('../another-user', 'user/another-user', 'user?query', 'user%2fother', 'user name'):
            with self.subTest(user_id=user_id):
                context = TrustedRequestContext(app_name='synthetic-app', user_id=user_id)
                with self.assertRaises(AdaApplicationError):
                    await self.api.create(context)
        self.transport.request_json.assert_not_awaited()

    async def test_non_uuid_lookup_is_rejected_before_dispatch(self) -> None:
        with self.assertRaises(AdaApplicationError):
            await self.api.get(self.context, '../another-session')
        self.transport.request_json.assert_not_awaited()

    async def test_upstream_404_is_preserved(self) -> None:
        self.transport.request_json.side_effect = AdaApplicationError('Private request rejected.', status_code=404)
        with self.assertRaises(AdaApplicationError) as caught:
            await self.api.get(self.context, uuid4())
        self.assertEqual(caught.exception.status_code, 404)

    async def test_real_transport_keeps_two_users_separate(self) -> None:
        app = FastAPI()
        records: dict[tuple[str, str, str], dict[str, Any]] = {}

        @app.post('/apps/{app_name}/users/{user_id}/sessions')
        async def create(app_name: str, user_id: str, request: Request) -> dict[str, Any]:
            body = await request.json()
            record = {'id': body['session_id'], 'appName': app_name, 'userId': user_id}
            records[(app_name, user_id, record['id'])] = record
            return record

        @app.get('/apps/{app_name}/users/{user_id}/sessions')
        async def list_sessions(app_name: str, user_id: str) -> list[dict[str, Any]]:
            return [value for (app_id, owner_id, _), value in records.items() if (app_id, owner_id) == (app_name, user_id)]

        @app.get('/apps/{app_name}/users/{user_id}/sessions/{session_id}')
        async def get(app_name: str, user_id: str, session_id: str) -> dict[str, Any]:
            record = records.get((app_name, user_id, session_id))
            if record is None:
                raise HTTPException(status_code=404)
            return record

        api = AdaSessionApi(AdaAsgiTransport(app, AdaApplicationAdapterConfiguration()))
        created = await api.create(self.context)
        session_id = UUID(created['id'])
        self.assertEqual(await api.get(self.context, session_id), created)
        other = TrustedRequestContext(app_name=self.context.app_name, user_id='another-synthetic-user')
        self.assertEqual(await api.list(other), [])
        with self.assertRaises(AdaApplicationError) as caught:
            await api.get(other, session_id)
        self.assertEqual(caught.exception.status_code, 404)
