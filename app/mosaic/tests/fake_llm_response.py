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
        content = value['content']
        assert isinstance(content, dict)
        raw_parts = content['parts']
        assert isinstance(raw_parts, list)
        parts = []
        for raw_part in raw_parts:
            function_call = raw_part.get('function_call')
            parts.append(
                SimpleNamespace(
                    text=raw_part.get('text'),
                    function_call=(
                        SimpleNamespace(**function_call) if function_call else None
                    ),
                )
            )
        return cls(
            content=SimpleNamespace(parts=parts)
        )
