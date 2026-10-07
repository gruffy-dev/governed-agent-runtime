"""Trusted configuration for the MOSAIC-owned SQLite database."""

import os
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..utilities.environment_configuration_reader import EnvironmentConfigurationReader


class MosaicDatabaseConfiguration(BaseModel):
    """Configure one SQLite file independently from ADA session storage."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        validate_default=True,
    )

    database_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                'MOSAIC_DATABASE_PATH',
                'app/mosaic/.adk/mosaic.db',
            )
        ),
        description=(
            'Local or mounted-storage path of the MOSAIC-owned SQLite file.'
        ),
    )
    storage_mode: Literal['local', 'mounted'] = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_DATABASE_STORAGE_MODE',
            'local',
        ),
        description=(
            'Storage policy controlling local directory creation or mounted '
            'path validation.'
        ),
    )
    busy_timeout_seconds: int = Field(
        default_factory=lambda: (
            EnvironmentConfigurationReader.read_positive_integer(
                'MOSAIC_DATABASE_BUSY_TIMEOUT_SECONDS',
                5,
            )
        ),
        description='Maximum time SQLite waits for a database lock.',
        gt=0,
        le=60,
    )
    journal_mode: Literal['DELETE'] = Field(
        default='DELETE',
        description='Rollback journal mode required for mounted storage.',
    )
    synchronous_mode: Literal['FULL'] = Field(
        default='FULL',
        description='SQLite durability level for committed writes.',
    )

    @property
    def resolved_database_path(self) -> Path:
        """Return an absolute database path for the runtime connection.

        Returns:
            Expanded absolute path for the configured SQLite database.
        """
        return self.database_path.expanduser().resolve()

    def prepare_database_path(self) -> Path:
        """Prepare local storage or validate an existing mounted directory.

        Returns:
            Absolute path of the database file ready for SQLite to open.

        Raises:
            FileNotFoundError: If the mounted parent directory is absent.
            NotADirectoryError: If the mounted parent path is not a directory.
            PermissionError: If the mounted parent directory is not writable.
            ValueError: If the database path already identifies a directory.
        """
        database_path = self.resolved_database_path
        parent_directory = database_path.parent

        if database_path.exists() and database_path.is_dir():
            raise ValueError('database_path must identify a file.')

        if self.storage_mode == 'local':
            parent_directory.mkdir(parents=True, exist_ok=True)
            return database_path

        if not parent_directory.exists():
            raise FileNotFoundError(
                'Mounted database parent directory does not exist.'
            )
        if not parent_directory.is_dir():
            raise NotADirectoryError(
                'Mounted database parent path is not a directory.'
            )
        if not os.access(parent_directory, os.W_OK):
            raise PermissionError(
                'Mounted database parent directory is not writable.'
            )
        return database_path

    @model_validator(mode='after')
    def validate_database_path(self) -> Self:
        """Prevent MOSAIC from opening ADA's session database.

        Returns:
            The validated immutable configuration.

        Raises:
            ValueError: If the configured filename is not ``mosaic.db``.
        """
        expanded_path = self.database_path.expanduser()
        if expanded_path.name != 'mosaic.db':
            raise ValueError('database_path must end with mosaic.db.')
        if self.storage_mode == 'mounted' and not expanded_path.is_absolute():
            raise ValueError(
                'Mounted database_path must be absolute.'
            )
        return self
