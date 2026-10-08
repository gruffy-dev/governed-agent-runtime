"""Immutable snapshot of a validated skill catalogue."""

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .skill import Skill
from .skill_catalogue_group import SkillCatalogueGroup


class SkillCatalogueSnapshot(BaseModel):
    """Identify and contain one validated Git commit of skills."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    commit_sha: str = Field(
        description='Full Git object identifier of the catalogue commit.',
        pattern=r'^[0-9a-f]{40,64}$',
    )
    loaded_at: datetime = Field(
        description='Timezone-aware time when the snapshot was validated.',
    )
    skills: tuple[Skill, ...] = Field(
        description='Immutable skills validated from the commit.',
        min_length=1,
    )
    groups: tuple[SkillCatalogueGroup, ...] = Field(
        default=(),
        description='Current hierarchy groups expanded during assignment.',
    )

    @model_validator(mode='after')
    def validate_snapshot(self) -> Self:
        """Validate timestamp awareness and unique skill names.

        Returns:
            The validated catalogue snapshot.

        Raises:
            ValueError: If the timestamp is naive or skill names repeat.
        """
        if self.loaded_at.tzinfo is None:
            raise ValueError('loaded_at must be timezone-aware.')

        skill_names = [skill.name for skill in self.skills]
        if len(skill_names) != len(set(skill_names)):
            raise ValueError('Skill names must be unique within a snapshot.')

        group_ids = [group.group_id for group in self.groups]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError('Group IDs must be unique within a snapshot.')
        available_skill_names = set(skill_names)
        if any(
            not set(group.skill_ids).issubset(available_skill_names)
            for group in self.groups
        ):
            raise ValueError(
                'Catalogue groups must reference available Skills.'
            )

        return self
