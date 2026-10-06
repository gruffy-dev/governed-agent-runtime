"""Protected target mapping for a shared MCP provider endpoint."""

import math
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class ProviderTargetBinding(BaseModel):
    """Map one canonical target to an approved provider selector value."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    target_id: str = Field(
        description='Canonical target supported by the shared provider.',
        min_length=3,
        max_length=255,
        pattern=r'^[a-z][a-z0-9-]*/[a-z][a-z0-9-]*$',
    )
    argument_value: JsonValue = Field(
        description='Protected scalar value injected into the provider tool.',
    )

    @model_validator(mode='after')
    def validate_argument_value(self) -> Self:
        """Require a finite non-empty JSON scalar routing value.

        Returns:
            Validated immutable target binding.

        Raises:
            ValueError: If the protected provider value is null, structured,
                blank, or a non-finite number.
        """
        value = self.argument_value
        if value is None or isinstance(value, (dict, list)):
            raise ValueError(
                'Provider target argument values must be JSON scalars.'
            )
        if isinstance(value, str) and not value:
            raise ValueError(
                'Provider target argument values must not be blank.'
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(
                'Provider target argument values must be finite.'
            )
        return self
