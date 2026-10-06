"""Tests for bounded declarative MCP result processing."""

import unittest

from mosaic.components.capabilities.mcp_capability_result_processor import (
    McpCapabilityResultProcessor,
)
from mosaic.models.capabilities.capability_result_binding import (
    CapabilityResultBinding,
)
from mosaic.models.capabilities.capability_evidence_limit_exceeded_error import (
    CapabilityEvidenceLimitExceededError,
)


class TestMcpCapabilityResultProcessor(unittest.TestCase):
    """Verify standard sources, formats, selectors, and reductions."""

    def test_yaml_text_collection_is_counted(self) -> None:
        """A declared YAML array is reduced without exposing raw objects."""
        result = McpCapabilityResultProcessor().process(
            provider_result={
                'content': [
                    {
                        'type': 'text',
                        'text': '- {name: object-a}\n- {name: object-b}\n',
                    }
                ]
            },
            result_binding=self._binding(),
            tool_arguments={'scope': 'payments'},
        )

        self.assertEqual(result, {'scope': 'payments', 'object_count': 2})

    def test_structured_content_is_selected_by_json_pointer(self) -> None:
        """Native structured MCP content needs no server-specific adapter."""
        result = McpCapabilityResultProcessor().process(
            provider_result={
                'structuredContent': {
                    'summary': {'health': 'degraded'},
                }
            },
            result_binding=CapabilityResultBinding(
                content_source='structured_content',
                content_media_type=None,
                content_block_index=None,
                json_pointer='/summary/health',
                operation='select',
                output_field='health',
                maximum_response_characters=1000,
                maximum_collection_items=10,
            ),
            tool_arguments={},
        )

        self.assertEqual(result, {'health': 'degraded'})

    def test_wrapped_structured_collection_is_counted(self) -> None:
        """MCP object-wrapped collections can be counted declaratively."""
        result = McpCapabilityResultProcessor().process(
            provider_result={
                'structuredContent': {
                    'items': [
                        {'identity': 'object-a'},
                        {'identity': 'object-b'},
                    ]
                }
            },
            result_binding=CapabilityResultBinding(
                content_source='structured_content',
                content_media_type=None,
                content_block_index=None,
                json_pointer='/items',
                operation='count',
                output_field='object_count',
                maximum_response_characters=1000,
                maximum_collection_items=10,
            ),
            tool_arguments={},
        )

        self.assertEqual(result, {'object_count': 2})

    def test_bounded_plain_text_is_selected_without_interpretation(self) -> None:
        """Provider-owned compact text remains protocol-neutral evidence."""
        result = McpCapabilityResultProcessor().process(
            provider_result={
                'content': [
                    {
                        'type': 'text',
                        'text': 'NAME READY STATUS\nobject-a 1/1 Running',
                    }
                ]
            },
            result_binding=CapabilityResultBinding(
                content_source='text_content',
                content_media_type='text/plain',
                content_block_index=0,
                json_pointer='',
                operation='select',
                output_field='evidence',
                maximum_response_characters=1000,
                maximum_collection_items=10,
            ),
            tool_arguments={},
        )

        self.assertEqual(
            result,
            {'evidence': 'NAME READY STATUS\nobject-a 1/1 Running'},
        )

    def test_plain_text_size_limit_is_enforced(self) -> None:
        """Oversized unstructured evidence fails before model exposure."""
        with self.assertRaisesRegex(
            CapabilityEvidenceLimitExceededError,
            'size limit',
        ):
            McpCapabilityResultProcessor().process(
                provider_result={
                    'content': [{'type': 'text', 'text': 'too-large'}]
                },
                result_binding=CapabilityResultBinding(
                    content_source='text_content',
                    content_media_type='text/plain',
                    content_block_index=0,
                    json_pointer='',
                    operation='select',
                    output_field='evidence',
                    maximum_response_characters=3,
                    maximum_collection_items=10,
                ),
                tool_arguments={},
            )

    def test_unsafe_yaml_reference_is_rejected(self) -> None:
        """Aliases cannot expand or recursively link provider data."""
        with self.assertRaisesRegex(ValueError, 'aliases'):
            McpCapabilityResultProcessor().process(
                provider_result={
                    'content': [
                        {
                            'type': 'text',
                            'text': '- &item {name: a}\n- *item\n',
                        }
                    ]
                },
                result_binding=self._binding(),
                tool_arguments={'scope': 'payments'},
            )

    def test_collection_limit_is_enforced(self) -> None:
        """An oversized collection cannot appear partially complete."""
        with self.assertRaisesRegex(
            CapabilityEvidenceLimitExceededError,
            'collection limit',
        ):
            McpCapabilityResultProcessor().process(
                provider_result={
                    'content': [
                        {
                            'type': 'text',
                            'text': '- {name: a}\n- {name: b}\n',
                        }
                    ]
                },
                result_binding=self._binding(maximum_collection_items=1),
                tool_arguments={'scope': 'payments'},
            )

    def _binding(
        self,
        maximum_collection_items: int = 10,
    ) -> CapabilityResultBinding:
        """Create a generic YAML count binding for test evidence."""
        return CapabilityResultBinding(
            content_source='text_content',
            content_media_type='application/yaml',
            content_block_index=0,
            json_pointer='',
            operation='count',
            output_field='object_count',
            evidence_tool_argument_names=('scope',),
            maximum_response_characters=1000,
            maximum_collection_items=maximum_collection_items,
        )


if __name__ == '__main__':
    unittest.main()
