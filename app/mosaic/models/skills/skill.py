"""Domain model for a MOSAIC skill."""

import re
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)


class Skill(BaseModel):
    """Represent one immutable procedural or output skill version."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    name: str = Field(
        description='Stable skill identifier used for discovery and loading.',
        min_length=1,
        max_length=64,
        pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$',
    )
    version: str = Field(
        description='Semantic version of the immutable skill definition.',
        pattern=(
            r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
            r'(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
            r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
        ),
    )
    kind: Literal['procedural', 'output'] = Field(
        description='Whether the skill supplies procedure or output guidance.',
    )
    description: str = Field(
        description='Compact metadata used to decide whether the skill applies.',
        min_length=1,
        max_length=1024,
    )
    instruction: str = Field(
        description='Full procedural guidance loaded after skill selection.',
        min_length=1,
    )
    output_form: str | None = Field(
        default=None,
        description='Optional structure required for the skill result.',
        min_length=1,
    )
    output_schema: dict[str, JsonValue] | None = Field(
        default=None,
        description='Optional JSON Schema for machine-consumable output.',
    )
    required_capability_names: tuple[str, ...] = Field(
        default=(),
        description='Semantic capabilities required to execute the skill.',
    )
    optional_capability_names: tuple[str, ...] = Field(
        default=(),
        description='Semantic capabilities that can improve the skill result.',
    )

    @model_validator(mode='after')
    def validate_skill_contract(self) -> Self:
        """Validate capability references and output-skill restrictions.

        Returns:
            The validated skill.

        Raises:
            ValueError: If capability names are malformed, duplicated, or
                overlapping, or if an output skill declares capabilities.
        """
        required_names = self.required_capability_names
        optional_names = self.optional_capability_names

        for field_name, capability_names in (
            ('required_capability_names', required_names),
            ('optional_capability_names', optional_names),
        ):
            contains_invalid_name = any(
                re.fullmatch(
                    r'[a-z][a-z0-9]*(?:\.[a-z0-9]+)+',
                    capability_name,
                )
                is None
                for capability_name in capability_names
            )
            if contains_invalid_name:
                raise ValueError(
                    f'{field_name} must contain semantic capability names.'
                )
            if len(capability_names) != len(set(capability_names)):
                raise ValueError(f'{field_name} must not contain duplicates.')

        if set(required_names) & set(optional_names):
            raise ValueError(
                'Required and optional capability names must not overlap.'
            )

        if self.kind == 'output' and (required_names or optional_names):
            raise ValueError(
                'Output skills cannot declare system capabilities.'
            )

        return self
