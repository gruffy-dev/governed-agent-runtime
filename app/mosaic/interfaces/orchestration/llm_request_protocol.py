"""ADA model-request contract required by MOSAIC orchestration."""

from typing import Protocol

from pydantic import JsonValue


class LlmRequestProtocol(Protocol):
    """Expose dynamic output-schema configuration required by MOSAIC."""

    def set_output_schema(
        self,
        output_schema: dict[str, JsonValue],
    ) -> None:
        """Apply a JSON response schema to the current model request.

        Args:
            output_schema: Validated JSON Schema loaded from an output skill.
        """
        ...
