import base64
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mosaic.components.identity.pilot_administration_api import PilotAdministrationApi
from mosaic.components.identity.pilot_user_administration_service import PilotUserAdministrationService
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestPilotAdministrationApi(unittest.TestCase):
    def test_disabled_configuration_registers_no_routes(self) -> None:
        application = FastAPI()
        service = Mock()
        PilotAdministrationApi(
            PilotAdministrationConfiguration(enabled=False),
            service,
        ).register_routes(application)

        with TestClient(application) as client:
            response = client.get('/api/v1/admin/users')

        self.assertEqual(response.status_code, 404)
        service.list_users.assert_not_called()

    def test_admin_routes_provision_list_and_disable_user(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            MosaicDatabaseMigrator(database).upgrade()
            application = FastAPI()
            secret = 'synthetic-administrator-secret-value'
            PilotAdministrationApi(
                PilotAdministrationConfiguration(
                    enabled=True,
                    administrator_secret=SecretStr(secret),
                ),
                PilotUserAdministrationService(database),
            ).register_routes(application)

            try:
                with TestClient(application) as client:
                    denied_missing = client.get('/api/v1/admin/users')
                    denied_invalid = client.get(
                        '/api/v1/admin/users',
                        headers={'Authorization': 'Bearer invalid'},
                    )
                    created = client.post(
                        '/api/v1/admin/users',
                        headers={'Authorization': f'Bearer {secret}'},
                        json={'user_id': 'pilot-user'},
                    )
                    listed = client.get(
                        '/api/v1/admin/users',
                        headers={'Authorization': f'Bearer {secret}'},
                    )
                    disabled = client.post(
                        '/api/v1/admin/users/pilot-user/disable',
                        headers={'Authorization': f'Bearer {secret}'},
                    )
                    openapi = client.get('/openapi.json')

                plaintext_token = created.json()['plaintext_token']
                encoded_random_bytes = plaintext_token.removeprefix(
                    'mosaic_r1_'
                )
                padded_token = encoded_random_bytes + '=' * (
                    -len(encoded_random_bytes) % 4
                )
                with database.create_session() as session:
                    resolved_user = UserAccessRepository(
                        session
                    ).resolve_enabled_user(plaintext_token)
            finally:
                database.dispose()

        self.assertEqual(denied_missing.status_code, 403)
        self.assertEqual(denied_invalid.status_code, 403)
        self.assertEqual(denied_missing.json(), denied_invalid.json())
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.headers['Cache-Control'], 'no-store')
        self.assertEqual(
            len(base64.urlsafe_b64decode(padded_token)),
            32,
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)
        self.assertNotIn('token', listed.text.lower())
        self.assertEqual(disabled.status_code, 204)
        self.assertIsNone(resolved_user)
        self.assertNotIn('/api/v1/admin/users', openapi.json()['paths'])

    def test_duplicate_user_returns_generic_conflict(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            MosaicDatabaseMigrator(database).upgrade()
            application = FastAPI()
            secret = 'synthetic-administrator-secret-value'
            PilotAdministrationApi(
                PilotAdministrationConfiguration(
                    enabled=True,
                    administrator_secret=SecretStr(secret),
                ),
                PilotUserAdministrationService(database),
            ).register_routes(application)

            try:
                with TestClient(application) as client:
                    headers = {
                        'Authorization': f'Bearer {secret}',
                    }
                    client.post(
                        '/api/v1/admin/users',
                        headers=headers,
                        json={'user_id': 'duplicate-user'},
                    )
                    duplicate = client.post(
                        '/api/v1/admin/users',
                        headers=headers,
                        json={'user_id': 'duplicate-user'},
                    )
            finally:
                database.dispose()

        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(duplicate.json(), {'detail': 'Conflict'})
