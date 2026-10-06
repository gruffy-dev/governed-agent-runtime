"""Tests for portable JSON Schema adaptation to Google GenAI."""

import unittest
from copy import deepcopy

from mosaic.components.skills.google_gen_ai_response_schema_adapter import (
    GoogleGenAiResponseSchemaAdapter,
)


class TestGoogleGenAiResponseSchemaAdapter(unittest.TestCase):
    """Verify safe conversion into Google GenAI's supported schema subset."""

    def setUp(self) -> None:
        """Create a stateless adapter for each test."""
        self.adapter = GoogleGenAiResponseSchemaAdapter()

    def test_adapts_portable_schema_without_mutating_source(self) -> None:
        """Annotations are removed and nullable type arrays become anyOf."""
        source = {
            '$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'https://mosaic.example/diagnostic.schema.json',
            'type': 'object',
            'additionalProperties': False,
            'required': ['time_window'],
            'properties': {
                'time_window': {
                    'type': ['string', 'null'],
                },
                'status': {
                    'type': 'string',
                    'enum': ['healthy', 'failed'],
                    'minLength': 1,
                },
            },
        }
        original = deepcopy(source)

        adapted = self.adapter.adapt(source)

        self.assertEqual(source, original)
        self.assertNotIn('$schema', adapted)
        self.assertNotIn('$id', adapted)
        self.assertEqual(
            adapted['properties']['time_window'],
            {
                'anyOf': [
                    {'type': 'string'},
                    {'type': 'null'},
                ]
            },
        )
        self.assertEqual(
            adapted['properties']['status']['enum'],
            ['healthy', 'failed'],
        )
        self.assertFalse(adapted['additionalProperties'])

    def test_unsupported_keyword_reports_schema_path(self) -> None:
        """Meaningful unsupported constraints fail instead of disappearing."""
        source = {
            'type': 'object',
            'properties': {
                'status': {
                    'type': 'string',
                    'const': 'healthy',
                }
            },
        }

        with self.assertRaisesRegex(
            ValueError,
            r"'const' at \$\.properties\.status",
        ):
            self.adapter.adapt(source)

    def test_type_array_cannot_conflict_with_existing_any_of(self) -> None:
        """An ambiguous conversion fails with its exact schema location."""
        source = {
            'type': 'object',
            'properties': {
                'value': {
                    'type': ['string', 'null'],
                    'anyOf': [{'maxLength': 20}],
                }
            },
        }

        with self.assertRaisesRegex(
            ValueError,
            r'cannot be combined with anyOf at \$\.properties\.value',
        ):
            self.adapter.adapt(source)


if __name__ == '__main__':
    unittest.main()
