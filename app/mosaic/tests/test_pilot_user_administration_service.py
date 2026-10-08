import base64
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from mosaic.components.identity.pilot_user_administration_service import PilotUserAdministrationService
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.components.persistence.workspace_service import WorkspaceService
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestPilotUserAdministrationService(unittest.TestCase):
    def test_create_user_provisions_token_and_empty_workspace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            service = PilotUserAdministrationService(database)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                credential = service.create_user('pilot-user')
                plaintext_token = (
                    credential.plaintext_token.get_secret_value()
                )
                with database.create_session() as session:
                    resolved_user = UserAccessRepository(
                        session
                    ).resolve_enabled_user(plaintext_token)
                    workspace = WorkspaceService(session).get_for_user(
                        'pilot-user'
                    )
            finally:
                database.dispose()

            padded_token = plaintext_token + '=' * (
                -len(plaintext_token) % 4
            )
            random_bytes = base64.urlsafe_b64decode(padded_token)
            self.assertEqual(len(random_bytes), 32)
            self.assertEqual(str(UUID(credential.token_id)), credential.token_id)
            self.assertIsNotNone(resolved_user)
            self.assertIsNotNone(workspace)
            self.assertEqual(workspace.skill_ids, ())

    def test_duplicate_user_rolls_back_without_extra_workspace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            service = PilotUserAdministrationService(database)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                service.create_user('duplicate-pilot-user')
                with self.assertRaises(IntegrityError):
                    service.create_user('duplicate-pilot-user')
                users = service.list_users()
                with database.create_session() as session:
                    workspace = WorkspaceService(session).get_for_user(
                        'duplicate-pilot-user'
                    )
            finally:
                database.dispose()

            self.assertEqual(len(users), 1)
            self.assertIsNotNone(workspace)

    def test_list_and_disable_do_not_expose_token_material(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            service = PilotUserAdministrationService(database)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                credential = service.create_user('disable-pilot-user')
                self.assertTrue(service.disable_user('disable-pilot-user'))
                users = service.list_users()
                with database.create_session() as session:
                    resolved_user = UserAccessRepository(
                        session
                    ).resolve_enabled_user(
                        credential.plaintext_token.get_secret_value()
                    )
            finally:
                database.dispose()

            self.assertEqual(len(users), 1)
            self.assertFalse(users[0].is_enabled)
            self.assertIsNotNone(users[0].disabled_at)
            self.assertNotIn('token', users[0].model_dump())
            self.assertIsNone(resolved_user)

    def test_token_generation_requests_32_random_bytes(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            service = PilotUserAdministrationService(database)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                with patch(
                    'mosaic.components.identity.'
                    'pilot_user_administration_service.token_urlsafe',
                    return_value='synthetic-pilot-token',
                ) as token_generator:
                    credential = service.create_user('entropy-pilot-user')
            finally:
                database.dispose()

            token_generator.assert_called_once_with(32)
            self.assertEqual(
                credential.plaintext_token.get_secret_value(),
                'synthetic-pilot-token',
            )
