import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select

from mosaic.components.persistence.access_token_record import AccessTokenRecord
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.user_record import UserRecord
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestUserAccessRecords(unittest.TestCase):
    def test_records_match_migrated_table_columns(self) -> None:
        self.assertEqual(
            set(UserRecord.__table__.columns.keys()),
            {'user_id', 'is_enabled', 'created_at', 'disabled_at'},
        )
        self.assertEqual(
            set(AccessTokenRecord.__table__.columns.keys()),
            {
                'token_id',
                'user_id',
                'token_hash',
                'is_enabled',
                'created_at',
                'disabled_at',
                'rotated_at',
            },
        )
        self.assertNotIn('token', AccessTokenRecord.__table__.columns)

    def test_records_persist_without_plaintext_token_material(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            created_at = datetime.now(UTC)
            user = UserRecord(
                user_id='user-example',
                is_enabled=True,
                created_at=created_at,
                disabled_at=None,
            )
            token = AccessTokenRecord(
                token_id='00000000-0000-4000-8000-000000000004',
                user_id=user.user_id,
                token_hash=(
                    'cccccccccccccccccccccccccccccccc'
                    'cccccccccccccccccccccccccccccccc'
                ),
                is_enabled=True,
                created_at=created_at,
                disabled_at=None,
                rotated_at=None,
            )

            try:
                MosaicDatabaseMigrator(database).upgrade()
                with database.create_session() as session:
                    session.add(user)
                    session.flush()
                    session.add(token)
                    session.commit()
                    stored_token = session.scalar(
                        select(AccessTokenRecord).where(
                            AccessTokenRecord.token_id == token.token_id
                        )
                    )
            finally:
                database.dispose()

            self.assertIsNotNone(stored_token)
            self.assertEqual(stored_token.user_id, 'user-example')
            self.assertTrue(stored_token.is_enabled)
            self.assertEqual(stored_token.token_hash, token.token_hash)
