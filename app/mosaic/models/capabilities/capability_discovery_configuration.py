"""Trusted limits for skill-gated capability discovery."""

from pydantic import BaseModel, ConfigDict, Field

from ...utilities.environment_configuration_reader import (
    EnvironmentConfigurationReader,
)


class CapabilityDiscoveryConfiguration(BaseModel):
    """Bound model-visible skill-declared capabilities for one goal."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        validate_default=True,
    )

    maximum_candidate_count: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_CAPABILITIES_MAXIMUM_CANDIDATE_COUNT',
            20,
        ),
        description='Maximum skill-declared capabilities exposed per goal.',
        gt=0,
        le=500,
    )
    maximum_metadata_characters: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_CAPABILITIES_MAXIMUM_METADATA_CHARACTERS',
            16000,
        ),
        description='Maximum serialized candidate metadata for one goal.',
        gt=0,
        le=1000000,
    )
