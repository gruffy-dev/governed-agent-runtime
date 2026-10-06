"""MOSAIC governance extension for a standard Agent Skill package."""

import re
from pathlib import PurePosixPath
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MosaicSkillMetadata(BaseModel):
    """Describe governed MOSAIC metadata not defined by Agent Skills."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal[1] = Field(
        default=1,
        description='Schema version of the MOSAIC metadata extension.',
    )
    version: str = Field(
        description='Semantic version of the immutable skill package.',
        pattern=(
            r'^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)'
            r'(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
            r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$'
        ),
    )
    kind: Literal['procedural', 'output'] = Field(
        description='Whether the skill supplies procedure or output guidance.',
    )
    output_form_file: str | None = Field(
        default=None,
        description='Optional package-relative Markdown output-form file.',
        min_length=1,
    )
    output_schema_file: str | None = Field(
        default=None,
        description='Optional package-relative JSON Schema file.',
        min_length=1,
    )
    required_capability_names: tuple[str, ...] = Field(
        default=(),
        description='Semantic capabilities required by the skill.',
    )
    optional_capability_names: tuple[str, ...] = Field(
        default=(),
        description='Semantic capabilities that can improve the skill.',
    )

    @model_validator(mode='after')
    def validate_governance_contract(self) -> Self:
        """Validate safe files, capabilities, and output isolation.

        Returns:
            The validated MOSAIC metadata extension.

        Raises:
            ValueError: If file paths are unsafe, capability references are
                malformed or conflicting, or an output skill declares system
                capabilities.
        """
        for field_name, file_name in (
            ('output_form_file', self.output_form_file),
            ('output_schema_file', self.output_schema_file),
        ):
            if file_name is not None:
                self._validate_relative_file(field_name, file_name)

        if (
            self.output_form_file is not None
            and not self.output_form_file.endswith('.md')
        ):
            raise ValueError('output_form_file must be a Markdown file.')
        if (
            self.output_schema_file is not None
            and not self.output_schema_file.endswith('.json')
        ):
            raise ValueError('output_schema_file must be a JSON file.')

        required_names = self.required_capability_names
        optional_names = self.optional_capability_names
        for field_name, capability_names in (
            ('required_capability_names', required_names),
            ('optional_capability_names', optional_names),
        ):
            if any(
                re.fullmatch(
                    r'[a-z][a-z0-9]*(?:\.[a-z0-9]+)+',
                    capability_name,
                )
                is None
                for capability_name in capability_names
            ):
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

    def _validate_relative_file(
        self,
        field_name: str,
        file_name: str,
    ) -> None:
        """Reject absolute, escaping, directory, and non-POSIX file paths.

        Args:
            field_name: Metadata field being validated for error reporting.
            file_name: Candidate path relative to the skill directory.

        Raises:
            ValueError: If the path is unsafe or does not identify a file.
        """
        path = PurePosixPath(file_name)
        if (
            path.is_absolute()
            or '..' in path.parts
            or '\\' in file_name
            or file_name.endswith('/')
            or path.name in {'', '.', '..'}
        ):
            raise ValueError(
                f'{field_name} must be a safe relative POSIX file path.'
            )
