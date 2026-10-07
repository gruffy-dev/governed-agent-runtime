"""Alembic upgrade runner for the MOSAIC-owned database."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from ... import migrations
from .mosaic_database import MosaicDatabase


class MosaicDatabaseMigrator:
    """Upgrade one MOSAIC database through its packaged migration history."""

    def __init__(self, database: MosaicDatabase) -> None:
        """Bind the migrator to the owned database engine.

        Args:
            database: MOSAIC database whose schema must be upgraded.
        """
        self._database = database

    def upgrade(self) -> None:
        """Upgrade the database to the latest packaged revision.

        Raises:
            RuntimeError: If the packaged migration directory is unavailable.
            Exception: Propagates any Alembic or database migration failure.
        """
        migration_package_path = migrations.__file__
        if migration_package_path is None:
            raise RuntimeError('MOSAIC migration package path is unavailable.')

        alembic_configuration = Config()
        alembic_configuration.set_main_option(
            'script_location',
            str(Path(migration_package_path).resolve().parent),
        )
        with self._database.engine.begin() as connection:
            alembic_configuration.attributes['connection'] = connection
            command.upgrade(alembic_configuration, 'head')
