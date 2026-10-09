import os

from pydantic import BaseModel, ConfigDict, Field


class TrustedRequestConfiguration(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        validate_default=True,
    )

    app_name: str = Field(
        default_factory=lambda: os.getenv('MOSAIC_APP_NAME', 'mosaic'),
        min_length=1,
        max_length=255,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]*$',
        description=(
            'Server-owned application name matching the ADA application '
            'used by conversation adapters.'
        ),
    )
