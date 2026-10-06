"""ADA MCPToolset-backed live capability provider invoker."""

from pydantic import ConfigDict, Field, JsonValue

from ...interfaces.capabilities.capability_provider_invoker import (
    CapabilityProviderInvoker,
)
from ...interfaces.orchestration.callback_context_protocol import (
    CallbackContextProtocol,
)
from ...models.capabilities.mcp_provider_configuration import (
    McpProviderConfiguration,
)


class AdaMcpCapabilityProviderInvoker(CapabilityProviderInvoker):
    """Invoke allowlisted live MCP tools with ADA request-scoped headers."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='forbid',
        frozen=True,
    )

    configuration: McpProviderConfiguration = Field(
        description='Trusted endpoint and tool allowlist for one MCP server.',
    )
    agent_identifier: str = Field(
        description='Non-empty static x-agent-id header value.',
        min_length=1,
    )

    def supported_provider_names(self) -> tuple[str, ...]:
        """Return the single provider owned by this invoker."""
        return (self.configuration.provider_name,)

    async def invoke(
        self,
        provider_name: str,
        tool_name: str,
        tool_arguments: dict[str, JsonValue],
        tool_context: CallbackContextProtocol,
    ) -> dict[str, object]:
        """Invoke one exact allowlisted MCP tool and close its toolset.

        Args:
            provider_name: Approved provider selected by capability metadata.
            tool_name: Approved exact MCP tool name.
            tool_arguments: Fully prepared concrete MCP arguments.
            tool_context: Active ADK context carrying request-scoped headers.

        Returns:
            Raw serialized MCP call result for governed result processing.

        Raises:
            LookupError: If provider or tool is outside the trusted allowlist.
            RuntimeError: If MCP reports an error result.
            TypeError: If ADK returns an unexpected result shape.
        """
        if provider_name != self.configuration.provider_name:
            raise LookupError('The selected MCP provider is not configured.')
        if tool_name not in self.configuration.allowed_tool_names:
            raise LookupError('The selected MCP tool is not allowlisted.')

        from ada_sdk.mcp.mcp_header_provider import MCPHeaderProvider
        from google.adk.tools.mcp_tool import (
            McpToolset,
            StreamableHTTPConnectionParams,
        )

        base_url = str(self.configuration.base_url)
        header_provider = MCPHeaderProvider(
            base_url=base_url,
            static_headers={'x-agent-id': self.agent_identifier},
        )
        toolset = McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=base_url),
            header_provider=header_provider.get_headers,
            tool_filter=[tool_name],
        )
        try:
            tools = await toolset.get_tools(tool_context)
            selected_tools = [tool for tool in tools if tool.name == tool_name]
            if len(selected_tools) != 1:
                raise LookupError(
                    'The allowlisted MCP tool was not discovered uniquely.'
                )
            result = await selected_tools[0].run_async(
                args=tool_arguments,
                tool_context=tool_context,
            )
            if not isinstance(result, dict):
                raise TypeError('The MCP tool returned an invalid result type.')
            if result.get('isError') is True:
                raise RuntimeError('The MCP tool reported an execution error.')
            return result
        finally:
            await toolset.close()
