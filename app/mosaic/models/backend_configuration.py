"""Trusted environment configuration for the MOSAIC backend process."""

import os

from pydantic import BaseModel, ConfigDict, Field

from ..utilities.environment_configuration_reader import EnvironmentConfigurationReader


class BackendConfiguration(BaseModel):
    """Configure the network listener without coupling it to ADA internals."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    host: str = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_BACKEND_HOST',
            '127.0.0.1',
        ),
        description='Network interface on which the backend listens.',
        min_length=1,
        max_length=255,
        pattern=r'^\S+$',
    )
    port: int = Field(
        default_factory=lambda: (
            EnvironmentConfigurationReader.read_positive_integer(
                'PORT',
                8000,
            )
        ),
        description='TCP port on which the backend listens.',
        ge=1,
        le=65535,
    )
