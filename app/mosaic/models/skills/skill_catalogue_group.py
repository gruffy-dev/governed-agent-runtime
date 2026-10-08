from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SkillCatalogueGroup(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    group_id: str = Field(
        description='Stable domain or domain/function catalogue group.',
        min_length=1,
        max_length=129,
        pattern=(
            r'^[a-z0-9]+(?:-[a-z0-9]+)*'
            r'(?:/[a-z0-9]+(?:-[a-z0-9]+)*)?$'
        ),
    )
    skill_ids: tuple[str, ...] = Field(
        description='Sorted atomic Skill identifiers currently in the group.',
        min_length=1,
    )

    @model_validator(mode='after')
    def validate_skill_ids(self) -> Self:
        """
        Require unique sorted atomic Skill identifiers.

        :return: Validated immutable catalogue group.

        :raises ValueError: If Skill identifiers are duplicated or unsorted.
        """
        if tuple(sorted(set(self.skill_ids))) != self.skill_ids:
            raise ValueError('skill_ids must be unique and sorted.')
        return self
