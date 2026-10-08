import os
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...utilities.environment_configuration_reader import EnvironmentConfigurationReader


class PilotAuthenticationConfiguration(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        validate_default=True,
    )

    mode: Literal['production', 'local'] = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_PILOT_AUTH_MODE',
            'production',
        ),
        description='Pilot authentication cookie security mode.',
    )
    cookie_name: str = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_PILOT_AUTH_COOKIE_NAME',
            'mosaic_pilot_session',
        ),
        min_length=1,
        max_length=64,
        pattern=r'^[A-Za-z0-9_-]+$',
        description='Name of the HttpOnly pilot authentication cookie.',
    )
    cookie_lifetime_seconds: int = Field(
        default_factory=lambda: (
            EnvironmentConfigurationReader.read_positive_integer(
                'MOSAIC_PILOT_AUTH_COOKIE_LIFETIME_SECONDS',
                604800,
            )
        ),
        gt=0,
        description='Configured browser-cookie lifetime in seconds.',
    )
    secure_cookie: bool = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_PILOT_AUTH_COOKIE_SECURE',
            'true',
        ),
        description='Whether browsers send the cookie only over HTTPS.',
    )

    @model_validator(mode='after')
    def validate_cookie_security(self) -> Self:
        """
        Refuse an insecure cookie outside explicit local mode.

        :return: Validated immutable pilot authentication configuration.

        :raises ValueError: If production mode disables secure cookies.
        """
        if self.mode == 'production' and not self.secure_cookie:
            raise ValueError(
                'Production pilot authentication requires a secure cookie.'
            )
        return self
