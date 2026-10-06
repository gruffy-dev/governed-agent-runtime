"""Capability provider invocation contract for the MOSAIC runtime."""

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, JsonValue

from ..orchestration.callback_context_protocol import CallbackContextProtocol


class CapabilityProviderInvoker(BaseModel, ABC):
    """Invoke an approved provider tool behind the execution boundary."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='forbid',
        frozen=True,
    )

    @abstractmethod
    def supported_provider_names(self) -> tuple[str, ...]:
        """Return exact governed provider names handled by this invoker."""
        raise NotImplementedError

    @abstractmethod
    async def invoke(
        self,
        provider_name: str,
        tool_name: str,
        tool_arguments: dict[str, JsonValue],
        tool_context: CallbackContextProtocol,
    ) -> dict[str, object]:
        """Invoke one concrete tool selected by governed capability metadata.

        Args:
            provider_name: Approved ADA-registered MCP provider name.
            tool_name: Approved concrete tool name within the provider.
            tool_arguments: Fully prepared provider arguments.
            tool_context: Active ADK tool context for request-scoped headers.

        Returns:
            Evidence returned by the concrete provider tool.

        Raises:
            Exception: If provider lookup, invocation, or response handling
                fails. The execution gateway converts this to a safe result.
        """
        raise NotImplementedError
