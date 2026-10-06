"""Result model for MOSAIC capability resolution."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .resolved_capability import ResolvedCapability


class CapabilityResolutionResult(BaseModel):
    """Report resolved and unavailable semantic capabilities."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    status: Literal['resolved', 'partially_resolved', 'unavailable'] = Field(
        description='Overall capability-resolution outcome.',
    )
    resolved_capabilities: tuple[ResolvedCapability, ...] = Field(
        default=(),
        description='Concrete provider tools selected by the resolver.',
    )
    unavailable_capability_names: tuple[str, ...] = Field(
        default=(),
        description='Capability names without an allowed available provider.',
    )
