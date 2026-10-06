"""Provider binding model for a MOSAIC capability."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .capability_argument_binding import CapabilityArgumentBinding
from .capability_result_binding import CapabilityResultBinding


class CapabilityProviderBinding(BaseModel):
    """Map a semantic capability to one provider type and concrete tool."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    provider_type: str = Field(
        description='Provider function used for target-aware selection.',
        min_length=1,
        pattern=r'^[a-z][a-z0-9-]*$',
    )
    tool_name: str = Field(
        description='Concrete callable tool implementing the capability.',
        min_length=1,
        pattern=r'^[a-z][a-z0-9_]*$',
    )
    priority: int = Field(
        default=100,
        description='Provider preference where lower values are preferred.',
        ge=0,
    )
    read_only: bool = Field(
        default=True,
        description='Whether the provider tool is guaranteed not to mutate.',
    )
    argument_bindings: tuple[CapabilityArgumentBinding, ...] = Field(
        default=(),
        description='Fixed and semantic mappings for concrete tool arguments.',
    )
    result_binding: CapabilityResultBinding | None = Field(
        default=None,
        description='Optional bounded reduction for raw provider results.',
    )

    @model_validator(mode='after')
    def validate_unique_tool_argument_names(self) -> Self:
        """Validate that each concrete tool argument is bound once.

        Returns:
            The validated provider binding.

        Raises:
            ValueError: If multiple bindings target the same tool argument.
        """
        tool_argument_names = [
            binding.tool_argument_name
            for binding in self.argument_bindings
        ]
        if len(tool_argument_names) != len(set(tool_argument_names)):
            raise ValueError('Concrete tool argument names must be unique.')
        if self.result_binding is not None and not set(
            self.result_binding.evidence_tool_argument_names
        ).issubset(tool_argument_names):
            raise ValueError(
                'Result evidence arguments must be bound tool arguments.'
            )

        return self
