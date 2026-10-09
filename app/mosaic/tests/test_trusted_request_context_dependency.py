import asyncio
import unittest
from typing import Annotated
from unittest.mock import Mock

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mosaic.components.identity.authentication_failure_handler import AuthenticationFailureHandler
from mosaic.components.identity.pilot_authentication_middleware import PilotAuthenticationMiddleware
from mosaic.components.identity.trusted_request_context_dependency import TrustedRequestContextDependency
from mosaic.models.identity.trusted_request_configuration import TrustedRequestConfiguration
from mosaic.models.identity.trusted_request_context import TrustedRequestContext
from mosaic.models.identity.trusted_user_context import TrustedUserContext


class TestTrustedRequestContextDependency(unittest.TestCase):
    def test_bearer_and_cookie_resolve_the_same_server_owned_identity(
        self,
    ) -> None:
        application = self._create_application(authenticated=True)

        with TestClient(application) as client:
            bearer_response = client.post(
                '/api/v1/identity/claimed-user',
                headers={'Authorization': 'Bearer synthetic-test-token'},
                json={},
            )
            client.cookies.set(
                'mosaic_pilot_session',
                'synthetic-test-token',
            )
            cookie_response = client.post(
                '/api/v1/identity/claimed-user',
                json={},
            )

        for response in (bearer_response, cookie_response):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    'app_name': 'configured-application',
                    'user_id': 'authenticated-user',
                },
            )

    def test_body_query_path_and_header_claims_cannot_change_identity(
        self,
    ) -> None:
        application = self._create_application(authenticated=True)
        claims = {
            'app_name': 'claimed-application',
            'user_id': 'claimed-user',
            'workspace_id': 'claimed-workspace',
            'owner_id': 'claimed-owner',
        }

        with (
            TestClient(application) as client,
            self.assertLogs('mosaic.identity', level='INFO') as audit,
        ):
            response = client.post(
                '/api/v1/identity/another-user',
                params=claims,
                headers={
                    'Authorization': 'Bearer synthetic-test-token',
                    'X-App-Name': 'header-application',
                    'X-User-ID': 'header-user',
                    'X-Workspace-ID': 'header-workspace',
                    'X-Owner-ID': 'header-owner',
                },
                json={**claims, 'state': claims},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'app_name': 'configured-application',
                'user_id': 'authenticated-user',
            },
        )
        self.assertEqual(len(audit.records), 1)
        self.assertEqual(audit.records[0].user_id, 'authenticated-user')
        self.assertEqual(audit.records[0].app_name, 'configured-application')
        self.assertEqual(audit.records[0].mosaic_event, 'trusted_identity_resolved')
        logged = '\n'.join(audit.output)
        for untrusted_value in (
            'synthetic-test-token',
            'claimed-user',
            'header-user',
            'claimed-workspace',
        ):
            self.assertNotIn(untrusted_value, logged)

    def test_dependency_rejects_missing_context_without_middleware(
        self,
    ) -> None:
        application = self._create_application(authenticated=False)

        with TestClient(application) as client:
            response = client.post(
                '/api/v1/identity/claimed-user',
                headers={
                    'Authorization': 'Bearer synthetic-test-token',
                    'X-User-ID': 'claimed-user',
                },
                json={'user_id': 'claimed-user'},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['detail'], 'Unauthorized')
        self.assertEqual(response.json()['error_code'], 'unauthorized')
        self.assertEqual(response.headers['WWW-Authenticate'], 'Bearer')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_dependency_rejects_unvalidated_context(self) -> None:
        dependency = TrustedRequestContextDependency(
            TrustedRequestConfiguration(app_name='configured-application')
        )
        for invalid_context in (
            None,
            {'user_id': 'claimed-user'},
            'claimed-user',
        ):
            with self.subTest(context=invalid_context):
                request = Request(
                    {
                        'type': 'http',
                        'state': {'trusted_user_context': invalid_context},
                    }
                )
                with self.assertRaises(HTTPException) as raised:
                    asyncio.run(dependency(request))

                self.assertEqual(raised.exception.status_code, 401)
                self.assertEqual(raised.exception.detail, 'Unauthorized')

    def test_resolved_context_is_immutable(self) -> None:
        context = TrustedRequestContext(
            app_name='configured-application',
            user_id='authenticated-user',
        )

        with self.assertRaises(ValidationError):
            context.user_id = 'claimed-user'

    @staticmethod
    def _create_application(*, authenticated: bool) -> FastAPI:
        application = FastAPI()
        AuthenticationFailureHandler().register(application)
        dependency = TrustedRequestContextDependency(
            TrustedRequestConfiguration(app_name='configured-application')
        )

        @application.post('/api/v1/identity/{claimed_user_id}')
        async def identity(
            claimed_user_id: str,
            context: Annotated[
                TrustedRequestContext,
                Depends(dependency),
            ],
        ) -> TrustedRequestContext:
            return context

        if authenticated:
            authenticator = Mock()
            authenticator.authenticate.return_value = TrustedUserContext(
                user_id='authenticated-user'
            )
            application.add_middleware(
                PilotAuthenticationMiddleware,
                authenticator=authenticator,
                cookie_name='mosaic_pilot_session',
            )
        return application
