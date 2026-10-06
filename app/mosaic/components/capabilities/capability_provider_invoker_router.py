"""Provider-name router for modular capability invokers."""

from typing import Self

from pydantic import ConfigDict, Field, JsonValue, model_validator

from ...interfaces.capabilities.capability_provider_invoker import (
    CapabilityProviderInvoker,
)
from ...interfaces.orchestration.callback_context_protocol import (
    CallbackContextProtocol,
)


class CapabilityProviderInvokerRouter(CapabilityProviderInvoker):
    """Route one governed provider name to exactly one internal invoker."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='forbid',
        frozen=True,
    )

    provider_invokers: tuple[CapabilityProviderInvoker, ...] = Field(
        description='Non-overlapping internal provider invokers.',
        min_length=1,
    )

    @model_validator(mode='after')
    def validate_unique_provider_routes(self) -> Self:
        """Reject ambiguous provider ownership.

        Returns:
            Validated immutable provider router.

        Raises:
            ValueError: If an invoker declares no provider or providers overlap.
        """
        provider_names = [
            provider_name
            for invoker in self.provider_invokers
            for provider_name in invoker.supported_provider_names()
        ]
        if not provider_names:
            raise ValueError('Provider invokers must declare provider names.')
        if len(provider_names) != len(set(provider_names)):
            raise ValueError('Capability provider routes must be unique.')
        return self

    def supported_provider_names(self) -> tuple[str, ...]:
        """Return every provider routed by the composed invokers."""
        return tuple(
            provider_name
            for invoker in self.provider_invokers
            for provider_name in invoker.supported_provider_names()
        )

    async def invoke(
        self,
        provider_name: str,
        tool_name: str,
        tool_arguments: dict[str, JsonValue],
        tool_context: CallbackContextProtocol,
    ) -> dict[str, object]:
        """Delegate a governed provider call to its unique invoker.

        Args:
            provider_name: Approved provider selected by capability metadata.
            tool_name: Approved concrete provider tool.
            tool_arguments: Fully prepared concrete arguments.
            tool_context: Active ADK tool context.

        Returns:
            Raw provider evidence returned by the selected invoker.

        Raises:
            LookupError: If no invoker owns the provider name.
        """
        selected_invoker = next(
            (
                invoker
                for invoker in self.provider_invokers
                if provider_name in invoker.supported_provider_names()
            ),
            None,
        )
        if selected_invoker is None:
            raise LookupError('No invoker owns the selected provider.')
        return await selected_invoker.invoke(
            provider_name=provider_name,
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            tool_context=tool_context,
        )
