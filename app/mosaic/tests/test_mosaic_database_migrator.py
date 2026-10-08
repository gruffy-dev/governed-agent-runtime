import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestMosaicDatabaseMigrator(unittest.TestCase):
    def test_upgrade_reaches_current_schema_and_is_idempotent(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            migrator = MosaicDatabaseMigrator(database)

            try:
                migrator.upgrade()
                migrator.upgrade()
                with database.engine.connect() as connection:
                    revision = connection.exec_driver_sql(
                        'SELECT version_num FROM alembic_version'
                    ).scalar_one()
            finally:
                database.dispose()

            self.assertEqual(revision, '0003_workspace_skills')

    def test_upgrade_failure_is_propagated(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            migrator = MosaicDatabaseMigrator(database)

            try:
                with (
                    patch(
                        'mosaic.components.persistence.'
                        'mosaic_database_migrator.command.upgrade',
                        side_effect=RuntimeError('migration failed'),
                    ),
                    self.assertRaisesRegex(
                        RuntimeError,
                        'migration failed',
                    ),
                ):
                    migrator.upgrade()
            finally:
                database.dispose()
