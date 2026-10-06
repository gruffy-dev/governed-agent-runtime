"""Trusted configuration for the external capability-runtime snapshot."""

from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...utilities.environment_configuration_reader import (
    EnvironmentConfigurationReader,
)


class CapabilityRuntimeSnapshotConfiguration(BaseModel):
    """Locate and bound one deployment-managed runtime snapshot."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        validate_default=True,
    )

    snapshot_path: Path = Field(
        default_factory=lambda: Path(
            EnvironmentConfigurationReader.read_required_string(
                'MOSAIC_CAPABILITY_RUNTIME_SNAPSHOT_PATH'
            )
        ),
        description='Absolute path to the versioned JSON snapshot.',
    )
    maximum_snapshot_bytes: int = Field(
        default_factory=lambda: (
            EnvironmentConfigurationReader.read_positive_integer(
                'MOSAIC_CAPABILITY_RUNTIME_SNAPSHOT_MAXIMUM_BYTES',
                2000000,
            )
        ),
        description='Largest capability snapshot file accepted at startup.',
        gt=0,
        le=10000000,
    )
    maximum_result_response_characters: int = Field(
        default_factory=lambda: (
            EnvironmentConfigurationReader.read_positive_integer(
                'MOSAIC_CAPABILITY_RESULT_MAXIMUM_RESPONSE_CHARACTERS',
                500000,
            )
        ),
        description='Deployment ceiling for one encoded capability result.',
        gt=0,
        le=5000000,
    )
    maximum_result_collection_items: int = Field(
        default_factory=lambda: (
            EnvironmentConfigurationReader.read_positive_integer(
                'MOSAIC_CAPABILITY_RESULT_MAXIMUM_COLLECTION_ITEMS',
                2000,
            )
        ),
        description='Deployment ceiling for one selected result collection.',
        gt=0,
        le=100000,
    )

    @model_validator(mode='after')
    def validate_path(self) -> Self:
        """Require a precise absolute file path.

        Returns:
            Validated immutable snapshot configuration.

        Raises:
            ValueError: If the configured snapshot path is not absolute.
        """
        if not self.snapshot_path.expanduser().is_absolute():
            raise ValueError('snapshot_path must be absolute.')
        return self
