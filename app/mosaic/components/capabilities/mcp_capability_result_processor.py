"""Bounded declarative reduction of raw MCP capability results."""

import json
import re

import yaml
from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter
from yaml.tokens import AliasToken, AnchorToken, TagToken

from ...models.capabilities.capability_result_binding import (
    CapabilityResultBinding,
)
from ...models.capabilities.capability_evidence_limit_exceeded_error import (
    CapabilityEvidenceLimitExceededError,
)


class McpCapabilityResultProcessor(BaseModel):
    """Convert bounded MCP results into compact model-visible evidence."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    def process(
        self,
        provider_result: dict[str, object],
        result_binding: CapabilityResultBinding,
        tool_arguments: dict[str, JsonValue],
    ) -> dict[str, JsonValue]:
        """Apply one validated declarative provider-result binding.

        Args:
            provider_result: Raw serialized MCP call result.
            result_binding: Governed bounded reduction selected by capability.
            tool_arguments: Prepared arguments supplied to the MCP tool.

        Returns:
            Compact JSON-compatible evidence for model context.

        Raises:
            ValueError: If content is absent, oversized, unsafe, or malformed.
            TypeError: If the configured source or operation receives an
                incompatible provider-result shape.
            LookupError: If the configured JSON Pointer cannot be resolved.
        """
        if provider_result.get('isError') is True:
            raise ValueError('The MCP provider reported an error result.')
        decoded_result = self._decode_result(provider_result, result_binding)
        selected_result = self._resolve_json_pointer(
            decoded_result,
            result_binding.json_pointer,
        )
        if isinstance(selected_result, (dict, list)) and len(
            selected_result
        ) > result_binding.maximum_collection_items:
            raise CapabilityEvidenceLimitExceededError(
                'The MCP result exceeds its collection limit.'
            )

        if result_binding.operation == 'count':
            if not isinstance(selected_result, (dict, list)):
                raise TypeError('The count operation requires a collection.')
            output_value: JsonValue = len(selected_result)
        else:
            output_value = TypeAdapter(JsonValue).validate_python(
                selected_result
            )

        evidence: dict[str, JsonValue] = {}
        for argument_name in result_binding.evidence_tool_argument_names:
            if argument_name not in tool_arguments:
                raise ValueError(
                    'A configured evidence argument was not supplied.'
                )
            evidence[argument_name] = tool_arguments[argument_name]
        evidence[result_binding.output_field] = output_value
        return evidence

    def _decode_result(
        self,
        provider_result: dict[str, object],
        result_binding: CapabilityResultBinding,
    ) -> object:
        """Extract and decode one standard MCP result source.

        Args:
            provider_result: Raw serialized MCP call result.
            result_binding: Governed source and decoding configuration.

        Returns:
            JSON-compatible structured value or bounded plain text.

        Raises:
            ValueError: If configured content is absent, oversized, malformed,
                unsafe, or not JSON-compatible.
            TypeError: If MCP content has an incompatible container shape.
        """
        if result_binding.content_source == 'structured_content':
            if 'structuredContent' not in provider_result:
                raise ValueError(
                    'The MCP provider result has no structured content.'
                )
            result = TypeAdapter(JsonValue).validate_python(
                provider_result['structuredContent']
            )
            encoded_result = json.dumps(
                result,
                ensure_ascii=False,
                separators=(',', ':'),
            )
            self._enforce_response_limit(encoded_result, result_binding)
            return result

        encoded_result = self._text_content(provider_result, result_binding)
        self._enforce_response_limit(encoded_result, result_binding)
        if result_binding.content_media_type == 'application/json':
            try:
                result = json.loads(encoded_result)
            except json.JSONDecodeError as error:
                raise ValueError(
                    'The MCP provider returned invalid JSON.'
                ) from error
        elif result_binding.content_media_type == 'application/yaml':
            result = self._safe_yaml_load(encoded_result)
        else:
            result = encoded_result
        return TypeAdapter(JsonValue).validate_python(result)

    def _text_content(
        self,
        provider_result: dict[str, object],
        result_binding: CapabilityResultBinding,
    ) -> str:
        """Extract one explicitly selected MCP text content block.

        Args:
            provider_result: Raw serialized MCP call result.
            result_binding: Governed text-block selection configuration.

        Returns:
            Text from the explicitly selected MCP content block.

        Raises:
            ValueError: If the configured content block is absent.
            TypeError: If the MCP content collection or selected block has an
                incompatible shape.
        """
        content = provider_result.get('content')
        if not isinstance(content, list):
            raise TypeError('The MCP provider result has no content blocks.')
        content_block_index = result_binding.content_block_index
        if content_block_index is None or content_block_index >= len(content):
            raise ValueError('The configured MCP content block is absent.')
        content_block = content[content_block_index]
        if (
            not isinstance(content_block, dict)
            or content_block.get('type') != 'text'
            or not isinstance(content_block.get('text'), str)
        ):
            raise TypeError('The configured MCP content block is not text.')
        return content_block['text']

    def _enforce_response_limit(
        self,
        encoded_result: str,
        result_binding: CapabilityResultBinding,
    ) -> None:
        """Reject provider evidence above its declared character limit.

        Args:
            encoded_result: Serialized provider evidence to measure.
            result_binding: Governed response-character limit.

        Raises:
            ValueError: If the encoded evidence exceeds the configured limit.
        """
        if len(encoded_result) > result_binding.maximum_response_characters:
            raise CapabilityEvidenceLimitExceededError(
                'The MCP provider result exceeds its size limit.'
            )

    def _resolve_json_pointer(
        self,
        decoded_result: object,
        json_pointer: str,
    ) -> object:
        """Resolve an RFC 6901 pointer without executable syntax.

        Args:
            decoded_result: Decoded JSON-compatible provider value.
            json_pointer: Validated RFC 6901 pointer to resolve.

        Returns:
            Value selected by the pointer, or the root for an empty pointer.

        Raises:
            ValueError: If a pointer token contains an invalid escape.
            LookupError: If a property or array index cannot be resolved.
            TypeError: If the pointer attempts to traverse a scalar value.
        """
        selected_result = decoded_result
        if not json_pointer:
            return selected_result

        for encoded_token in json_pointer[1:].split('/'):
            if re.search(r'~(?![01])', encoded_token):
                raise ValueError('The JSON pointer contains an invalid escape.')
            token = encoded_token.replace('~1', '/').replace('~0', '~')
            if isinstance(selected_result, dict):
                if token not in selected_result:
                    raise LookupError('The JSON pointer does not exist.')
                selected_result = selected_result[token]
            elif isinstance(selected_result, list):
                if not token.isdigit():
                    raise LookupError('The JSON pointer list index is invalid.')
                index = int(token)
                if index >= len(selected_result):
                    raise LookupError('The JSON pointer does not exist.')
                selected_result = selected_result[index]
            else:
                raise TypeError('The JSON pointer traverses a scalar value.')
        return selected_result

    def _safe_yaml_load(self, encoded_result: str) -> object:
        """Decode one YAML document after rejecting reference features.

        Args:
            encoded_result: Bounded YAML text returned by the MCP provider.

        Returns:
            Decoded YAML document for subsequent JSON-value validation.

        Raises:
            ValueError: If YAML is malformed or contains aliases, anchors, or
                explicit tags.
        """
        try:
            tokens = yaml.scan(encoded_result)
            if any(
                isinstance(token, (AliasToken, AnchorToken, TagToken))
                for token in tokens
            ):
                raise ValueError(
                    'MCP YAML aliases, anchors, and tags are prohibited.'
                )
            return yaml.safe_load(encoded_result)
        except yaml.YAMLError as error:
            raise ValueError('The MCP provider returned invalid YAML.') from error
