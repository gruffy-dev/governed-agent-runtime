from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceSkillSet(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    workspace_id: str = Field(
        description='Application-generated workspace UUID.',
        pattern=(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
            r'[0-9a-f]{4}-[0-9a-f]{12}$'
        ),
    )
    user_id: str = Field(
        description='Immutable owner of the workspace.',
        min_length=1,
        max_length=255,
    )
    version: int = Field(
        description='Optimistic concurrency version of the Skill set.',
        ge=1,
    )
    skill_ids: tuple[str, ...] = Field(
        description='Sorted atomic Skill identifiers assigned to the user.',
    )
    created_at: datetime = Field(
        description='Time at which the workspace was created.',
    )
    updated_at: datetime = Field(
        description='Time of the most recent Skill-set replacement.',
    )
