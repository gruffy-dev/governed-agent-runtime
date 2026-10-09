import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mosaic.components.api.conversation_api_contract import ConversationApiContract
from mosaic.components.api.conversation_api_documentation import ConversationApiDocumentation
from mosaic.components.identity.authentication_failure_handler import AuthenticationFailureHandler
from mosaic.components.identity.pilot_authentication_middleware import PilotAuthenticationMiddleware
from mosaic.components.identity.trusted_request_context_dependency import TrustedRequestContextDependency
from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration
from mosaic.models.identity.trusted_request_configuration import TrustedRequestConfiguration
from mosaic.models.identity.trusted_user_context import TrustedUserContext


class TestConversationApiDocumentation(unittest.TestCase):
    def test_bearer_and_cookie_can_read_isolated_contract(self) -> None:
        application = self._create_application(authenticated=True)
        with TestClient(application) as client:
            anonymous = client.get('/api/v1/openapi.json')
            bearer = client.get(
                '/api/v1/openapi.json',
                headers={'Authorization': 'Bearer synthetic-token'},
            )
            client.cookies.set('mosaic_pilot_session', 'synthetic-token')
            cookie = client.get('/api/v1/openapi.json')
            planned_route = client.get('/api/v1/conversations')
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(bearer.status_code, 200)
        self.assertEqual(bearer.headers['Cache-Control'], 'no-store')
        self.assertEqual(bearer.json(), cookie.json())
        self.assertNotIn('/openapi.json', bearer.json()['paths'])
        self.assertEqual(planned_route.status_code, 404)

    def test_trusted_dependency_rejects_claims_without_middleware(self) -> None:
        application = self._create_application(authenticated=False)
        with TestClient(application) as client:
            response = client.get(
                '/api/v1/openapi.json',
                params={'user_id': 'claimed-user'},
                headers={
                    'Authorization': 'Bearer synthetic-token',
                    'X-User-ID': 'claimed-user',
                },
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['error_code'], 'unauthorized')

    @staticmethod
    def _create_application(*, authenticated: bool) -> FastAPI:
        application = FastAPI()
        AuthenticationFailureHandler().register(application)
        ConversationApiDocumentation(
            ConversationApiContract(PilotAuthenticationConfiguration()),
            TrustedRequestContextDependency(
                TrustedRequestConfiguration(app_name='mosaic')
            ),
        ).register_routes(application)
        if authenticated:
            authenticator = Mock()
            authenticator.authenticate.side_effect = lambda token: (
                TrustedUserContext(user_id='authenticated-user')
                if token == 'synthetic-token'
                else None
            )
            application.add_middleware(
                PilotAuthenticationMiddleware,
                authenticator=authenticator,
                cookie_name='mosaic_pilot_session',
            )
        return application
