import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI
from fastapi.testclient import TestClient

from mosaic.backend import Backend
from mosaic.components.identity.pilot_user_administration_service import PilotUserAdministrationService
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.models.identity.browser_access_configuration import BrowserAccessConfiguration
from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestBrowserOriginMiddleware(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.configuration = MosaicDatabaseConfiguration(
            database_path=Path(self.directory.name) / 'mosaic.db'
        )
        self.origin = 'http://127.0.0.1:8050'
        application = Backend.create_application(
            ada_app_factory=FastAPI,
            database_configuration=self.configuration,
            pilot_administration_configuration=PilotAdministrationConfiguration(
                enabled=False
            ),
            pilot_authentication_configuration=PilotAuthenticationConfiguration(
                mode='local', secure_cookie=False
            ),
            browser_access_configuration=BrowserAccessConfiguration(
                allowed_origins=(self.origin,)
            ),
        )
        self.database = MosaicDatabase(self.configuration)
        self.addCleanup(self.database.dispose)
        user = PilotUserAdministrationService(self.database).create_user(
            'synthetic-browser-user'
        )
        self.token = user.plaintext_token.get_secret_value()
        self.client_stack = ExitStack()
        self.addCleanup(self.client_stack.close)
        self.client = self.client_stack.enter_context(TestClient(application))

    def test_preflight_requires_no_credential_but_only_approved_method_and_headers(
        self,
    ) -> None:
        headers = {
            'Origin': self.origin,
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type',
        }
        response = self.client.options('/api/v1/auth/token', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['access-control-allow-origin'], self.origin)
        self.assertEqual(response.headers['access-control-allow-credentials'], 'true')
        job_preflight = self.client.options(
            '/api/v1/conversations/synthetic-conversation/jobs',
            headers={**headers, 'Access-Control-Request-Headers': 'content-type,idempotency-key'},
        )
        self.assertEqual(job_preflight.status_code, 200)
        for replacement in (
            {'Origin': 'https://untrusted.example.com'},
            {'Access-Control-Request-Method': 'DELETE'},
            {'Access-Control-Request-Headers': 'X-Admin-Secret'},
        ):
            self.assertEqual(
                self.client.options(
                    '/api/v1/auth/token', headers={**headers, **replacement}
                ).status_code,
                400,
            )

    def test_allowed_origin_still_requires_authentication_and_exposes_error_correlation(
        self,
    ) -> None:
        response = self.client.get('/api/v1/workspace', headers={'Origin': self.origin})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers['access-control-allow-origin'], self.origin)
        self.assertIn(
            'X-Correlation-ID', response.headers['access-control-expose-headers']
        )
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_browser_cookie_sign_in_read_and_sign_out(self) -> None:
        headers = {'Origin': self.origin}
        response = self.client.post(
            '/api/v1/auth/token', headers=headers, json={'token': self.token}
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers['access-control-allow-origin'], self.origin)
        cookie = response.headers['set-cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=strict', cookie)
        self.assertNotIn('Domain=', cookie)
        response = self.client.get('/api/v1/workspace', headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user_id'], 'synthetic-browser-user')
        self.assertEqual(
            self.client.post('/api/v1/auth/logout', headers=headers).status_code, 204
        )
        self.assertEqual(
            self.client.get('/api/v1/workspace', headers=headers).status_code, 401
        )

    def test_unapproved_null_and_duplicate_origins_cannot_sign_in(self) -> None:
        for origin in (
            'https://untrusted.example.com',
            'null',
            'http://localhost:8050',
            self.origin + '.untrusted.example.com',
        ):
            response = self.client.post(
                '/api/v1/auth/token',
                headers={'Origin': origin},
                json={'token': self.token},
            )
            self.assertEqual(response.status_code, 403)
            self.assertNotIn('set-cookie', response.headers)
            self.assertNotIn('access-control-allow-origin', response.headers)
        response = self.client.post(
            '/api/v1/auth/token',
            headers=[
                ('Origin', self.origin),
                ('Origin', 'https://untrusted.example.com'),
            ],
            json={'token': self.token},
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('set-cookie', response.headers)

    def test_cookie_writes_require_origin_and_rejection_does_not_clear_cookie(
        self,
    ) -> None:
        self.assertEqual(
            self.client.post(
                '/api/v1/auth/token', json={'token': self.token}
            ).status_code,
            204,
        )
        for headers in ({}, {'Origin': 'https://untrusted.example.com'}):
            response = self.client.post('/api/v1/auth/logout', headers=headers)
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()['error_code'], 'forbidden')
            self.assertNotIn('set-cookie', response.headers)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(
                self.client.post(
                    '/api/v1/conversations', headers=headers, json={}
                ).status_code,
                403,
            )
        self.assertEqual(self.client.get('/api/v1/workspace').status_code, 200)

    def test_originless_bearer_calls_and_empty_default_allowlist(self) -> None:
        self.assertEqual(
            self.client.get(
                '/api/v1/workspace', headers={'Authorization': f'Bearer {self.token}'}
            ).status_code,
            200,
        )
        self.client_stack.close()
        application = Backend.create_application(
            ada_app_factory=FastAPI,
            database_configuration=self.configuration,
            pilot_administration_configuration=PilotAdministrationConfiguration(
                enabled=False
            ),
            browser_access_configuration=BrowserAccessConfiguration(allowed_origins=()),
        )
        with TestClient(application) as client:
            self.assertEqual(
                client.get(
                    '/api/v1/workspace',
                    headers={'Authorization': f'Bearer {self.token}'},
                ).status_code,
                200,
            )
            self.assertEqual(
                client.post(
                    '/api/v1/auth/token',
                    headers={'Origin': self.origin},
                    json={'token': self.token},
                ).status_code,
                403,
            )
