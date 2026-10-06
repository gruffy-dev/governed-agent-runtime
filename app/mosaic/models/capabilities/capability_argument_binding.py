"""Argument binding model for a concrete capability provider tool."""

import re
from string import Formatter
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class CapabilityArgumentBinding(BaseModel):
    """Map a fixed or semantic value to one concrete tool argument."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    tool_argument_name: str = Field(
        description='Concrete argument name accepted by the provider tool.',
        min_length=1,
        pattern=r'^[a-z][A-Za-z0-9_]*$',
    )
    source: Literal['fixed', 'semantic', 'template'] = Field(
        description='How the concrete tool argument value is produced.',
    )
    semantic_argument_names: tuple[str, ...] = Field(
        default=(),
        description='Runtime semantic inputs used to produce the value.',
    )
    fixed_value: JsonValue | None = Field(
        default=None,
        description='Non-overridable value applied to a fixed tool argument.',
    )
    value_template: str | None = Field(
        default=None,
        description='Template used to construct a concrete argument value.',
        min_length=1,
    )
    semantic_argument_patterns: dict[str, str] = Field(
        default_factory=dict,
        description='Optional full-match patterns for semantic input values.',
    )
    required: bool = Field(
        default=True,
        description='Whether a semantic argument must be supplied.',
    )

    @model_validator(mode='after')
    def validate_source_configuration(self) -> Self:
        """Validate fields applicable to the selected argument source.

        Returns:
            The validated argument binding.

        Raises:
            ValueError: If required source fields are absent, source-specific
                fields conflict, names are duplicated, a template references
                undeclared inputs, or an input pattern is invalid.
        """
        if len(self.semantic_argument_names) != len(
            set(self.semantic_argument_names)
        ):
            raise ValueError('Semantic argument names must be unique.')

        invalid_names = [
            name
            for name in self.semantic_argument_names
            if not re.fullmatch(r'[a-z][a-z0-9_]*', name)
        ]
        if invalid_names:
            raise ValueError(
                'Semantic argument names must use lower snake case.'
            )

        undeclared_pattern_names = (
            set(self.semantic_argument_patterns)
            - set(self.semantic_argument_names)
        )
        if undeclared_pattern_names:
            raise ValueError(
                'Semantic argument patterns must reference declared inputs.'
            )
        for pattern in self.semantic_argument_patterns.values():
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(
                    'Semantic argument patterns must be valid expressions.'
                ) from error

        if self.source == 'fixed':
            if 'fixed_value' not in self.model_fields_set:
                raise ValueError('A fixed argument requires fixed_value.')
            if self.semantic_argument_names:
                raise ValueError(
                    'A fixed argument cannot use semantic arguments.'
                )
            if self.value_template is not None:
                raise ValueError('A fixed argument cannot have a template.')
            if self.semantic_argument_patterns:
                raise ValueError(
                    'A fixed argument cannot have semantic input patterns.'
                )
            if not self.required:
                raise ValueError('A fixed argument cannot be optional.')
        elif 'fixed_value' in self.model_fields_set:
            raise ValueError(
                'A non-fixed argument cannot have fixed_value.'
            )
        elif not self.semantic_argument_names:
            raise ValueError(
                'A semantic or template argument requires semantic inputs.'
            )
        elif self.source == 'semantic':
            if len(self.semantic_argument_names) != 1:
                raise ValueError(
                    'A semantic argument requires exactly one semantic input.'
                )
            if self.value_template is not None:
                raise ValueError(
                    'A semantic argument cannot have a value template.'
                )
        elif self.value_template is None:
            raise ValueError('A template argument requires value_template.')
        else:
            template_names = {
                field_name
                for _, field_name, format_spec, conversion in Formatter().parse(
                    self.value_template
                )
                if field_name is not None
                and not format_spec
                and conversion is None
            }
            if template_names != set(self.semantic_argument_names):
                raise ValueError(
                    'Template fields must exactly match semantic inputs and '
                    'cannot use format specifications or conversions.'
                )

        return self
