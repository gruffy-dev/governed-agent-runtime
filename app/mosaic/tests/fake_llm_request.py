import sys
from collections.abc import Iterator
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from pydantic import ConfigDict, create_model


class FakeLlmRequest:
    def __init__(self) -> None:
        self.config = SimpleNamespace(tool_config=None)

    @staticmethod
    @contextmanager
    def google_types() -> Iterator[None]:
        function_config = create_model(
            'TestFunctionCallingConfig',
            mode=(str, ...),
            allowed_function_names=(list[str] | None, None),
        )
        types = ModuleType('google.genai.types')
        types.FunctionCallingConfig = function_config
        types.ToolConfig = create_model(
            'TestToolConfig',
            __config__=ConfigDict(extra='allow'),
            function_calling_config=(function_config | None, None),
        )
        with patch.dict(sys.modules, {'google.genai.types': types}):
            yield
