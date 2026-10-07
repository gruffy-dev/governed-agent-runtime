import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pydantic import ValidationError

from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestMosaicDatabaseConfiguration(unittest.TestCase):
    def test_local_defaults_are_applied(self) -> None:
        with patch.dict('os.environ', {}, clear=True):
            configuration = MosaicDatabaseConfiguration()

        self.assertEqual(
            configuration.database_path,
            Path('app/mosaic/.adk/mosaic.db'),
        )
        self.assertEqual(configuration.busy_timeout_seconds, 5)
        self.assertEqual(configuration.storage_mode, 'local')
        self.assertEqual(configuration.journal_mode, 'DELETE')
        self.assertEqual(configuration.synchronous_mode, 'FULL')
        self.assertTrue(configuration.resolved_database_path.is_absolute())

    def test_local_database_is_next_to_ada_session_database(self) -> None:
        with patch.dict('os.environ', {}, clear=True):
            configuration = MosaicDatabaseConfiguration()

        self.assertEqual(
            configuration.database_path.parent / 'session.db',
            Path('app/mosaic/.adk/session.db'),
        )

    def test_mounted_database_path_is_applied(self) -> None:
        configured_path = '/mnt/persistent/mosaic.db'

        with patch.dict(
            'os.environ',
            {
                'MOSAIC_DATABASE_PATH': configured_path,
                'MOSAIC_DATABASE_STORAGE_MODE': 'mounted',
            },
            clear=True,
        ):
            configuration = MosaicDatabaseConfiguration()

        self.assertEqual(
            configuration.resolved_database_path,
            Path(configured_path),
        )

    def test_local_parent_directory_is_created(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = (
                Path(temporary_directory) / 'nested' / 'mosaic.db'
            )
            configuration = MosaicDatabaseConfiguration(
                database_path=database_path,
                storage_mode='local',
            )

            prepared_path = configuration.prepare_database_path()

            self.assertEqual(prepared_path, database_path.resolve())
            self.assertTrue(database_path.parent.is_dir())

    def test_relative_mounted_database_path_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            MosaicDatabaseConfiguration(
                database_path=Path('mounted/mosaic.db'),
                storage_mode='mounted',
            )

    def test_missing_mounted_parent_directory_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = (
                Path(temporary_directory) / 'missing' / 'mosaic.db'
            )
            configuration = MosaicDatabaseConfiguration(
                database_path=database_path,
                storage_mode='mounted',
            )

            with self.assertRaises(FileNotFoundError):
                configuration.prepare_database_path()

    def test_unwritable_mounted_parent_directory_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / 'mosaic.db'
            configuration = MosaicDatabaseConfiguration(
                database_path=database_path,
                storage_mode='mounted',
            )

            with (
                patch(
                    'mosaic.models.mosaic_database_configuration.os.access',
                    return_value=False,
                ),
                self.assertRaises(PermissionError),
            ):
                configuration.prepare_database_path()

    def test_busy_timeout_is_configurable(self) -> None:
        with patch.dict(
            'os.environ',
            {'MOSAIC_DATABASE_BUSY_TIMEOUT_SECONDS': '10'},
            clear=True,
        ):
            configuration = MosaicDatabaseConfiguration()

        self.assertEqual(configuration.busy_timeout_seconds, 10)

    def test_ada_session_database_name_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            MosaicDatabaseConfiguration(database_path=Path('session.db'))

    def test_non_positive_busy_timeout_is_rejected(self) -> None:
        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_DATABASE_BUSY_TIMEOUT_SECONDS': '0'},
                clear=True,
            ),
            self.assertRaises(ValueError),
        ):
            MosaicDatabaseConfiguration()

    def test_unsupported_sqlite_modes_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            MosaicDatabaseConfiguration(
                journal_mode='WAL',
                synchronous_mode='NORMAL',
            )
