import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mosaic.components.identity.pilot_authentication_api import PilotAuthenticationApi
from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration
from mosaic.models.identity.trusted_user_context import TrustedUserContext


class TestPilotAuthenticationApi(unittest.TestCase):
    def test_valid_token_sets_protected_production_cookie(self) -> None:
        application = FastAPI()
        authenticator = Mock()
        authenticator.authenticate.return_value = TrustedUserContext(
            user_id='browser-user'
        )
        PilotAuthenticationApi(
            PilotAuthenticationConfiguration(),
            authenticator,
        ).register_routes(application)

        with TestClient(application) as client:
            response = client.post(
                '/api/v1/auth/token',
                json={'token': 'valid-browser-token'},
            )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        cookie_header = response.headers['Set-Cookie']
        self.assertIn(
            'mosaic_pilot_session=valid-browser-token',
            cookie_header,
        )
        self.assertIn('HttpOnly', cookie_header)
        self.assertIn('Max-Age=604800', cookie_header)
        self.assertIn('Path=/', cookie_header)
        self.assertIn('SameSite=strict', cookie_header)
        self.assertIn('Secure', cookie_header)
        authenticator.authenticate.assert_called_once_with(
            'valid-browser-token'
        )

    def test_invalid_token_returns_generic_unauthorized_response(self) -> None:
        application = FastAPI()
        authenticator = Mock()
        authenticator.authenticate.return_value = None
        PilotAuthenticationApi(
            PilotAuthenticationConfiguration(),
            authenticator,
        ).register_routes(application)

        with TestClient(application) as client:
            response = client.post(
                '/api/v1/auth/token',
                json={'token': 'invalid-browser-token'},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {'detail': 'Unauthorized'})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(
            response.headers['WWW-Authenticate'],
            'Bearer',
        )
        self.assertNotIn('Set-Cookie', response.headers)

    def test_logout_expires_cookie_without_validating_it(self) -> None:
        application = FastAPI()
        authenticator = Mock()
        PilotAuthenticationApi(
            PilotAuthenticationConfiguration(),
            authenticator,
        ).register_routes(application)

        with TestClient(application) as client:
            response = client.post('/api/v1/auth/logout')

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        cookie_header = response.headers['Set-Cookie']
        self.assertIn('mosaic_pilot_session=""', cookie_header)
        self.assertIn('Max-Age=0', cookie_header)
        self.assertIn('HttpOnly', cookie_header)
        self.assertIn('SameSite=strict', cookie_header)
        self.assertIn('Secure', cookie_header)
        authenticator.authenticate.assert_not_called()
