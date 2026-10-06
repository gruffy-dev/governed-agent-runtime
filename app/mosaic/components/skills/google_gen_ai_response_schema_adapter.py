"""Google GenAI response-schema compatibility boundary."""

from copy import deepcopy
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, JsonValue


class GoogleGenAiResponseSchemaAdapter(BaseModel):
    """Convert portable JSON Schema into Google GenAI's supported subset."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    supported_keywords: ClassVar[frozenset[str]] = frozenset(
        {
            '$defs',
            '$ref',
            'additionalProperties',
            'anyOf',
            'default',
            'description',
            'enum',
            'example',
            'format',
            'items',
            'maxItems',
            'maxLength',
            'maxProperties',
            'maximum',
            'minItems',
            'minLength',
            'minProperties',
            'minimum',
            'nullable',
            'pattern',
            'properties',
            'propertyOrdering',
            'required',
            'title',
            'type',
        }
    )
    removable_annotation_keywords: ClassVar[frozenset[str]] = frozenset(
        {'$id', '$schema'}
    )

    def adapt(
        self,
        output_schema: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        """Create a Google-compatible copy of a portable JSON Schema.

        Args:
            output_schema: Validated JSON Schema supplied by an output skill.

        Returns:
            Independent schema copy accepted by Google GenAI validation.

        Raises:
            TypeError: If a nested schema has an invalid JSON shape.
            ValueError: If the schema uses a meaningful unsupported construct
                or contains an invalid schema shape.
        """
        if not output_schema:
            raise ValueError('Output schema must not be empty.')
        return self._adapt_schema(output_schema, '$')

    def _adapt_schema(
        self,
        schema: dict[str, JsonValue],
        path: str,
    ) -> dict[str, JsonValue]:
        """Recursively adapt one schema node.

        Args:
            schema: JSON Schema node to adapt.
            path: Human-readable JSON path for validation errors.

        Returns:
            Adapted independent schema node.

        Raises:
            ValueError: If a keyword or nested schema shape is unsupported.
        """
        unsupported_keywords = (
            set(schema)
            - self.supported_keywords
            - self.removable_annotation_keywords
        )
        if unsupported_keywords:
            unsupported_keyword = min(unsupported_keywords)
            raise ValueError(
                f"Unsupported JSON Schema keyword '{unsupported_keyword}' "
                f'at {path}.'
            )

        adapted: dict[str, JsonValue] = {}
        for keyword, value in schema.items():
            if keyword in self.removable_annotation_keywords:
                continue
            if keyword in {'properties', '$defs'}:
                adapted[keyword] = self._adapt_schema_map(
                    value,
                    f'{path}.{keyword}',
                )
                continue
            if keyword == 'anyOf':
                adapted[keyword] = self._adapt_schema_list(
                    value,
                    f'{path}.anyOf',
                )
                continue
            if keyword == 'items':
                adapted[keyword] = self._adapt_nested_schema(
                    value,
                    f'{path}.items',
                )
                continue
            if keyword == 'additionalProperties' and isinstance(value, dict):
                adapted[keyword] = self._adapt_schema(
                    value,
                    f'{path}.additionalProperties',
                )
                continue
            if keyword == 'type' and isinstance(value, list):
                if 'anyOf' in schema:
                    raise ValueError(
                        f'A type array cannot be combined with anyOf at {path}.'
                    )
                adapted['anyOf'] = self._adapt_type_array(value, path)
                continue
            adapted[keyword] = deepcopy(value)
        return adapted

    def _adapt_schema_map(
        self,
        value: JsonValue,
        path: str,
    ) -> dict[str, JsonValue]:
        """Adapt a named map of property or definition schemas.

        Args:
            value: Candidate mapping of names to schema objects.
            path: Human-readable JSON path for validation errors.

        Returns:
            Adapted schema mapping.

        Raises:
            TypeError: If the mapping or a child schema is malformed.
        """
        if not isinstance(value, dict):
            raise TypeError(f'Expected a schema mapping at {path}.')
        adapted: dict[str, JsonValue] = {}
        for name, child_schema in value.items():
            adapted[name] = self._adapt_nested_schema(
                child_schema,
                f'{path}.{name}',
            )
        return adapted

    def _adapt_schema_list(
        self,
        value: JsonValue,
        path: str,
    ) -> list[JsonValue]:
        """Adapt a list of alternative schemas.

        Args:
            value: Candidate list of schema objects.
            path: Human-readable JSON path for validation errors.

        Returns:
            Adapted list of alternative schemas.

        Raises:
            ValueError: If the list is empty or contains a malformed schema.
        """
        if not isinstance(value, list) or not value:
            raise ValueError(f'Expected a non-empty schema list at {path}.')
        return [
            self._adapt_nested_schema(child_schema, f'{path}[{index}]')
            for index, child_schema in enumerate(value)
        ]

    def _adapt_nested_schema(
        self,
        value: JsonValue,
        path: str,
    ) -> dict[str, JsonValue]:
        """Validate and adapt one nested schema object.

        Args:
            value: Candidate nested schema.
            path: Human-readable JSON path for validation errors.

        Returns:
            Adapted nested schema.

        Raises:
            TypeError: If the value is not a schema object.
        """
        if not isinstance(value, dict):
            raise TypeError(f'Expected a schema object at {path}.')
        return self._adapt_schema(value, path)

    def _adapt_type_array(
        self,
        value: list[JsonValue],
        path: str,
    ) -> list[JsonValue]:
        """Convert a JSON Schema type array into portable ``anyOf`` branches.

        Args:
            value: Candidate list of JSON Schema primitive type names.
            path: Human-readable JSON path for validation errors.

        Returns:
            Equivalent list of single-type schema branches.

        Raises:
            ValueError: If the array is empty, duplicated, or non-string.
        """
        if (
            not value
            or not all(isinstance(type_name, str) for type_name in value)
            or len(value) != len(set(value))
        ):
            raise ValueError(
                f'Expected unique string type names in the array at {path}.'
            )
        return [{'type': type_name} for type_name in value]
