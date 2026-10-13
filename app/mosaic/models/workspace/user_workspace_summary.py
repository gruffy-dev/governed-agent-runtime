from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .workspace_skill_summary import WorkspaceSkillSummary


class UserWorkspaceSummary(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    user_id: str = Field(
        min_length=1,
        description='Signed-in user derived only from validated authentication.',
    )
    workspace_id: UUID | None = Field(
        description='Owned workspace identifier, or None if no workspace exists.'
    )
    version: int | None = Field(
        ge=1, description='Current assignment version, or None if no workspace exists.'
    )
    skills: tuple[WorkspaceSkillSummary, ...] = Field(
        default=(),
        description='Current assigned Skills present in the active catalogue; not an active Goal snapshot.',
    )
