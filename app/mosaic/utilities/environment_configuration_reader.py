"""Typed readers for trusted deployment environment configuration."""

import json
import os
from typing import Any


class EnvironmentConfigurationReader:
    """Read and validate common environment-backed configuration values."""

    @staticmethod
    def read_required_string(environment_variable_name: str) -> str:
        """Read one required non-empty environment setting.

        Args:
            environment_variable_name: Name of the trusted environment value.

        Returns:
            Configured value with surrounding whitespace removed.

        Raises:
            ValueError: If the value is absent or blank.
        """
        value = os.getenv(environment_variable_name, '').strip()
        if not value:
            raise ValueError(
                f'{environment_variable_name} must not be empty.'
            )
        return value

    @staticmethod
    def read_json_object(
        environment_variable_name: str,
        default_value: str,
    ) -> dict[str, Any]:
        """Read one environment variable as a JSON object.

        Args:
            environment_variable_name: Name of the trusted environment value.
            default_value: JSON object used when the value is absent.

        Returns:
            Parsed JSON object for subsequent model validation.

        Raises:
            ValueError: If the configured value contains malformed JSON.
            TypeError: If the configured JSON value is not an object.
        """
        raw_value = os.getenv(environment_variable_name, default_value)
        try:
            parsed_value = json.loads(raw_value)
        except json.JSONDecodeError as error:
            raise ValueError(
                f'{environment_variable_name} must contain valid JSON.'
            ) from error
        if not isinstance(parsed_value, dict):
            raise TypeError(
                f'{environment_variable_name} must contain a JSON object.'
            )
        return parsed_value

    @staticmethod
    def read_positive_integer(
        environment_variable_name: str,
        default_value: int,
    ) -> int:
        """Read one positive integer environment setting.

        Args:
            environment_variable_name: Name of the trusted environment value.
            default_value: Integer used when the value is absent.

        Returns:
            Parsed positive integer.

        Raises:
            ValueError: If the value is not a positive integer.
        """
        raw_value = os.getenv(environment_variable_name, str(default_value))
        try:
            parsed_value = int(raw_value)
        except ValueError as error:
            raise ValueError(
                f'{environment_variable_name} must contain an integer.'
            ) from error
        if parsed_value <= 0:
            raise ValueError(
                f'{environment_variable_name} must be greater than zero.'
            )
        return parsed_value
