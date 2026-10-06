import unittest

from mosaic.components.capabilities.capability_catalogue_and_resolver import CapabilityCatalogueAndResolver
from mosaic.models.capabilities.capability import Capability
from mosaic.models.capabilities.capability_argument_binding import CapabilityArgumentBinding
from mosaic.models.capabilities.capability_provider_binding import CapabilityProviderBinding
from mosaic.models.capabilities.mcp_provider_configuration import McpProviderConfiguration
from mosaic.models.capabilities.provider_routing_configuration import ProviderRoutingConfiguration
from mosaic.models.capabilities.provider_target_binding import ProviderTargetBinding


class TestTargetAwareCapabilityResolution(unittest.TestCase):
    def test_endpoint_provider_is_selected_by_canonical_target(self) -> None:
        resolver = CapabilityCatalogueAndResolver(
            capabilities=(
                Capability(
                    name='platform.status.read',
                    description='Read platform status.',
                    provider_bindings=(
                        CapabilityProviderBinding(
                            provider_type='platform',
                            tool_name='status_read',
                        ),
                    ),
                ),
            ),
            providers=(
                self._endpoint_provider(
                    provider_name='platform-one',
                    target_id='platform/one',
                ),
                self._endpoint_provider(
                    provider_name='platform-two',
                    target_id='platform/two',
                ),
            ),
        )

        result = resolver.prepare_capability_invocation(
            capability_name='platform.status.read',
            semantic_arguments={},
            target_id='platform/two',
        )

        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['provider_name'], 'platform-two')

    def test_shared_target_argument_is_injected_and_cannot_be_overridden(
        self,
    ) -> None:
        provider = McpProviderConfiguration(
            provider_name='shared-platform',
            provider_type='platform',
            transport='streamable_http',
            header_strategy='ada_request_context',
            base_url='https://shared.example/mcp',
            allowed_tool_names=('resources_list',),
            routing=ProviderRoutingConfiguration(
                mode='shared_endpoint',
                target_argument_name='cluster_name',
                target_bindings=(
                    ProviderTargetBinding(
                        target_id='platform/one',
                        argument_value='internal-cluster-one',
                    ),
                    ProviderTargetBinding(
                        target_id='platform/two',
                        argument_value='internal-cluster-two',
                    ),
                ),
            ),
        )
        resolver = CapabilityCatalogueAndResolver(
            capabilities=(
                Capability(
                    name='platform.resources.read',
                    description='Read platform resources.',
                    provider_bindings=(
                        CapabilityProviderBinding(
                            provider_type='platform',
                            tool_name='resources_list',
                            argument_bindings=(
                                CapabilityArgumentBinding(
                                    tool_argument_name='namespace',
                                    source='semantic',
                                    semantic_argument_names=('namespace',),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
            providers=(provider,),
        )

        result = resolver.prepare_capability_invocation(
            capability_name='platform.resources.read',
            semantic_arguments={
                'namespace': 'payments',
                'cluster_name': 'attacker-controlled',
            },
            target_id='platform/two',
        )

        self.assertEqual(result['status'], 'ready')
        self.assertEqual(
            result['tool_arguments'],
            {
                'namespace': 'payments',
                'cluster_name': 'internal-cluster-two',
            },
        )
        self.assertEqual(
            result['ignored_semantic_argument_names'],
            ['cluster_name'],
        )

    def _endpoint_provider(
        self,
        provider_name: str,
        target_id: str,
    ) -> McpProviderConfiguration:
        return McpProviderConfiguration(
            provider_name=provider_name,
            provider_type='platform',
            transport='streamable_http',
            header_strategy='ada_request_context',
            base_url=f'https://{provider_name}.example/mcp',
            allowed_tool_names=('status_read',),
            routing=ProviderRoutingConfiguration(
                mode='endpoint_per_target',
                target_id=target_id,
            ),
        )


if __name__ == '__main__':
    unittest.main()
