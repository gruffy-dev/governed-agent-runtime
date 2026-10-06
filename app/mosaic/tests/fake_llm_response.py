"""Minimal ADK response substitute for callback unit tests."""

from types import SimpleNamespace


class FakeLlmResponse:
    """Provide only the ADK response behaviour consumed by callbacks."""

    def __init__(
        self,
        *,
        content: SimpleNamespace | None,
        error_code: str | None = None,
        partial: bool | None = None,
    ) -> None:
        """Store the response fields consumed by the completion guard.

        Args:
            content: ADK-like response content containing parts.
            error_code: Optional model error code.
            partial: Whether the response is an incomplete stream fragment.
        """
        self.content = content
        self.error_code = error_code
        self.partial = partial

    def get_function_calls(self) -> list[SimpleNamespace]:
        """Return function calls contained in fake response parts.

        Returns:
            Function-call objects from parts that contain one.
        """
        if not self.content:
            return []
        return [
            part.function_call
            for part in self.content.parts
            if getattr(part, 'function_call', None)
        ]

    @classmethod
    def model_validate(cls, value: dict[str, object]) -> 'FakeLlmResponse':
        """Parse the callback's ADK-shaped replacement response.

        Args:
            value: Serialized response containing one function-call part.

        Returns:
            Fake response exposing the parsed function call.

        Raises:
            AssertionError: If the serialized response shape is invalid.
        """
        content = value['content']
        assert isinstance(content, dict)
        raw_parts = content['parts']
        assert isinstance(raw_parts, list)
        raw_function_call = raw_parts[0]['function_call']
        return cls(
            content=SimpleNamespace(
                parts=[
                    SimpleNamespace(
                        function_call=SimpleNamespace(**raw_function_call)
                    )
                ]
            )
        )
