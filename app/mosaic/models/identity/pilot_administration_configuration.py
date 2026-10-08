import os
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class PilotAdministrationConfiguration(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        validate_default=True,
    )

    enabled: bool = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_PILOT_ADMIN_ENABLED',
            'false',
        ),
        description=(
            'Whether temporary pilot administration routes are registered.'
        ),
    )
    administrator_secret: SecretStr | None = Field(
        default_factory=lambda: (
            os.getenv('MOSAIC_PILOT_ADMIN_SECRET') or None
        ),
        description=(
            'Dedicated bearer secret protecting pilot administration routes.'
        ),
    )

    @model_validator(mode='after')
    def validate_enabled_secret(self) -> Self:
        """
        Require a non-blank high-entropy-sized secret when routes are enabled.

        :return: Validated immutable pilot administration configuration.

        :raises ValueError: If enabled routes lack a suitable secret.
        """
        if not self.enabled:
            return self
        if self.administrator_secret is None:
            raise ValueError(
                'administrator_secret is required when pilot '
                'administration is enabled.'
            )
        secret_value = self.administrator_secret.get_secret_value()
        if len(secret_value) < 32 or secret_value != secret_value.strip():
            raise ValueError(
                'administrator_secret must contain at least 32 '
                'non-whitespace characters.'
            )
        return self
