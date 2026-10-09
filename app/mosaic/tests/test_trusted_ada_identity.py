import unittest
from contextlib import aclosing
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Any
from unittest.mock import Mock, patch
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from mosaic.backend import Backend
from mosaic.components.ada.ada_application_error import AdaApplicationError
from mosaic.components.ada.ada_invocation_api import AdaInvocationApi
from mosaic.components.ada.ada_session_api import AdaSessionApi
from mosaic.models.api.submit_message_request import SubmitMessageRequest
from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from mosaic.models.identity.trusted_request_configuration import TrustedRequestConfiguration
from mosaic.models.identity.trusted_request_context import TrustedRequestContext
from mosaic.models.identity.trusted_user_context import TrustedUserContext
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestTrustedAdaIdentity(unittest.TestCase):
    def test_public_wrapper_preserves_two_user_isolation_and_ignores_all_claims(
        self,
    ) -> None:
        private = FastAPI()
        records: dict[tuple[str, str, str], dict[str, Any]] = {}
        executed: list[dict[str, Any]] = []
        private_headers: list[dict[str, str]] = []

        @private.post('/apps/{app_name}/users/{user_id}/sessions')
        async def create_session(
            app_name: str, user_id: str, request: Request
        ) -> dict[str, Any]:
            payload = await request.json()
            record = {
                'id': payload['session_id'],
                'appName': app_name,
                'userId': user_id,
            }
            records[(app_name, user_id, record['id'])] = record
            return record

        @private.get('/apps/{app_name}/users/{user_id}/sessions/{session_id}')
        async def get_session(
            app_name: str, user_id: str, session_id: str
        ) -> dict[str, Any]:
            record = records.get((app_name, user_id, session_id))
            if record is None:
                raise HTTPException(status_code=404)
            return record

        @private.post('/run_sse')
        async def run(request: Request) -> dict[str, str]:
            executed.append(await request.json())
            private_headers.append(dict(request.headers))
            return {'status': 'synthetic-complete'}

        def configure(application: FastAPI) -> None:
            dependency = application.state.trusted_request_context_dependency

            async def create(
                request: Request,
                context: Annotated[TrustedRequestContext, Depends(dependency)],
            ) -> dict[str, str]:
                session = await AdaSessionApi(request.app.state.ada_transport).create(
                    context
                )
                return {'conversation_id': session['id']}

            async def execute(
                claimed_user_id: str,
                conversation_id: UUID,
                request: Request,
                context: Annotated[TrustedRequestContext, Depends(dependency)],
            ) -> dict[str, str]:
                body = await request.json()
                message = SubmitMessageRequest(text=body['text'])
                api = AdaInvocationApi(request.app.state.ada_transport)
                try:
                    async with aclosing(
                        api.stream(context, conversation_id, message)
                    ) as stream:
                        async for _ in stream:
                            pass
                except AdaApplicationError as error:
                    raise HTTPException(
                        status_code=error.status_code or 500, detail='Unavailable'
                    ) from None
                return {'status': 'complete'}

            application.add_api_route(
                '/api/v1/identity-test/sessions', create, methods=['POST']
            )
            application.add_api_route(
                '/api/v1/identity-test/{claimed_user_id}/{conversation_id}',
                execute,
                methods=['POST'],
            )

        identities = {
            'synthetic-token-a': TrustedUserContext(user_id='synthetic-user-a'),
            'synthetic-token-b': TrustedUserContext(user_id='synthetic-user-b'),
        }
        authenticator = Mock()
        authenticator.authenticate.side_effect = identities.get
        with (
            TemporaryDirectory() as directory,
            patch(
                'mosaic.components.identity.pilot_bearer_authenticator.PilotBearerAuthenticator',
                return_value=authenticator,
            ),
        ):
            public = Backend.create_application(
                ada_app_factory=lambda: private,
                application_configurer=configure,
                database_configuration=MosaicDatabaseConfiguration(
                    database_path=Path(directory) / 'mosaic.db'
                ),
                pilot_administration_configuration=PilotAdministrationConfiguration(
                    enabled=False
                ),
                trusted_request_configuration=TrustedRequestConfiguration(
                    app_name='synthetic-app'
                ),
            )
            with TestClient(public) as client:
                created = client.post(
                    '/api/v1/identity-test/sessions',
                    headers={'Authorization': 'Bearer synthetic-token-a'},
                )
                self.assertEqual(created.status_code, 200)
                conversation_id = created.json()['conversation_id']
                claims = {
                    'app_name': 'claimed-app',
                    'user_id': 'synthetic-user-a',
                    'workspace_id': 'claimed-workspace',
                    'owner_id': 'claimed-owner',
                }
                path = f'/api/v1/identity-test/synthetic-user-a/{conversation_id}'
                for credential in ('bearer', 'cookie'):
                    with self.subTest(credential=credential):
                        headers = {
                            'X-User-ID': 'synthetic-user-a',
                            'X-App-Name': 'claimed-app',
                        }
                        if credential == 'bearer':
                            headers['Authorization'] = 'Bearer synthetic-token-b'
                        else:
                            client.cookies.set(
                                'mosaic_pilot_session', 'synthetic-token-b'
                            )
                        denied = client.post(
                            path,
                            headers=headers,
                            params=claims,
                            json={**claims, 'text': 'hello', 'state': claims},
                        )
                        self.assertEqual(denied.status_code, 404)
                        self.assertEqual(executed, [])
                        client.cookies.clear()
                own_claims = {**claims, 'user_id': 'synthetic-user-b'}
                for credential in ('bearer', 'cookie'):
                    with self.subTest(credential=credential):
                        headers = {
                            'X-User-ID': 'synthetic-user-b',
                            'X-App-Name': 'claimed-app',
                        }
                        if credential == 'bearer':
                            headers['Authorization'] = 'Bearer synthetic-token-a'
                        else:
                            client.cookies.set(
                                'mosaic_pilot_session', 'synthetic-token-a'
                            )
                        allowed = client.post(
                            f'/api/v1/identity-test/synthetic-user-b/{conversation_id}',
                            headers=headers,
                            params=own_claims,
                            json={**own_claims, 'text': 'hello', 'state': own_claims},
                        )
                        self.assertEqual(allowed.status_code, 200)
                        client.cookies.clear()
                unauthenticated = client.post(path, json={'text': 'hello'})
                self.assertEqual(unauthenticated.status_code, 401)
                self.assertEqual(client.post('/run_sse', json={}).status_code, 401)
                self.assertEqual(
                    client.post(
                        '/run_sse',
                        headers={'Authorization': 'Bearer synthetic-token-a'},
                        json={},
                    ).status_code,
                    404,
                )
        self.assertEqual(len(executed), 2)
        for payload in executed:
            self.assertEqual(payload['app_name'], 'synthetic-app')
            self.assertEqual(payload['user_id'], 'synthetic-user-a')
            self.assertEqual(payload['session_id'], conversation_id)
            self.assertEqual(
                set(payload),
                {'app_name', 'user_id', 'session_id', 'new_message', 'streaming'},
            )
        for headers in private_headers:
            self.assertEqual(headers, {'content-type': 'application/json'})
