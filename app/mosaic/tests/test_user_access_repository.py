import hashlib
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.exc import IntegrityError

from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestUserAccessRepository(unittest.TestCase):
    def test_enabled_token_resolves_user_without_storing_plaintext(self) -> None:
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
                with database.create_session() as session:
                    with session.begin():
                        repository = UserAccessRepository(session)
                        repository.add_user('user-example', created_at)
                        token = repository.add_access_token(
                            '00000000-0000-4000-8000-000000000010',
                            'user-example',
                            'opaque-example-token',
                            created_at,
                        )

                    resolved_user = repository.resolve_enabled_user(
                        'opaque-example-token'
                    )
            finally:
                database.dispose()

            self.assertIsNotNone(resolved_user)
            self.assertEqual(resolved_user.user_id, 'user-example')
            self.assertEqual(
                token.token_hash,
                hashlib.sha256(
                    b'opaque-example-token'
                ).hexdigest(),
            )
            self.assertNotEqual(
                token.token_hash,
                'opaque-example-token',
            )

    def test_disabled_and_missing_credentials_do_not_resolve(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            created_at = datetime.now(UTC)
            disabled_at = created_at

            try:
                MosaicDatabaseMigrator(database).upgrade()
                with database.create_session() as session:
                    repository = UserAccessRepository(session)
                    with session.begin():
                        repository.add_user('disabled-user', created_at)
                        repository.add_access_token(
                            '00000000-0000-4000-8000-000000000011',
                            'disabled-user',
                            'disabled-user-token',
                            created_at,
                        )
                        repository.add_user('token-disabled-user', created_at)
                        repository.add_access_token(
                            '00000000-0000-4000-8000-000000000012',
                            'token-disabled-user',
                            'disabled-token',
                            created_at,
                        )
                        repository.disable_user(
                            'disabled-user',
                            disabled_at,
                        )
                        repository.disable_access_token(
                            '00000000-0000-4000-8000-000000000012',
                            disabled_at,
                        )

                    self.assertIsNone(
                        repository.resolve_enabled_user(
                            'disabled-user-token'
                        )
                    )
                    self.assertIsNone(
                        repository.resolve_enabled_user('disabled-token')
                    )
                    self.assertIsNone(
                        repository.resolve_enabled_user('missing-token')
                    )
            finally:
                database.dispose()

    def test_duplicate_user_is_rejected(self) -> None:
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
                with database.create_session() as session:
                    repository = UserAccessRepository(session)
                    with session.begin():
                        repository.add_user('duplicate-user', created_at)

                    with (
                        self.assertRaises(IntegrityError),
                        session.begin(),
                    ):
                        repository.add_user(
                            'duplicate-user',
                            created_at,
                        )
            finally:
                database.dispose()
