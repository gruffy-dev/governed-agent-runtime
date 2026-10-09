import hashlib
import json
import unittest
from http.cookiejar import Cookie
from typing import Any
from unittest.mock import Mock
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mosaic.components.identity.authentication_error import AuthenticationError
from mosaic.components.identity.authentication_failure_handler import AuthenticationFailureHandler
from mosaic.components.identity.pilot_administration_api import PilotAdministrationApi
from mosaic.components.identity.pilot_authentication_api import PilotAuthenticationApi
from mosaic.components.identity.pilot_authentication_middleware import PilotAuthenticationMiddleware
from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration


class TestAuthenticationFailureHandler(unittest.TestCase):
    def test_bearer_cookie_and_sign_in_failures_share_the_same_contract(
        self,
    ) -> None:
        application = self._create_application()
        token = 'synthetic-rejected-token'

        with (
            self.assertLogs('mosaic.authentication', level='WARNING') as logs,
            TestClient(application) as client,
        ):
            responses = [
                client.get('/protected'),
                client.get(
                    '/protected',
                    headers={'Authorization': 'Basic malformed'},
                ),
                client.get(
                    '/protected',
                    headers={'Authorization': f'Bearer {token}'},
                ),
                client.post('/api/v1/auth/token', json={'token': token}),
            ]
            client.cookies.set('mosaic_pilot_session', token)
            responses.append(client.get('/protected'))

        correlation_ids: set[str] = set()
        for response, record in zip(responses, logs.records, strict=True):
            self.assertEqual(response.status_code, 401)
            body = response.json()
            self._assert_envelope(body, 401)
            correlation_ids.add(body['correlation_id'])
            self.assertEqual(
                body['correlation_id'],
                response.headers['X-Correlation-ID'],
            )
            self.assertEqual(body['correlation_id'], record.correlation_id)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(response.headers['WWW-Authenticate'], 'Bearer')
            self.assertNotIn(token, response.text)
            self.assertNotIn('Set-Cookie', response.headers)
        self.assertEqual(len(correlation_ids), len(responses))

    def test_expired_browser_cookie_prompts_sign_in(self) -> None:
        application = self._create_application()

        with TestClient(application) as client:
            client.cookies.jar.set_cookie(
                Cookie(
                    version=0,
                    name='mosaic_pilot_session',
                    value='synthetic-expired-token',
                    port=None,
                    port_specified=False,
                    domain='testserver.local',
                    domain_specified=False,
                    domain_initial_dot=False,
                    path='/',
                    path_specified=True,
                    secure=False,
                    expires=1,
                    discard=False,
                    comment=None,
                    comment_url=None,
                    rest={'HttpOnly': None},
                )
            )
            response = client.get('/protected')

        self.assertEqual(response.status_code, 401)
        self.assertNotIn('cookie', response.request.headers)
        self.assertEqual(
            response.json()['action'],
            'Sign in again or supply a valid bearer token.',
        )

    def test_administrator_denials_use_correlated_forbidden_response(
        self,
    ) -> None:
        application = self._create_application()
        service = Mock()
        PilotAdministrationApi(
            PilotAdministrationConfiguration(
                enabled=True,
                administrator_secret=SecretStr('synthetic-admin-secret-for-testing-only'),
            ),
            service,
        ).register_routes(application)

        with (
            self.assertLogs('mosaic.authentication', level='WARNING') as logs,
            TestClient(application) as client,
        ):
            responses = (
                client.get('/api/v1/admin/users'),
                client.get(
                    '/api/v1/admin/users',
                    headers={'Authorization': 'Bearer synthetic-invalid-secret'},
                ),
            )

        for response, record in zip(responses, logs.records, strict=True):
            self.assertEqual(response.status_code, 403)
            self._assert_envelope(response.json(), 403)
            self.assertEqual(
                response.json()['correlation_id'],
                record.correlation_id,
            )
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertNotIn('WWW-Authenticate', response.headers)
        service.list_users.assert_not_called()

    def test_logs_exclude_credentials_hashes_and_request_claims(self) -> None:
        application = self._create_application()
        token = 'synthetic-private-token'
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        with (
            self.assertLogs('mosaic.authentication', level='WARNING') as logs,
            TestClient(application) as client,
        ):
            response = client.get(
                '/protected',
                params={'token': token, 'token_hash': token_hash},
                headers={
                    'Authorization': f'Bearer {token}',
                    'Cookie': f'mosaic_pilot_session={token}',
                    'X-Correlation-ID': token,
                    'X-User-ID': 'claimed-private-user',
                },
            )

        record = logs.records[0]
        metadata = json.loads(record.getMessage().split('failure ', 1)[1])
        self.assertEqual(
            set(metadata),
            {'mosaic_event', 'status_code', 'error_code', 'correlation_id'},
        )
        self.assertEqual(metadata['correlation_id'], response.json()['correlation_id'])
        for excluded in (
            token,
            token_hash,
            'claimed-private-user',
            'Authorization',
            'Cookie',
        ):
            self.assertNotIn(excluded, record.getMessage())
            self.assertNotIn(excluded, response.text)
            self.assertNotIn(excluded, str(record.__dict__))

    def test_existing_framework_exception_handler_is_preserved(self) -> None:
        application = FastAPI()

        async def framework_handler(
            request: Request,
            exception: Exception,
        ) -> JSONResponse:
            return JSONResponse({'framework_error': True}, status_code=404)

        application.add_exception_handler(HTTPException, framework_handler)
        AuthenticationFailureHandler().register(application)

        @application.get('/framework-error')
        async def framework_error() -> None:
            raise HTTPException(status_code=404)

        with TestClient(application) as client:
            response = client.get('/framework-error')

        self.assertIs(application.exception_handlers[HTTPException], framework_handler)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json(), {'framework_error': True})

    def test_unsupported_authentication_status_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AuthenticationError(status_code=500)

    def _assert_envelope(self, body: dict[str, Any], status_code: int) -> None:
        self.assertEqual(
            set(body),
            {'detail', 'error_code', 'action', 'correlation_id'},
        )
        self.assertEqual(
            body['error_code'],
            'unauthorized' if status_code == 401 else 'forbidden',
        )
        self.assertEqual(UUID(body['correlation_id']).version, 4)
        self.assertTrue(body['action'])

    @staticmethod
    def _create_application() -> FastAPI:
        application = FastAPI()
        AuthenticationFailureHandler().register(application)
        authenticator = Mock()
        authenticator.authenticate.return_value = None
        application.add_middleware(
            PilotAuthenticationMiddleware,
            authenticator=authenticator,
            cookie_name='mosaic_pilot_session',
        )
        PilotAuthenticationApi(
            PilotAuthenticationConfiguration(),
            authenticator,
        ).register_routes(application)

        @application.get('/protected')
        async def protected() -> dict[str, bool]:
            return {'unexpected_access': True}

        return application
