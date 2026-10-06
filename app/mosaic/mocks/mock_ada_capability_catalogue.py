"""Mock ADA capability metadata for the MOSAIC prototype."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from ..models.capabilities.capability import Capability
from ..models.capabilities.capability_argument_binding import CapabilityArgumentBinding
from ..models.capabilities.capability_provider_binding import CapabilityProviderBinding
from ..models.capabilities.mcp_provider_configuration import McpProviderConfiguration
from ..models.capabilities.provider_routing_configuration import ProviderRoutingConfiguration
from ..models.capabilities.target_definition import TargetDefinition


class MockAdaCapabilityCatalogue(BaseModel):
    """Provide deterministic ADA capability metadata without registry calls."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    capabilities: tuple[Capability, ...] = Field(
        description='Deterministic capability metadata for the prototype.',
        min_length=1,
    )
    targets: tuple[TargetDefinition, ...] = Field(
        description='Deterministic canonical targets for target-aware tests.',
        min_length=1,
    )
    providers: tuple[McpProviderConfiguration, ...] = Field(
        description='Deterministic provider configurations for tests.',
        min_length=1,
    )

    @classmethod
    def create(cls) -> Self:
        """Create the mock ADA capability catalogue.

        Returns:
            A validated catalogue containing read-only Kubernetes,
            Prometheus, MQ, and database runbook capability bindings.

        Raises:
            pydantic.ValidationError: If a mock capability or the resulting
                catalogue is invalid.
        """
        return cls(
            targets=(
                TargetDefinition(
                    id='openshift/dev',
                    display_name='Development OpenShift',
                    aliases=('dev', 'development'),
                ),
            ),
            providers=(
                McpProviderConfiguration(
                    provider_name='mock-kubernetes-mcp',
                    provider_type='kubernetes',
                    transport='streamable_http',
                    header_strategy='ada_request_context',
                    base_url='https://kubernetes.example/mcp',
                    allowed_tool_names=(
                        'resources_list',
                        'events_list',
                        'pods_log',
                    ),
                    routing=ProviderRoutingConfiguration(
                        mode='endpoint_per_target',
                        target_id='openshift/dev',
                    ),
                ),
                McpProviderConfiguration(
                    provider_name='mock-prometheus-mcp',
                    provider_type='observability',
                    transport='streamable_http',
                    header_strategy='ada_request_context',
                    base_url='https://observability.example/mcp',
                    allowed_tool_names=('query_range',),
                    routing=ProviderRoutingConfiguration(
                        mode='endpoint_per_target',
                        target_id='openshift/dev',
                    ),
                ),
                McpProviderConfiguration(
                    provider_name='mock-mq-mcp',
                    provider_type='mq',
                    transport='streamable_http',
                    header_strategy='ada_request_context',
                    base_url='https://mq.example/mcp',
                    allowed_tool_names=('run_mqsc',),
                    routing=ProviderRoutingConfiguration(
                        mode='target_independent',
                    ),
                ),
                McpProviderConfiguration(
                    provider_name='mock-database-runbook-mcp',
                    provider_type='database-runbook',
                    transport='streamable_http',
                    header_strategy='ada_request_context',
                    base_url='https://database.example/mcp',
                    allowed_tool_names=(
                        'search_runbooks',
                        'read_runbook',
                    ),
                    routing=ProviderRoutingConfiguration(
                        mode='target_independent',
                    ),
                ),
            ),
            capabilities=(
                Capability(
                    name='openshift.ingress.status.read',
                    description=(
                        'Read OpenShift ingress controller and router pod '
                        'status for a cluster.'
                    ),
                    provider_bindings=(
                        CapabilityProviderBinding(
                            provider_type='kubernetes',
                            tool_name='resources_list',
                            argument_bindings=(
                                CapabilityArgumentBinding(
                                    tool_argument_name='cluster_name',
                                    source='semantic',
                                    semantic_argument_names=('cluster_name',),
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='api_version',
                                    source='fixed',
                                    fixed_value='v1',
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='kind',
                                    source='fixed',
                                    fixed_value='Pod',
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='namespace',
                                    source='fixed',
                                    fixed_value='openshift-ingress',
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='label_selector',
                                    source='fixed',
                                    fixed_value=(
                                        'ingresscontroller.operator.'
                                        'openshift.io/deployment-'
                                        'ingresscontroller=default'
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                Capability(
                    name='openshift.events.read',
                    description=(
                        'Read recent OpenShift ingress events for a cluster.'
                    ),
                    provider_bindings=(
                        CapabilityProviderBinding(
                            provider_type='kubernetes',
                            tool_name='events_list',
                            argument_bindings=(
                                CapabilityArgumentBinding(
                                    tool_argument_name='cluster_name',
                                    source='semantic',
                                    semantic_argument_names=('cluster_name',),
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='namespace',
                                    source='fixed',
                                    fixed_value='openshift-ingress',
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='since_minutes',
                                    source='semantic',
                                    semantic_argument_names=(
                                        'time_window_minutes',
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                Capability(
                    name='openshift.router.logs.read',
                    description=(
                        'Read recent OpenShift router logs for a cluster.'
                    ),
                    provider_bindings=(
                        CapabilityProviderBinding(
                            provider_type='kubernetes',
                            tool_name='pods_log',
                            argument_bindings=(
                                CapabilityArgumentBinding(
                                    tool_argument_name='cluster_name',
                                    source='semantic',
                                    semantic_argument_names=('cluster_name',),
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='namespace',
                                    source='fixed',
                                    fixed_value='openshift-ingress',
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='pod_name',
                                    source='semantic',
                                    semantic_argument_names=('pod_name',),
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='since_minutes',
                                    source='semantic',
                                    semantic_argument_names=(
                                        'time_window_minutes',
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                Capability(
                    name='prometheus.ingress.metrics.read',
                    description=(
                        'Read latency, saturation, restart, and error metrics '
                        'for OpenShift ingress.'
                    ),
                    provider_bindings=(
                        CapabilityProviderBinding(
                            provider_type='observability',
                            tool_name='query_range',
                            argument_bindings=(
                                CapabilityArgumentBinding(
                                    tool_argument_name='cluster_name',
                                    source='semantic',
                                    semantic_argument_names=('cluster_name',),
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='query',
                                    source='fixed',
                                    fixed_value=(
                                        'mosaic:openshift_ingress_health'
                                    ),
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='time_window_minutes',
                                    source='semantic',
                                    semantic_argument_names=(
                                        'time_window_minutes',
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
                Capability(
                    name='mq.queue.depth.read',
                    description=(
                        'Read queue depth and open-handle status through an '
                        'approved MQ command tunnel.'
                    ),
                    provider_bindings=(
                        CapabilityProviderBinding(
                            provider_type='mq',
                            tool_name='run_mqsc',
                            argument_bindings=(
                                CapabilityArgumentBinding(
                                    tool_argument_name='queue_manager_name',
                                    source='semantic',
                                    semantic_argument_names=(
                                        'queue_manager_name',
                                    ),
                                    semantic_argument_patterns={
                                        'queue_manager_name': (
                                            r'[A-Z][A-Z0-9._]{0,47}'
                                        ),
                                    },
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='command',
                                    source='template',
                                    semantic_argument_names=('queue_name',),
                                    value_template=(
                                        'DISPLAY QSTATUS({queue_name}) '
                                        'TYPE(QUEUE) CURDEPTH MAXDEPTH '
                                        'IPPROCS OPPROCS'
                                    ),
                                    semantic_argument_patterns={
                                        'queue_name': r'[A-Z][A-Z0-9._]{0,47}',
                                    },
                                ),
                            ),
                        ),
                    ),
                ),
                Capability(
                    name='database.runbook.search',
                    description=(
                        'Search approved database runbooks using a natural-'
                        'language database request.'
                    ),
                    provider_bindings=(
                        CapabilityProviderBinding(
                            provider_type='database-runbook',
                            tool_name='search_runbooks',
                            argument_bindings=(
                                CapabilityArgumentBinding(
                                    tool_argument_name='query',
                                    source='semantic',
                                    semantic_argument_names=('request',),
                                ),
                            ),
                        ),
                    ),
                ),
                Capability(
                    name='database.runbook.read',
                    description=(
                        'Read one exact approved database runbook version '
                        'selected from search evidence.'
                    ),
                    provider_bindings=(
                        CapabilityProviderBinding(
                            provider_type='database-runbook',
                            tool_name='read_runbook',
                            argument_bindings=(
                                CapabilityArgumentBinding(
                                    tool_argument_name='runbook_id',
                                    source='semantic',
                                    semantic_argument_names=('runbook_id',),
                                    semantic_argument_patterns={
                                        'runbook_id': r'DB-RB-[0-9]{4}',
                                    },
                                ),
                                CapabilityArgumentBinding(
                                    tool_argument_name='version',
                                    source='semantic',
                                    semantic_argument_names=('version',),
                                    semantic_argument_patterns={
                                        'version': (
                                            r'(0|[1-9]\d*)\.'
                                            r'(0|[1-9]\d*)\.'
                                            r'(0|[1-9]\d*)'
                                        ),
                                    },
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
