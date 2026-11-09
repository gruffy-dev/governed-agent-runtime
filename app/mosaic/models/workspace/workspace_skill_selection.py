from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkspaceSkillSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    expected_version: int = Field(
        strict=True,
        ge=1,
        le=2**63 - 2,
        description='Workspace version read before editing.',
    )
    skill_ids: tuple[Annotated[str, Field(min_length=1, max_length=255)], ...] = Field(
        description='Complete selection of published atomic Skill IDs. An empty list clears it.',
    )

    @model_validator(mode='after')
    def validate_unique_skill_ids(self) -> Self:
        """
        Require each selected Skill to appear once.

        :return: Validated workspace selection.

        :raises ValueError: If a Skill ID is repeated.
        """
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError('Skill IDs must not contain duplicates.')
        return self
