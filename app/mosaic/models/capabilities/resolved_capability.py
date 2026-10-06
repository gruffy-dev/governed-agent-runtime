"""Resolved capability model used by the MOSAIC runtime."""

from pydantic import BaseModel, ConfigDict, Field


class ResolvedCapability(BaseModel):
    """Identify the concrete provider tool selected for a capability."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    capability_name: str = Field(
        description='Semantic capability requested by the skill or runtime.',
        min_length=1,
    )
    provider_name: str = Field(
        description='Selected capability provider.',
        min_length=1,
    )
    tool_name: str = Field(
        description='Selected callable tool.',
        min_length=1,
    )
    read_only: bool = Field(
        description='Whether the selected tool is guaranteed not to mutate.',
    )
    required_semantic_argument_names: tuple[str, ...] = Field(
        default=(),
        description='Semantic inputs required to prepare the provider call.',
    )
    optional_semantic_argument_names: tuple[str, ...] = Field(
        default=(),
        description='Optional semantic inputs accepted during preparation.',
    )
