import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text

from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestMosaicDatabase(unittest.TestCase):
    def test_connection_uses_required_sqlite_settings(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / 'mosaic.db'
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(database_path=database_path)
            )

            try:
                with database.engine.connect() as connection:
                    foreign_keys = connection.exec_driver_sql(
                        'PRAGMA foreign_keys'
                    ).scalar_one()
                    journal_mode = connection.exec_driver_sql(
                        'PRAGMA journal_mode'
                    ).scalar_one()
                    synchronous_mode = connection.exec_driver_sql(
                        'PRAGMA synchronous'
                    ).scalar_one()
                    busy_timeout = connection.exec_driver_sql(
                        'PRAGMA busy_timeout'
                    ).scalar_one()
            finally:
                database.dispose()

            self.assertEqual(foreign_keys, 1)
            self.assertEqual(journal_mode, 'delete')
            self.assertEqual(synchronous_mode, 2)
            self.assertEqual(busy_timeout, 5000)
            self.assertTrue(database_path.is_file())

    def test_session_executes_against_mosaic_database(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / 'mosaic.db'
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(database_path=database_path)
            )

            try:
                with database.create_session() as session:
                    result = session.execute(text('SELECT 1')).scalar_one()
            finally:
                database.dispose()

            self.assertEqual(result, 1)
            self.assertTrue(database_path.is_file())
            self.assertFalse(
                (Path(temporary_directory) / 'session.db').exists()
            )
