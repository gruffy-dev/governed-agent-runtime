"""Compact active-target state persisted through one ADA session."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionTargetContext(BaseModel):
    """Retain only the canonical target identity selected for a session."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal[1] = Field(
        default=1,
        description='Schema version for persisted session target state.',
    )
    target_id: str = Field(
        description='Canonical active target identity.',
        min_length=3,
        max_length=255,
        pattern=r'^[a-z][a-z0-9-]*/[a-z][a-z0-9-]*$',
    )
