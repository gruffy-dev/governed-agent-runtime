"""Semantic capability model used by the MOSAIC runtime."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .capability_provider_binding import CapabilityProviderBinding


class Capability(BaseModel):
    """Describe a semantic capability and its provider bindings."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    name: str = Field(
        description='Stable semantic capability name used by skills.',
        min_length=1,
        pattern=r'^[a-z][a-z0-9]*(?:\.[a-z0-9]+)+$',
    )
    description: str = Field(
        description='Compact description of the capability outcome.',
        min_length=1,
    )
    provider_bindings: tuple[CapabilityProviderBinding, ...] = Field(
        description='Concrete tools able to implement the capability.',
        min_length=1,
    )

    @model_validator(mode='after')
    def validate_unique_provider_bindings(self) -> Self:
        """Validate that concrete provider bindings are not duplicated.

        Returns:
            The validated capability.

        Raises:
            ValueError: If a provider and tool pair appears more than once.
        """
        binding_keys = [
            (binding.provider_type, binding.tool_name)
            for binding in self.provider_bindings
        ]
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError('Capability provider bindings must be unique.')

        return self
