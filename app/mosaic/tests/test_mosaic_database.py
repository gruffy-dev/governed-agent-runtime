import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import text

from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestMosaicDatabase(unittest.TestCase):
    def test_job_runtime_lock_is_released_after_process_is_killed(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            database_path = directory / 'mosaic.db'
            ready = directory / 'worker-ready'
            database = MosaicDatabase(MosaicDatabaseConfiguration(database_path=database_path))
            self.addCleanup(database.dispose)
            script = """
import sys
from pathlib import Path
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration

database = MosaicDatabase(MosaicDatabaseConfiguration(database_path=Path(sys.argv[1])))
with database.exclusive_job_runtime():
    Path(sys.argv[2]).touch()
    sys.stdin.read(1)
"""
            environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2])}
            with subprocess.Popen(
                [sys.executable, '-c', script, str(database_path), str(ready)],
                env=environment, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
            ) as worker:
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists():
                        if worker.poll() is not None:
                            self.fail(worker.stderr.read().decode(errors='replace'))
                        if time.monotonic() >= deadline:
                            self.fail('The lock holder did not start.')
                        time.sleep(0.02)
                    with self.assertRaisesRegex(RuntimeError, 'already owns'), database.exclusive_job_runtime():
                        self.fail('Two processes acquired the same lock.')
                finally:
                    if worker.poll() is None:
                        worker.kill()
                    worker.wait(timeout=5)
                self.assertTrue(database_path.with_suffix('.db.jobs.lock').is_file())
                with database.exclusive_job_runtime():
                    pass

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
