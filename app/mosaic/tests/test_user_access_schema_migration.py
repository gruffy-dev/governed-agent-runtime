import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestUserAccessSchemaMigration(unittest.TestCase):
    def test_upgrade_creates_user_and_access_token_schema(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )

            try:
                MosaicDatabaseMigrator(database).upgrade()
                inspector = inspect(database.engine)
                table_names = set(inspector.get_table_names())
                user_columns = {
                    column['name']
                    for column in inspector.get_columns('users')
                }
                token_columns = {
                    column['name']
                    for column in inspector.get_columns('access_tokens')
                }
                user_primary_key = inspector.get_pk_constraint('users')
                token_primary_key = inspector.get_pk_constraint(
                    'access_tokens'
                )
                user_constraints = {
                    constraint['name']
                    for constraint in inspector.get_check_constraints(
                        'users'
                    )
                }
                token_constraints = {
                    constraint['name']
                    for constraint in inspector.get_check_constraints(
                        'access_tokens'
                    )
                }
                foreign_keys = inspector.get_foreign_keys('access_tokens')
                indexes = {
                    index['name']: index
                    for index in inspector.get_indexes('access_tokens')
                }
            finally:
                database.dispose()

            self.assertTrue(
                {'alembic_version', 'users', 'access_tokens'}
                <= table_names
            )
            self.assertEqual(
                user_columns,
                {'user_id', 'status', 'created_at', 'disabled_at'},
            )
            self.assertEqual(
                token_columns,
                {
                    'token_id',
                    'user_id',
                    'token_hash',
                    'status',
                    'created_at',
                    'disabled_at',
                    'rotated_at',
                },
            )
            self.assertEqual(user_primary_key['name'], 'pk_users')
            self.assertEqual(
                user_primary_key['constrained_columns'],
                ['user_id'],
            )
            self.assertEqual(
                token_primary_key['name'],
                'pk_access_tokens',
            )
            self.assertEqual(
                token_primary_key['constrained_columns'],
                ['token_id'],
            )
            self.assertEqual(
                user_constraints,
                {
                    'ck_users_status',
                    'ck_users_status_timestamp',
                    'ck_users_user_id_length',
                },
            )
            self.assertEqual(
                token_constraints,
                {
                    'ck_access_tokens_status',
                    'ck_access_tokens_status_timestamp',
                    'ck_access_tokens_token_hash_length',
                    'ck_access_tokens_token_id_length',
                },
            )
            self.assertEqual(len(foreign_keys), 1)
            self.assertEqual(
                foreign_keys[0]['referred_table'],
                'users',
            )
            self.assertTrue(indexes['ix_access_tokens_token_hash']['unique'])
            self.assertEqual(
                indexes['ix_access_tokens_user_id_status']['column_names'],
                ['user_id', 'status'],
            )

    def test_foreign_key_and_unique_token_hash_are_enforced(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )

            try:
                MosaicDatabaseMigrator(database).upgrade()
                with database.engine.begin() as connection:
                    connection.exec_driver_sql(
                        "INSERT INTO users "
                        "(user_id, status, created_at, disabled_at) "
                        "VALUES ('user-example', 'enabled', "
                        "CURRENT_TIMESTAMP, NULL)"
                    )
                    connection.exec_driver_sql(
                        "INSERT INTO access_tokens "
                        "(token_id, user_id, token_hash, status, "
                        "created_at, disabled_at, rotated_at) VALUES "
                        "('00000000-0000-4000-8000-000000000001', "
                        "'user-example', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'active', "
                        "CURRENT_TIMESTAMP, NULL, NULL)"
                    )

                with (
                    self.assertRaises(IntegrityError),
                    database.engine.begin() as connection,
                ):
                    connection.exec_driver_sql(
                        "INSERT INTO access_tokens "
                        "(token_id, user_id, token_hash, status, "
                        "created_at, disabled_at, rotated_at) VALUES "
                        "('00000000-0000-4000-8000-000000000002', "
                        "'missing-user', "
                        "'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
                        "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', "
                        "'active', CURRENT_TIMESTAMP, NULL, NULL)"
                    )

                with (
                    self.assertRaises(IntegrityError),
                    database.engine.begin() as connection,
                ):
                    connection.exec_driver_sql(
                        "INSERT INTO access_tokens "
                        "(token_id, user_id, token_hash, status, "
                        "created_at, disabled_at, rotated_at) VALUES "
                        "('00000000-0000-4000-8000-000000000003', "
                        "'user-example', "
                        "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', "
                        "'active', CURRENT_TIMESTAMP, NULL, NULL)"
                    )
            finally:
                database.dispose()
