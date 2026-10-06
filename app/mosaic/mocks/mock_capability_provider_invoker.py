"""Mock internal capability provider invoker."""

from pydantic import ConfigDict, Field, JsonValue

from ..interfaces.capabilities.capability_provider_invoker import (
    CapabilityProviderInvoker,
)
from ..interfaces.orchestration.callback_context_protocol import (
    CallbackContextProtocol,
)
from .mock_database_runbook_mcp_tools import MockDatabaseRunbookMcpTools
from .mock_kubernetes_mcp_tools import MockKubernetesMcpTools
from .mock_mq_mcp_tools import MockMqMcpTools
from .mock_prometheus_mcp_tools import MockPrometheusMcpTools


class MockCapabilityProviderInvoker(CapabilityProviderInvoker):
    """Dispatch approved invocations to deterministic mock MCP providers."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='forbid',
        frozen=True,
    )

    kubernetes_mcp_tools: MockKubernetesMcpTools = Field(
        default_factory=MockKubernetesMcpTools,
        description='Mock Kubernetes MCP provider implementation.',
    )
    prometheus_mcp_tools: MockPrometheusMcpTools = Field(
        default_factory=MockPrometheusMcpTools,
        description='Mock Prometheus MCP provider implementation.',
    )
    mq_mcp_tools: MockMqMcpTools = Field(
        default_factory=MockMqMcpTools,
        description='Mock MQ MCP provider implementation.',
    )
    database_runbook_mcp_tools: MockDatabaseRunbookMcpTools = Field(
        default_factory=MockDatabaseRunbookMcpTools,
        description='Mock database runbook MCP provider implementation.',
    )

    def supported_provider_names(self) -> tuple[str, ...]:
        """Return deterministic provider names implemented by this mock."""
        return (
            'mock-kubernetes-mcp',
            'mock-prometheus-mcp',
            'mock-mq-mcp',
            'mock-database-runbook-mcp',
        )

    async def invoke(
        self,
        provider_name: str,
        tool_name: str,
        tool_arguments: dict[str, JsonValue],
        tool_context: CallbackContextProtocol,
    ) -> dict[str, object]:
        """Invoke an approved deterministic mock provider tool.

        Args:
            provider_name: Provider selected by capability resolution.
            tool_name: Concrete tool selected by capability resolution.
            tool_arguments: Prepared arguments controlled by the catalogue.
            tool_context: Active context, unused by deterministic mocks.

        Returns:
            Deterministic evidence from the selected mock provider tool.

        Raises:
            LookupError: If the selected provider and tool pair is not exposed
                by this mock invoker.
            TypeError: If prepared arguments do not match the mock tool's
                callable signature.
        """
        del tool_context
        provider_tool = (provider_name, tool_name)

        if provider_tool == ('mock-kubernetes-mcp', 'resources_list'):
            return self.kubernetes_mcp_tools.resources_list(**tool_arguments)
        if provider_tool == ('mock-kubernetes-mcp', 'pods_log'):
            return self.kubernetes_mcp_tools.pods_log(**tool_arguments)
        if provider_tool == ('mock-kubernetes-mcp', 'events_list'):
            return self.kubernetes_mcp_tools.events_list(**tool_arguments)
        if provider_tool == ('mock-prometheus-mcp', 'query_range'):
            return self.prometheus_mcp_tools.query_range(**tool_arguments)
        if provider_tool == ('mock-mq-mcp', 'run_mqsc'):
            return self.mq_mcp_tools.run_mqsc(**tool_arguments)
        if provider_tool == (
            'mock-database-runbook-mcp',
            'search_runbooks',
        ):
            return self.database_runbook_mcp_tools.search_runbooks(
                **tool_arguments
            )
        if provider_tool == (
            'mock-database-runbook-mcp',
            'read_runbook',
        ):
            return self.database_runbook_mcp_tools.read_runbook(
                **tool_arguments
            )

        raise LookupError(
            'The selected capability provider tool is not available.'
        )
