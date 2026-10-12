import time
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from mosaic.backend import Backend
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration
from mosaic.models.identity.trusted_request_configuration import TrustedRequestConfiguration
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


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

    def test_create_list_and_get_use_public_models_only(self) -> None:
        created = self._create()
        self.assertEqual(
            set(created),
            {'conversation_id', 'title', 'created_at', 'last_activity_at', 'messages'},
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
            available, {'createConversation', 'listConversations', 'getConversation'}
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
