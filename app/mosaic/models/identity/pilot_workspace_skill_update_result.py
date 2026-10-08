from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PilotWorkspaceSkillUpdateResult(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    workspace_id: str = Field(
        description='Application-generated workspace UUID.',
        min_length=36,
        max_length=36,
    )
    user_id: str = Field(
        description='Immutable owner of the workspace.',
        min_length=1,
        max_length=255,
    )
    version: int = Field(
        description='Current or newly applied workspace version.',
        ge=1,
    )
    skill_ids: tuple[str, ...] = Field(
        description='Sorted atomic Skill identifiers after group expansion.',
    )
    group_ids: tuple[str, ...] = Field(
        description='Requested catalogue groups expanded for this operation.',
    )
    applied: bool = Field(
        description='Whether the replacement was committed to the workspace.',
    )
    updated_at: datetime = Field(
        description='Current or newly applied workspace update time.',
    )
