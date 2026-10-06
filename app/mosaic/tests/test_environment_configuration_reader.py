"""Tests for shared environment configuration readers."""

import os
import unittest
from unittest.mock import patch

from mosaic.utilities.environment_configuration_reader import (
    EnvironmentConfigurationReader,
)


class TestEnvironmentConfigurationReader(unittest.TestCase):
    """Verify common environment values fail closed when malformed."""

    def test_required_string_is_trimmed(self) -> None:
        """A non-empty required value is returned without outer whitespace."""
        with patch.dict(os.environ, {'MOSAIC_TEST_STRING': ' value '}):
            result = EnvironmentConfigurationReader.read_required_string(
                'MOSAIC_TEST_STRING'
            )

        self.assertEqual(result, 'value')

    def test_missing_required_string_is_rejected(self) -> None:
        """Absent trusted string configuration fails closed."""
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaises(ValueError),
        ):
            EnvironmentConfigurationReader.read_required_string(
                'MOSAIC_TEST_STRING'
            )

    def test_json_object_is_read(self) -> None:
        """A configured JSON object is returned unchanged."""
        with patch.dict(os.environ, {'MOSAIC_TEST_JSON': '{"key":"value"}'}):
            result = EnvironmentConfigurationReader.read_json_object(
                'MOSAIC_TEST_JSON',
                '{}',
            )

        self.assertEqual(result, {'key': 'value'})

    def test_non_object_json_is_rejected(self) -> None:
        """Valid JSON of the wrong shape cannot become configuration."""
        with (
            patch.dict(os.environ, {'MOSAIC_TEST_JSON': '[]'}),
            self.assertRaises(TypeError),
        ):
            EnvironmentConfigurationReader.read_json_object(
                'MOSAIC_TEST_JSON',
                '{}',
            )

    def test_positive_integer_is_read(self) -> None:
        """A configured positive integer is parsed once consistently."""
        with patch.dict(os.environ, {'MOSAIC_TEST_INTEGER': '17'}):
            result = EnvironmentConfigurationReader.read_positive_integer(
                'MOSAIC_TEST_INTEGER',
                1,
            )

        self.assertEqual(result, 17)

    def test_invalid_positive_integers_are_rejected(self) -> None:
        """Non-integer and non-positive values fail closed."""
        for raw_value in ('invalid', '0', '-1'):
            with (
                self.subTest(raw_value=raw_value),
                patch.dict(
                    os.environ,
                    {'MOSAIC_TEST_INTEGER': raw_value},
                ),
                self.assertRaises(ValueError),
            ):
                EnvironmentConfigurationReader.read_positive_integer(
                    'MOSAIC_TEST_INTEGER',
                    1,
                )


if __name__ == '__main__':
    unittest.main()
