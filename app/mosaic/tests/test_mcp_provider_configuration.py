import unittest

from pydantic import ValidationError

from mosaic.models.capabilities.mcp_provider_configuration import McpProviderConfiguration
from mosaic.models.capabilities.provider_routing_configuration import ProviderRoutingConfiguration


class TestMcpProviderConfiguration(unittest.TestCase):
    def test_explicit_provider_configuration_is_accepted(self) -> None:
        configuration = McpProviderConfiguration(
            provider_name='cluster-inventory',
            provider_type='inventory',
            transport='streamable_http',
            header_strategy='ada_request_context',
            base_url='https://inventory.example/mcp',
            allowed_tool_names=('objects_list',),
            routing=ProviderRoutingConfiguration(
                mode='target_independent',
            ),
        )

        self.assertEqual(configuration.provider_name, 'cluster-inventory')
        self.assertEqual(configuration.provider_type, 'inventory')
        self.assertEqual(configuration.allowed_tool_names, ('objects_list',))

    def test_omitted_provider_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            McpProviderConfiguration()

    def test_untrusted_tool_name_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            McpProviderConfiguration(
                provider_name='cluster-inventory',
                provider_type='inventory',
                transport='streamable_http',
                header_strategy='ada_request_context',
                base_url='https://inventory.example/mcp',
                allowed_tool_names=('objects-list',),
                routing=ProviderRoutingConfiguration(
                    mode='target_independent',
                ),
            )


if __name__ == '__main__':
    unittest.main()
