"""Declarative result reduction for one capability provider binding."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CapabilityResultBinding(BaseModel):
    """Describe bounded protocol-neutral result extraction and reduction."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    content_source: Literal['structured_content', 'text_content'] = Field(
        description='Standard MCP result field containing authoritative data.',
    )
    content_media_type: Literal[
        'application/json',
        'application/yaml',
        'text/plain',
    ] | None = Field(
        description='Serialization of selected text content, when applicable.',
    )
    content_block_index: int | None = Field(
        description='Zero-based MCP text block selected from content.',
        ge=0,
    )
    json_pointer: str = Field(
        description='RFC 6901 pointer applied after content decoding.',
    )
    operation: Literal['count', 'select'] = Field(
        description='Deterministic operation applied to the selected value.',
    )
    output_field: str = Field(
        description='Compact evidence field receiving the resulting value.',
        min_length=1,
        pattern=r'^[a-z][a-z0-9_]*$',
    )
    evidence_tool_argument_names: tuple[str, ...] = Field(
        default=(),
        description='Safe concrete arguments copied into compact evidence.',
    )
    maximum_response_characters: int = Field(
        description='Largest encoded result accepted before decoding.',
        gt=0,
        le=5000000,
    )
    maximum_collection_items: int = Field(
        description='Largest selected collection accepted for processing.',
        gt=0,
        le=100000,
    )

    @model_validator(mode='after')
    def validate_binding(self) -> Self:
        """Reject inconsistent sources, selectors, and evidence fields.

        Returns:
            Validated immutable result binding.

        Raises:
            ValueError: If source or evidence configuration is inconsistent.
        """
        if self.content_source == 'structured_content':
            if self.content_media_type is not None:
                raise ValueError(
                    'Structured content must not declare a media type.'
                )
            if self.content_block_index is not None:
                raise ValueError(
                    'Structured content must not select a text block.'
                )
        elif self.content_media_type is None:
            raise ValueError('Text content requires a media type.')
        elif self.content_block_index is None:
            raise ValueError('Text content requires a content block index.')

        if self.content_media_type == 'text/plain' and self.json_pointer:
            raise ValueError('Plain text cannot use a JSON pointer.')
        if self.json_pointer and not self.json_pointer.startswith('/'):
            raise ValueError('json_pointer must be empty or start with /.')

        names = self.evidence_tool_argument_names
        if len(names) != len(set(names)):
            raise ValueError('Evidence tool argument names must be unique.')
        if any(
            not name
            or not name.replace('_', '').isalnum()
            or name[0].isdigit()
            for name in names
        ):
            raise ValueError(
                'Evidence tool argument names must be alphanumeric names.'
            )
        if self.output_field in names:
            raise ValueError(
                'The output field must not replace an evidence argument.'
            )
        return self
