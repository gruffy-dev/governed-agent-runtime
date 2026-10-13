from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceSkillSummary(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    skill_id: str = Field(
        min_length=1, description='Assigned atomic catalogue Skill identifier.'
    )
    display_name: str = Field(
        min_length=1,
        description='Readable label derived from the catalogue Skill name.',
    )
    description: str = Field(
        min_length=1,
        description='Compact catalogue description, excluding executable instructions.',
    )
    kind: Literal['procedural', 'output'] = Field(
        description='Whether the Skill supplies procedural or output guidance.'
    )
    groups: tuple[str, ...] = Field(
        default=(),
        description='Catalogue domain/function paths containing this assigned Skill.',
    )
