import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from mosaic.components.identity.pilot_bearer_authenticator import PilotBearerAuthenticator
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestPilotBearerAuthenticator(unittest.TestCase):
    def test_enabled_token_resolves_immutable_trusted_context(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            created_at = datetime.now(UTC)
            try:
                MosaicDatabaseMigrator(database).upgrade()
                with (
                    database.create_session() as session,
                    session.begin(),
                ):
                    repository = UserAccessRepository(session)
                    repository.add_user('authenticated-user', created_at)
                    repository.add_access_token(
                        '00000000-0000-4000-8000-000000000020',
                        'authenticated-user',
                        'valid-pilot-token',
                        created_at,
                    )

                context = PilotBearerAuthenticator(database).authenticate(
                    'valid-pilot-token'
                )
            finally:
                database.dispose()

        self.assertIsNotNone(context)
        self.assertEqual(context.user_id, 'authenticated-user')
        with self.assertRaisesRegex(ValidationError, 'frozen'):
            context.user_id = 'spoofed-user'

    def test_unavailable_tokens_do_not_resolve_context(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            created_at = datetime.now(UTC)
            try:
                MosaicDatabaseMigrator(database).upgrade()
                with (
                    database.create_session() as session,
                    session.begin(),
                ):
                    repository = UserAccessRepository(session)
                    repository.add_user('disabled-user', created_at)
                    repository.add_access_token(
                        '00000000-0000-4000-8000-000000000021',
                        'disabled-user',
                        'disabled-user-token',
                        created_at,
                    )
                    repository.disable_user(
                        'disabled-user',
                        created_at,
                    )
                    repository.add_user('rotated-user', created_at)
                    rotated_token = repository.add_access_token(
                        '00000000-0000-4000-8000-000000000022',
                        'rotated-user',
                        'rotated-token',
                        created_at,
                    )
                    rotated_token.is_enabled = False
                    rotated_token.rotated_at = created_at

                authenticator = PilotBearerAuthenticator(database)
                results = (
                    authenticator.authenticate('missing-token'),
                    authenticator.authenticate('disabled-user-token'),
                    authenticator.authenticate('rotated-token'),
                )
            finally:
                database.dispose()

        self.assertEqual(results, (None, None, None))
