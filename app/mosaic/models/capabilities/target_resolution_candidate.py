"""User-presentable candidate produced during target resolution."""

from pydantic import BaseModel, ConfigDict, Field


class TargetResolutionCandidate(BaseModel):
    """Identify one configured target without exposing provider details."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    target_id: str = Field(
        description='Canonical candidate target identity.',
        min_length=3,
        max_length=255,
        pattern=r'^[a-z][a-z0-9-]*/[a-z][a-z0-9-]*$',
    )
    display_name: str = Field(
        description='Human-readable clarification choice.',
        min_length=1,
        max_length=200,
    )
