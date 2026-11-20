import asyncio
import json
import time
import unittest
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse
from starlette.types import Message

from mosaic.backend import Backend
from mosaic.models.identity.browser_access_configuration import BrowserAccessConfiguration
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.conversation_metadata_repository import ConversationMetadataRepository
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration
from mosaic.models.identity.trusted_request_configuration import TrustedRequestConfiguration
from mosaic.models.identity.trusted_request_context import TrustedRequestContext
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration
from mosaic.models.orchestration.orchestration_state import OrchestrationState


class TestConversationApi(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.configuration = MosaicDatabaseConfiguration(
            database_path=Path(self.directory.name) / 'mosaic.db'
        )
        self.database = MosaicDatabase(self.configuration)
        self.addCleanup(self.database.dispose)
        MosaicDatabaseMigrator(self.database).upgrade()
        with self.database.create_session() as session, session.begin():
            repository = UserAccessRepository(session)
            for suffix in ('a', 'b'):
                user_id = f'synthetic-user-{suffix}'
                repository.add_user(user_id, datetime.now(UTC))
                repository.add_access_token(
                    str(uuid4()),
                    user_id,
                    f'synthetic-token-{suffix}',
                    datetime.now(UTC),
                )
        self.private = FastAPI()
        self.records: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.calls: list[str] = []

        @self.private.post('/apps/{app_name}/users/{user_id}/sessions')
        async def create(
            app_name: str, user_id: str, request: Request
        ) -> dict[str, Any]:
            payload = await request.json()
            self.assertEqual(set(payload), {'session_id'})
            record = {
                'id': payload['session_id'],
                'appName': app_name,
                'userId': user_id,
                'lastUpdateTime': time.time(),
                'events': [],
                'state': {'private': 'synthetic-private-state'},
            }
            self.records[(app_name, user_id, record['id'])] = record
            self.calls.append('create')
            return record

        @self.private.get('/apps/{app_name}/users/{user_id}/sessions')
        async def list_sessions(app_name: str, user_id: str) -> list[dict[str, Any]]:
            self.calls.append('list')
            return [
                {key: value for key, value in record.items() if key != 'events'}
                for (app, user, _), record in self.records.items()
                if (app, user) == (app_name, user_id)
            ]

        @self.private.get('/apps/{app_name}/users/{user_id}/sessions/{session_id}')
        async def get(app_name: str, user_id: str, session_id: str) -> dict[str, Any]:
            self.calls.append('get')
            record = self.records.get((app_name, user_id, session_id))
            if record is None:
                raise HTTPException(status_code=404, detail='synthetic-private-detail')
            return record

        self.application = self._backend()
        self.client = TestClient(self.application)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {'Authorization': 'Bearer synthetic-token-a'}

    def _backend(self) -> FastAPI:
        return Backend.create_application(
            ada_app_factory=lambda: self.private,
            database_configuration=self.configuration,
            browser_access_configuration=BrowserAccessConfiguration(allowed_origins=('http://127.0.0.1:8050',)),
            trusted_request_configuration=TrustedRequestConfiguration(
                app_name='synthetic-app'
            ),
            pilot_administration_configuration=PilotAdministrationConfiguration(
                enabled=False
            ),
            pilot_authentication_configuration=PilotAuthenticationConfiguration(
                mode='local', secure_cookie=False
            ),
        )

    def _create(self) -> dict[str, Any]:
        response = self.client.post(
            '/api/v1/conversations', headers=self.headers, json={}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(UUID(response.headers['X-Correlation-ID']).version, 4)
        return response.json()

    def _install_stream(self, *, fail: bool = False, reject: bool = False, phase: str = 'completed', block: bool = False) -> None:
        self.invocations: list[dict[str, Any]] = []
        self.private_headers: list[dict[str, str]] = []
        self.private_stream_closed = False

        @self.private.post('/run_sse')
        async def run(request: Request) -> StreamingResponse:
            self.invocations.append(await request.json())
            self.private_headers.append(dict(request.headers))
            if reject:
                raise HTTPException(status_code=500, detail='synthetic-private-detail')
            if block and len(self.invocations) > 1:
                payload = self.invocations[-1]
                stored = self.records[(payload['app_name'], payload['user_id'], payload['session_id'])]
                if stored['state']['mosaic:orchestration']['phase'] != 'completed':
                    raise HTTPException(status_code=409, detail='Synthetic invocation is still active')

            async def events() -> AsyncIterator[bytes]:
                record = {
                    'id': 'synthetic-event',
                    'invocationId': 'synthetic-invocation',
                    'author': 'mosaic',
                    'partial': True,
                    'content': {'role': 'model', 'parts': [{'text': 'Hello'}]},
                }
                if block and len(self.invocations) == 1:
                    payload = self.invocations[-1]
                    stored = self.records[(payload['app_name'], payload['user_id'], payload['session_id'])]
                    stored['state']['mosaic:orchestration'] = OrchestrationState.start(
                        'synthetic-invocation'
                    ).model_dump(mode='json')
                    stored['events'].append({
                        'id': 'synthetic-prompt', 'author': 'user', 'timestamp': time.time(),
                        'content': payload['new_message'],
                    })
                    try:
                        yield b'data: ' + json.dumps(record).encode() + b'\n\n'
                        await asyncio.Event().wait()
                    finally:
                        self.private_stream_closed = True
                    return
                yield b'data: ' + json.dumps(record).encode() + b'\n\n'
                if fail:
                    yield b'data: {"error":"synthetic-private-detail"}\n\n'
                else:
                    record['partial'] = False
                    yield b'data: ' + json.dumps(record).encode() + b'\n\n'
                    payload = self.invocations[-1]
                    self.records[(payload['app_name'], payload['user_id'], payload['session_id'])]['state']['mosaic:orchestration'] = {'phase': phase}

                self.private_stream_closed = True

            return StreamingResponse(events(), media_type='text/event-stream')

    def test_job_completes_without_a_stream_and_replays_to_its_owner(self) -> None:
        self._install_stream()
        conversation_id = self._create()['conversation_id']
        created = self.client.post(
            f'/api/v1/conversations/{conversation_id}/jobs',
            headers=self.headers, json={'text': 'Read synthetic status'},
        )
        self.assertEqual(created.status_code, 202)
        path = f'/api/v1/conversations/jobs/{created.json()["job_id"]}'
        job = self._wait_for_job(path, 'succeeded')
        self.assertEqual(job['result_text'], 'Hello')
        self.assertEqual(len(self.invocations), 1)
        replay = self.client.get(path + '/events', headers=self.headers, params={'after': 1})
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.text.startswith('id: 2\n'))
        self.assertNotIn('id: 1', replay.text)
        foreign = {'Authorization': 'Bearer synthetic-token-b'}
        self.assertEqual(self.client.get(path, headers=foreign).status_code, 404)
        self.assertEqual(self.client.get(path + '/events', headers=foreign).status_code, 404)
        self.assertEqual(self.client.post(path + '/stop', headers=foreign).status_code, 404)

    def test_job_stop_waits_for_private_close_and_blocks_unsafe_follow_up(self) -> None:
        self._check_job_stop_and_follow_up(patch_succeeds=False)

    def test_job_stop_recovers_same_conversation_for_follow_up(self) -> None:
        self._check_job_stop_and_follow_up(patch_succeeds=True)

    def _check_job_stop_and_follow_up(self, *, patch_succeeds: bool) -> None:
        self._install_stream(block=True)
        patches = []

        @self.private.patch('/apps/{app_name}/users/{user_id}/sessions/{session_id}')
        async def patch_session(app_name: str, user_id: str, session_id: str, request: Request) -> dict[str, Any]:
            self.assertTrue(self.private_stream_closed)
            context = TrustedRequestContext(app_name=app_name, user_id=user_id)
            with self.database.create_session() as session:
                self.assertFalse(ConversationMetadataRepository(session).begin_invocation(context, UUID(session_id)))
            payload = await request.json()
            patches.append(payload)
            if not patch_succeeds:
                raise HTTPException(status_code=500, detail='Synthetic persistence failure')
            record = self.records[(app_name, user_id, session_id)]
            state = OrchestrationState.model_validate(payload['state_delta']['mosaic:orchestration'])
            record['state']['mosaic:orchestration'] = state.model_dump(mode='json', exclude_none=True)
            return record

        conversation_id = self._create()['conversation_id']
        submit = f'/api/v1/conversations/{conversation_id}/jobs'
        created = self.client.post(submit, headers=self.headers, json={'text': 'Read synthetic status'})
        self.assertEqual(created.status_code, 202)
        path = f'/api/v1/conversations/jobs/{created.json()["job_id"]}'
        self._wait_for_job(path, 'running')
        async def disconnect_from_replay() -> None:
            first_frame = asyncio.Event()

            async def receive() -> Message:
                await first_frame.wait()
                return {'type': 'http.disconnect'}

            async def send(message: Message) -> None:
                if message['type'] == 'http.response.start':
                    self.assertEqual(message['status'], 200)
                elif b'Hello' in message.get('body', b''):
                    first_frame.set()

            events_path = path + '/events'
            scope = {
                'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
                'method': 'GET', 'path': events_path, 'raw_path': events_path.encode(),
                'query_string': b'', 'headers': [(b'authorization', b'Bearer synthetic-token-a')],
                'scheme': 'http', 'http_version': '1.1', 'server': ('testserver', 80), 'client': ('testclient', 1),
            }
            await asyncio.wait_for(self.application(scope, receive, send), 3)

        asyncio.run(disconnect_from_replay())
        self.assertFalse(self.private_stream_closed)
        self.assertEqual(self.client.get(path, headers=self.headers).json()['status'], 'running')
        self.assertTrue(self.invocations)
        stopped = self.client.post(path + '/stop', headers=self.headers)
        self.assertEqual(stopped.status_code, 200)
        self.assertIn(stopped.json()['status'], ('stopping', 'cancelled'))
        cancelled = self._wait_for_job(path, 'cancelled')
        self.assertIsNone(cancelled['result_text'])
        self.assertTrue(self.private_stream_closed)
        self.assertEqual(len(patches), 1)
        self.assertEqual(set(patches[0]), {'state_delta'})
        self.assertEqual(set(patches[0]['state_delta']), {'mosaic:orchestration'})
        completed = OrchestrationState.model_validate(patches[0]['state_delta']['mosaic:orchestration'])
        self.assertEqual(completed.phase, 'completed')
        self.assertEqual(completed.active_invocation_id, 'synthetic-invocation')
        follow_up = self.client.post(submit, headers=self.headers, json={'text': 'Follow up'})
        if patch_succeeds:
            self.assertEqual(follow_up.status_code, 202)
            second_job = self._wait_for_job(f'/api/v1/conversations/jobs/{follow_up.json()["job_id"]}', 'succeeded')
            self.assertEqual(second_job['result_text'], 'Hello')
            self.assertEqual(self.invocations[-1]['session_id'], conversation_id)
            self.assertEqual(len(patches), 1)
        else:
            self.assertEqual(follow_up.status_code, 409)

    def _wait_for_job(self, path: str, status: str) -> dict[str, Any]:
        deadline = time.monotonic() + 3
        while True:
            response = self.client.get(path, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            job = response.json()
            if job['status'] == status:
                return job
            if time.monotonic() >= deadline:
                self.fail(f'Job did not reach {status}: {job}')
            time.sleep(0.01)

    def test_stream_uses_trusted_identity_and_preserves_native_adk_text(self) -> None:
        self._install_stream()
        created = self._create()
        response = self.client.post(
            f'/api/v1/conversations/{created["conversation_id"]}/messages',
            headers={**self.headers, 'X-User-ID': 'synthetic-user-b'},
            params={'app_name': 'other-app', 'user_id': 'synthetic-user-b'},
            json={'text': 'Synthetic greeting'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers['Content-Type'].startswith('text/event-stream'))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.headers['X-Accel-Buffering'], 'no')
        self.assertEqual(UUID(response.headers['X-Correlation-ID']).version, 4)
        events = [json.loads(line[5:]) for line in response.text.splitlines() if line.startswith('data:')]
        self.assertEqual([event['partial'] for event in events], [True, False])
        self.assertEqual([event['content']['parts'][0]['text'] for event in events], ['Hello', 'Hello'])
        self.assertNotIn('event:', response.text)
        self.assertEqual(self.invocations, [{
            'app_name': 'synthetic-app',
            'user_id': 'synthetic-user-a',
            'session_id': created['conversation_id'],
            'new_message': {'role': 'user', 'parts': [{'text': 'Synthetic greeting'}]},
            'streaming': True,
        }])
        self.assertEqual(self.private_headers, [{'content-type': 'application/json'}])

    def test_stream_cookie_authentication_and_foreign_ownership(self) -> None:
        self._install_stream()
        created = self._create()
        self.client.cookies.set('mosaic_pilot_session', 'synthetic-token-a')
        owned = self.client.post(
            f'/api/v1/conversations/{created["conversation_id"]}/messages',
            headers={'Origin': 'http://127.0.0.1:8050'},
            json={'text': 'Synthetic greeting'},
        )
        self.assertEqual(owned.status_code, 200)
        self.assertEqual(owned.headers['Access-Control-Allow-Origin'], 'http://127.0.0.1:8050')
        self.assertEqual(owned.headers['Access-Control-Allow-Credentials'], 'true')
        self.client.cookies.clear()
        self.invocations.clear()
        self.calls.clear()
        for identifier in (created['conversation_id'], str(uuid4())):
            response = self.client.post(
                f'/api/v1/conversations/{identifier}/messages',
                headers={'Authorization': 'Bearer synthetic-token-b'},
                json={'text': 'Synthetic greeting'},
            )
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()['error_code'], 'conversation_not_found')
        self.assertEqual(self.invocations, [])
        self.assertEqual(self.calls, [])

    def test_failed_conversation_is_read_only_and_flags_survive_restart(self) -> None:
        self._install_stream(fail=True)
        created = self._create()
        path = f'/api/v1/conversations/{created["conversation_id"]}'
        response = self.client.post(path + '/messages', headers=self.headers, json={'text': 'Hello'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.private_stream_closed)
        with TestClient(self._backend()) as restarted:
            detail = restarted.get(path, headers=self.headers)
            self.assertEqual(detail.status_code, 200)
            self.assertFalse(detail.json()['can_continue'])
            self.assertTrue(detail.json()['is_interrupted'])
            listed = restarted.get('/api/v1/conversations', headers=self.headers).json()
            self.assertFalse(listed['conversations'][0]['can_continue'])
            self.assertTrue(listed['conversations'][0]['is_interrupted'])
            before = len(self.invocations)
            rejected = restarted.post(path + '/messages', headers=self.headers, json={'text': 'Another message'})
            self.assertEqual(rejected.status_code, 409)
            self.assertEqual(rejected.json()['error_code'], 'conversation_interrupted')
            self.assertEqual(rejected.json()['detail'], 'Interrupted — cannot continue')
            self.assertIn('Start a new conversation', rejected.json()['action'])
            self.assertEqual(rejected.headers['X-Correlation-ID'], rejected.json()['correlation_id'])
            self.assertEqual(len(self.invocations), before)
            foreign = restarted.post(path + '/messages', headers={'Authorization': 'Bearer synthetic-token-b'}, json={'text': 'Hello'})
            self.assertEqual(foreign.status_code, 404)
        self.assertEqual(self.client.get('/ready').status_code, 200)
        fresh = self._create()
        self.assertTrue(fresh['can_continue'])
        self.assertFalse(fresh['is_interrupted'])

    def test_normal_completion_and_clarification_allow_next_message(self) -> None:
        for phase in ('completed', 'awaiting_clarification'):
            with self.subTest(phase=phase):
                self.private.router.routes = [route for route in self.private.router.routes if getattr(route, 'path', None) != '/run_sse']
                self._install_stream(phase=phase)
                created = self._create()
                path = f'/api/v1/conversations/{created["conversation_id"]}'
                for _ in range(2):
                    response = self.client.post(path + '/messages', headers=self.headers, json={'text': 'Hello'})
                    self.assertEqual(response.status_code, 200)
                    detail = self.client.get(path, headers=self.headers).json()
                    self.assertTrue(detail['can_continue'])
                    self.assertFalse(detail['is_interrupted'])

    def test_stream_eof_without_saved_completion_is_not_available(self) -> None:
        self._install_stream(phase='planning')
        created = self._create()
        path = f'/api/v1/conversations/{created["conversation_id"]}'
        response = self.client.post(path + '/messages', headers=self.headers, json={'text': 'Hello'})
        self.assertEqual(response.status_code, 200)
        detail = self.client.get(path, headers=self.headers).json()
        self.assertFalse(detail['can_continue'])
        self.assertTrue(detail['is_interrupted'])

    def test_reserved_conversation_is_not_mislabelled_as_interrupted(self) -> None:
        self._install_stream()
        created = self._create()
        context = TrustedRequestContext(app_name='synthetic-app', user_id='synthetic-user-a')
        with self.database.create_session() as session, session.begin():
            self.assertTrue(ConversationMetadataRepository(session).begin_invocation(context, UUID(created['conversation_id'])))
        path = f'/api/v1/conversations/{created["conversation_id"]}'
        detail = self.client.get(path, headers=self.headers).json()
        self.assertFalse(detail['can_continue'])
        self.assertFalse(detail['is_interrupted'])
        rejected = self.client.post(path + '/messages', headers=self.headers, json={'text': 'Hello'})
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(rejected.json()['error_code'], 'conversation_busy')
        self.assertEqual(self.invocations, [])

    def test_disconnect_marks_interrupted_after_private_cleanup_and_keeps_history(self) -> None:
        self._install_stream(block=True)
        created = self._create()
        path = f'/api/v1/conversations/{created["conversation_id"]}'

        async def interrupt() -> None:
            first_sent = asyncio.Event()
            body_sent = False
            captured: list[Message] = []

            async def receive() -> Message:
                nonlocal body_sent
                if not body_sent:
                    body_sent = True
                    return {'type': 'http.request', 'body': b'{"text":"Synthetic long prompt"}', 'more_body': False}
                await first_sent.wait()
                return {'type': 'http.disconnect'}

            async def send(message: Message) -> None:
                captured.append(message)
                if message['type'] == 'http.response.body' and message.get('body'):
                    first_sent.set()

            scope = {
                'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.3'},
                'method': 'POST', 'path': path + '/messages', 'raw_path': (path + '/messages').encode(),
                'query_string': b'', 'headers': [(b'authorization', b'Bearer synthetic-token-a'), (b'content-type', b'application/json')],
                'scheme': 'http', 'http_version': '1.1', 'server': ('testserver', 80), 'client': ('testclient', 1),
            }
            await asyncio.wait_for(self.application(scope, receive, send), 3)
            self.assertEqual(captured[0]['status'], 200)

        asyncio.run(interrupt())
        self.assertTrue(self.private_stream_closed)
        detail = self.client.get(path, headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        self.assertFalse(detail.json()['can_continue'])
        self.assertTrue(detail.json()['is_interrupted'])
        self.assertEqual(detail.json()['messages'][0]['text'], 'Synthetic long prompt')
        before = len(self.invocations)
        self.assertEqual(self.client.post(path + '/messages', headers=self.headers, json={'text': 'Retry'}).status_code, 409)
        self.assertEqual(len(self.invocations), before)

    def test_stream_rejects_anonymous_disabled_and_spoofed_body(self) -> None:
        self._install_stream()
        created = self._create()
        path = f'/api/v1/conversations/{created["conversation_id"]}/messages'
        self.calls.clear()
        self.assertEqual(self.client.post(path, json={'text': 'Hello'}).status_code, 401)
        for field in ('user_id', 'app_name', 'workspace_id', 'session_id', 'state'):
            response = self.client.post(path, headers=self.headers, json={'text': 'Hello', field: 'synthetic-private-claim'})
            self.assertEqual(response.status_code, 400)
            self.assertNotIn('synthetic-private', response.text)
        with self.database.create_session() as session, session.begin():
            UserAccessRepository(session).disable_user('synthetic-user-a', datetime.now(UTC))
        self.assertEqual(self.client.post(path, headers=self.headers, json={'text': 'Hello'}).status_code, 401)
        self.assertEqual(self.invocations, [])
        self.assertEqual(self.calls, [])

    def test_stream_errors_before_and_after_headers_are_safe(self) -> None:
        self._install_stream(fail=True)
        created = self._create()
        response = self.client.post(
            f'/api/v1/conversations/{created["conversation_id"]}/messages',
            headers=self.headers, json={'text': 'Hello'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('"error":"Invocation failed"', response.text)
        self.assertNotIn('synthetic-private', response.text)

    def test_stream_rejects_invalid_input_and_deleted_session_before_execution(self) -> None:
        self._install_stream()
        created = self._create()
        path = f'/api/v1/conversations/{created["conversation_id"]}/messages'
        self.calls.clear()
        for body in ({'text': ''}, {'text': '   '}, {}):
            response = self.client.post(path, headers=self.headers, json=body)
            self.assertEqual(response.status_code, 400)
        invalid_id = self.client.post(
            '/api/v1/conversations/invalid-id/messages', headers=self.headers, json={'text': 'Hello'}
        )
        malformed = self.client.post(
            path, headers={**self.headers, 'Content-Type': 'application/json'}, content='{"text":'
        )
        self.assertEqual(invalid_id.status_code, 400)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(self.calls, [])
        del self.records[('synthetic-app', 'synthetic-user-a', created['conversation_id'])]
        deleted = self.client.post(path, headers=self.headers, json={'text': 'Hello'})
        self.assertEqual(deleted.status_code, 404)
        self.assertEqual(deleted.json()['error_code'], 'conversation_not_found')
        self.assertEqual(self.invocations, [])

    def test_private_http_rejection_returns_json_before_public_stream_starts(self) -> None:
        self._install_stream(reject=True)
        created = self._create()
        response = self.client.post(
            f'/api/v1/conversations/{created["conversation_id"]}/messages',
            headers=self.headers, json={'text': 'Hello'},
        )
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers['Content-Type'], 'application/json')
        self.assertEqual(response.json()['error_code'], 'internal_error')
        self.assertNotIn('synthetic-private', response.text)

    def test_create_list_and_get_use_public_models_only(self) -> None:
        created = self._create()
        self.assertEqual(
            set(created),
            {'conversation_id', 'title', 'created_at', 'last_activity_at', 'messages', 'can_continue', 'is_interrupted'},
        )
        self.assertIsNone(created['title'])
        self.assertEqual(created['messages'], [])
        listed = self.client.get('/api/v1/conversations', headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            listed.json()['conversations'],
            [{key: value for key, value in created.items() if key != 'messages'}],
        )
        retrieved = self.client.get(
            f'/api/v1/conversations/{created["conversation_id"]}', headers=self.headers
        )
        self.assertEqual(retrieved.json(), created)
        self.assertEqual(listed.headers['Cache-Control'], 'no-store')
        self.assertEqual(retrieved.headers['Cache-Control'], 'no-store')
        self.assertNotIn('synthetic-private', retrieved.text)

    def test_cookie_authentication_and_restart_preserve_creation_timestamp(
        self,
    ) -> None:
        created = self._create()
        with TestClient(self._backend()) as restarted:
            restarted.cookies.set('mosaic_pilot_session', 'synthetic-token-a')
            response = restarted.get(
                f'/api/v1/conversations/{created["conversation_id"]}'
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['created_at'], created['created_at'])

    def test_foreign_and_missing_conversations_are_non_disclosing(self) -> None:
        created = self._create()
        self.calls.clear()
        for credential in ('bearer', 'cookie'):
            with self.subTest(credential=credential):
                headers = {'X-User-ID': 'synthetic-user-a'}
                if credential == 'bearer':
                    headers['Authorization'] = 'Bearer synthetic-token-b'
                else:
                    self.client.cookies.set('mosaic_pilot_session', 'synthetic-token-b')
                foreign = self.client.get(
                    f'/api/v1/conversations/{created["conversation_id"]}',
                    headers=headers,
                    params={'user_id': 'synthetic-user-a'},
                )
                missing = self.client.get(
                    f'/api/v1/conversations/{uuid4()}', headers=headers
                )
                self.assertEqual(foreign.status_code, 404)
                self.assertEqual(missing.status_code, 404)
                self.assertEqual(foreign.json()['error_code'], 'conversation_not_found')
                self.assertEqual(
                    {
                        key: value
                        for key, value in foreign.json().items()
                        if key != 'correlation_id'
                    },
                    {
                        key: value
                        for key, value in missing.json().items()
                        if key != 'correlation_id'
                    },
                )
                self.assertEqual(
                    foreign.headers['X-Correlation-ID'],
                    foreign.json()['correlation_id'],
                )
                self.client.cookies.clear()
        self.assertEqual(self.calls, [])
        listed = self.client.get(
            '/api/v1/conversations',
            headers={'Authorization': 'Bearer synthetic-token-b'},
        )
        self.assertEqual(listed.json(), {'conversations': []})

    def test_body_identity_and_state_claims_are_rejected_before_ada(self) -> None:
        for body in (
            {'user_id': 'other-user'},
            {'app_name': 'other-app'},
            {'workspace_id': 'other-workspace'},
            {'state': {'owner': 'other-user'}},
            {'conversation_id': str(uuid4())},
        ):
            with self.subTest(body=body):
                response = self.client.post(
                    '/api/v1/conversations', headers=self.headers, json=body
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['error_code'], 'invalid_request')
                self.assertNotIn('other-user', response.text)
        self.assertEqual(self.calls, [])

    def test_query_and_header_identity_claims_do_not_change_owner(self) -> None:
        response = self.client.post(
            '/api/v1/conversations',
            headers={
                **self.headers,
                'X-User-ID': 'synthetic-user-b',
                'X-App-Name': 'other-app',
            },
            params={
                'user_id': 'synthetic-user-b',
                'workspace_id': 'other-workspace',
                'app_name': 'other-app',
            },
            json={},
        )
        self.assertEqual(response.status_code, 201)
        conversation_id = response.json()['conversation_id']
        self.assertIn(
            ('synthetic-app', 'synthetic-user-a', conversation_id), self.records
        )

    def test_malformed_json_and_uuid_have_safe_400_envelopes(self) -> None:
        malformed = self.client.post(
            '/api/v1/conversations',
            headers={**self.headers, 'Content-Type': 'application/json'},
            content='{"private":',
        )
        invalid_id = self.client.get(
            '/api/v1/conversations/invalid-private-id', headers=self.headers
        )
        for response in (malformed, invalid_id):
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json()['error_code'], 'invalid_request')
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertNotIn('private', response.text)
        self.assertEqual(self.calls, [])

    def test_missing_credentials_and_disabled_user_cannot_reach_ada(self) -> None:
        anonymous = self.client.post('/api/v1/conversations', json={})
        self.assertEqual(anonymous.status_code, 401)
        with self.database.create_session() as session, session.begin():
            UserAccessRepository(session).disable_user(
                'synthetic-user-a', datetime.now(UTC)
            )
        disabled = self.client.get('/api/v1/conversations', headers=self.headers)
        self.assertEqual(disabled.status_code, 401)
        self.assertEqual(self.calls, [])

    def test_list_hydrates_history_filters_private_events_and_sorts_by_activity(
        self,
    ) -> None:
        first = self._create()
        second = self._create()
        record = self.records[
            ('synthetic-app', 'synthetic-user-a', first['conversation_id'])
        ]
        record['lastUpdateTime'] = time.time() + 1
        record['events'] = [
            {
                'id': 'prompt-id',
                'author': 'user',
                'timestamp': time.time(),
                'content': {'role': 'user', 'parts': [{'text': 'Public greeting'}]},
            },
            {
                'id': 'response-id',
                'author': 'mosaic',
                'timestamp': time.time(),
                'content': {
                    'role': 'model',
                    'parts': [
                        {'text': 'Public response'},
                        {'text': 'synthetic-private-thought', 'thought': True},
                    ],
                },
            },
            {
                'id': 'tool-id',
                'author': 'tool',
                'timestamp': time.time(),
                'content': {
                    'role': 'tool',
                    'parts': [{'text': 'synthetic-private-tool'}],
                },
            },
        ]
        listed = self.client.get('/api/v1/conversations', headers=self.headers)
        self.assertEqual(
            [item['conversation_id'] for item in listed.json()['conversations']],
            [first['conversation_id'], second['conversation_id']],
        )
        self.assertEqual(listed.json()['conversations'][0]['title'], 'Public greeting')
        history = self.client.get(
            f'/api/v1/conversations/{first["conversation_id"]}', headers=self.headers
        )
        self.assertEqual(
            [message['text'] for message in history.json()['messages']],
            ['Public greeting', 'Public response'],
        )
        self.assertNotIn('synthetic-private', history.text)

    def test_ada_only_and_deleted_sessions_are_not_public(self) -> None:
        created = self._create()
        template = dict(
            self.records[
                ('synthetic-app', 'synthetic-user-a', created['conversation_id'])
            ]
        )
        for legacy_id in ('legacy-dev-session', str(uuid4())):
            self.records[('synthetic-app', 'synthetic-user-a', legacy_id)] = dict(
                template, id=legacy_id
            )
        listed = self.client.get('/api/v1/conversations', headers=self.headers)
        self.assertEqual(len(listed.json()['conversations']), 1)
        del self.records[
            ('synthetic-app', 'synthetic-user-a', created['conversation_id'])
        ]
        missing = self.client.get(
            f'/api/v1/conversations/{created["conversation_id"]}', headers=self.headers
        )
        self.assertEqual(missing.status_code, 404)
        self.assertNotIn('synthetic-private-detail', missing.text)

    def test_metadata_failure_is_safe_and_ada_orphan_is_not_listed(self) -> None:
        with (
            patch(
                'mosaic.components.api.conversation_service.ConversationService._record_creation',
                side_effect=RuntimeError('synthetic-private-database-detail'),
            ),
            TestClient(self._backend(), raise_server_exceptions=False) as client,
        ):
            failure = client.post(
                '/api/v1/conversations', headers=self.headers, json={}
            )
        self.assertEqual(failure.status_code, 500)
        self.assertEqual(failure.json()['error_code'], 'internal_error')
        self.assertNotIn('synthetic-private', failure.text)
        listed = self.client.get('/api/v1/conversations', headers=self.headers)
        self.assertEqual(listed.json(), {'conversations': []})

    def test_contract_marks_only_registered_lifecycle_operations_available(
        self,
    ) -> None:
        document = self.client.get('/api/v1/openapi.json', headers=self.headers).json()
        available = {
            operation['operationId']
            for methods in document['paths'].values()
            for operation in methods.values()
            if operation['x-mosaic-implementation'] == 'available'
        }
        self.assertEqual(
            available, {
                'createConversation', 'listConversations', 'getConversation', 'submitMessage',
                'submitConversationJob', 'getConversationJob', 'streamConversationJob', 'stopConversationJob',
            }
        )

    def test_inconsistent_private_ownership_fails_closed_with_safe_correlated_log(
        self,
    ) -> None:
        created = self._create()
        record = self.records[
            ('synthetic-app', 'synthetic-user-a', created['conversation_id'])
        ]
        record['userId'] = 'synthetic-private-foreign-owner'
        with self.assertLogs('mosaic.conversation', level='WARNING') as audit:
            response = self.client.get('/api/v1/conversations', headers=self.headers)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()['error_code'], 'internal_error')
        self.assertEqual(
            audit.records[0].correlation_id, response.json()['correlation_id']
        )
        self.assertNotIn('synthetic-private', response.text)
        self.assertNotIn('synthetic-private', '\n'.join(audit.output))
        self.assertNotIn('synthetic-token-a', '\n'.join(audit.output))
