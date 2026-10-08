from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PilotWorkspaceSkillUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    skill_ids: tuple[
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=64,
                pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$',
            ),
        ],
        ...,
    ] = Field(
        default=(),
        description='Atomic approved Skill identifiers to assign.',
    )
    group_ids: tuple[
        Annotated[
            str,
            Field(
                min_length=1,
                max_length=129,
                pattern=(
                    r'^[a-z0-9]+(?:-[a-z0-9]+)*'
                    r'(?:/[a-z0-9]+(?:-[a-z0-9]+)*)?$'
                ),
            ),
        ],
        ...,
    ] = Field(
        default=(),
        description='Current catalogue groups to expand into atomic Skills.',
    )
    clear: bool = Field(
        default=False,
        description='Whether to replace the assignment with an empty set.',
    )
    dry_run: bool = Field(
        default=False,
        description='Whether to resolve without changing the workspace.',
    )

    @model_validator(mode='after')
    def validate_selection(self) -> Self:
        """
        Require a selection or explicit clear without duplicate identifiers.

        :return: Validated immutable workspace Skill update request.

        :raises ValueError: If selection and clear options conflict.
        """
        if self.clear and (self.skill_ids or self.group_ids):
            raise ValueError(
                'clear cannot be combined with Skill or group identifiers.'
            )
        if not self.clear and not self.skill_ids and not self.group_ids:
            raise ValueError('clear is required for an empty Skill set.')
        if len(self.skill_ids) != len(set(self.skill_ids)):
            raise ValueError('skill_ids must not contain duplicates.')
        if len(self.group_ids) != len(set(self.group_ids)):
            raise ValueError('group_ids must not contain duplicates.')
        return self
