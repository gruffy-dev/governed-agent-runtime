import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestWorkspaceSchemaMigration(unittest.TestCase):
    def test_upgrade_creates_workspace_schema(self) -> None:
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
                workspace_columns = {
                    column['name']
                    for column in inspector.get_columns('workspaces')
                }
                skill_columns = {
                    column['name']
                    for column in inspector.get_columns('workspace_skills')
                }
                workspace_unique_constraints = {
                    constraint['name']
                    for constraint in inspector.get_unique_constraints(
                        'workspaces'
                    )
                }
                skill_primary_key = inspector.get_pk_constraint(
                    'workspace_skills'
                )
            finally:
                database.dispose()

            self.assertTrue(
                {'workspaces', 'workspace_skills'} <= table_names
            )
            self.assertEqual(
                workspace_columns,
                {
                    'workspace_id',
                    'user_id',
                    'version',
                    'created_at',
                    'updated_at',
                },
            )
            self.assertEqual(
                skill_columns,
                {'workspace_id', 'skill_id'},
            )
            self.assertEqual(
                workspace_unique_constraints,
                {'uq_workspaces_user_id'},
            )
            self.assertEqual(
                skill_primary_key['constrained_columns'],
                ['workspace_id', 'skill_id'],
            )

    def test_one_workspace_and_unique_skill_references_are_enforced(self) -> None:
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
                        "(user_id, is_enabled, created_at, disabled_at) "
                        "VALUES ('workspace-user', TRUE, "
                        "CURRENT_TIMESTAMP, NULL)"
                    )
                    connection.exec_driver_sql(
                        "INSERT INTO workspaces "
                        "(workspace_id, user_id, version, created_at, "
                        "updated_at) VALUES "
                        "('00000000-0000-4000-8000-000000000020', "
                        "'workspace-user', 1, CURRENT_TIMESTAMP, "
                        "CURRENT_TIMESTAMP)"
                    )
                    skill_count = connection.exec_driver_sql(
                        "SELECT COUNT(*) FROM workspace_skills"
                    ).scalar_one()
                    connection.exec_driver_sql(
                        "INSERT INTO workspace_skills "
                        "(workspace_id, skill_id) VALUES "
                        "('00000000-0000-4000-8000-000000000020', "
                        "'example-skill')"
                    )

                with (
                    self.assertRaises(IntegrityError),
                    database.engine.begin() as connection,
                ):
                    connection.exec_driver_sql(
                        "INSERT INTO workspaces "
                        "(workspace_id, user_id, version, created_at, "
                        "updated_at) VALUES "
                        "('00000000-0000-4000-8000-000000000021', "
                        "'workspace-user', 1, CURRENT_TIMESTAMP, "
                        "CURRENT_TIMESTAMP)"
                    )

                with (
                    self.assertRaises(IntegrityError),
                    database.engine.begin() as connection,
                ):
                    connection.exec_driver_sql(
                        "INSERT INTO workspace_skills "
                        "(workspace_id, skill_id) VALUES "
                        "('00000000-0000-4000-8000-000000000020', "
                        "'example-skill')"
                    )
            finally:
                database.dispose()

            self.assertEqual(skill_count, 0)
