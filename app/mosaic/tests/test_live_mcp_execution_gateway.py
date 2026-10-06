import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from mosaic.components.capabilities.ada_mcp_capability_provider_invoker import AdaMcpCapabilityProviderInvoker
from mosaic.components.capabilities.capability_catalogue_and_resolver import CapabilityCatalogueAndResolver
from mosaic.components.capabilities.mcp_execution_gateway import MCPExecutionGateway
from mosaic.models.capabilities.capability import Capability
from mosaic.models.capabilities.capability_argument_binding import CapabilityArgumentBinding
from mosaic.models.capabilities.capability_provider_binding import CapabilityProviderBinding
from mosaic.models.capabilities.capability_result_binding import CapabilityResultBinding
from mosaic.models.capabilities.mcp_provider_configuration import McpProviderConfiguration
from mosaic.models.capabilities.provider_routing_configuration import ProviderRoutingConfiguration


class TestLiveMCPExecutionGateway(unittest.IsolatedAsyncioTestCase):
    async def test_declared_collection_is_counted_behind_gateway(self) -> None:
        tool = SimpleNamespace(
            name='objects_list',
            run_async=AsyncMock(
                return_value={
                    'content': [
                        {
                            'type': 'text',
                            'text': '- {name: a}\n- {name: b}\n',
                        }
                    ],
                    'isError': False,
                }
            ),
        )
        toolset = SimpleNamespace(
            get_tools=AsyncMock(return_value=[tool]),
            close=AsyncMock(),
        )
        constructors = self._sdk_constructors(toolset)
        gateway = self._gateway()
        context = self._context()

        with (
            patch.dict(sys.modules, constructors['modules']),
            self.assertLogs(
                'mosaic.capability_execution',
                level='INFO',
            ) as captured_logs,
        ):
            result = await gateway.execute_capability(
                capability_name='inventory.objects.count',
                semantic_arguments={
                    'scope': 'payments',
                    'object_name': 'invoice-api',
                },
                tool_context=context,
            )

        self.assertEqual(result['status'], 'success')
        self.assertEqual(
            result['evidence'],
            {'scope': 'payments', 'object_count': 2},
        )
        constructors['toolset_constructor'].assert_called_once_with(
            connection_params=constructors['connection_params'],
            header_provider=constructors['get_headers'],
            tool_filter=['objects_list'],
        )
        tool.run_async.assert_awaited_once_with(
            args={
                'scope': 'payments',
                'selector': 'object.name=invoice-api',
            },
            tool_context=context,
        )
        toolset.close.assert_awaited_once()
        events = [
            record.mosaic_event
            for record in captured_logs.records
        ]
        self.assertEqual(
            events,
            [
                'capability_provider_invocation_started',
                'capability_execution_completed',
            ],
        )
        completed_record = captured_logs.records[1]
        self.assertEqual(completed_record.mcp_content_block_count, 1)
        self.assertEqual(completed_record.content_source, 'text_content')
        self.assertEqual(completed_record.result_operation, 'count')
        self.assertNotIn(
            'payments',
            completed_record.__dict__.values(),
        )

    async def test_oversized_evidence_has_an_explicit_outcome(self) -> None:
        tool = SimpleNamespace(
            name='objects_list',
            run_async=AsyncMock(
                return_value={
                    'content': [{'type': 'text', 'text': 'too-large'}],
                    'isError': False,
                }
            ),
        )
        toolset = SimpleNamespace(
            get_tools=AsyncMock(return_value=[tool]),
            close=AsyncMock(),
        )
        constructors = self._sdk_constructors(toolset)

        with (
            patch.dict(sys.modules, constructors['modules']),
            self.assertLogs(
                'mosaic.capability_execution',
                level='ERROR',
            ) as captured_logs,
        ):
            result = await self._gateway(
                maximum_response_characters=3,
            ).execute_capability(
                capability_name='inventory.objects.count',
                semantic_arguments={'scope': 'payments'},
                tool_context=self._context(),
            )

        self.assertEqual(result['status'], 'evidence_too_large')
        self.assertEqual(
            result['error_message'],
            'Capability provider evidence exceeded its governed limit.',
        )
        self.assertEqual(
            captured_logs.records[0].execution_status,
            'evidence_too_large',
        )
        toolset.close.assert_awaited_once()

    def _gateway(
        self,
        maximum_response_characters: int = 1000,
    ) -> MCPExecutionGateway:
        configuration = McpProviderConfiguration(
            provider_name='inventory-mcp',
            provider_type='inventory',
            transport='streamable_http',
            header_strategy='ada_request_context',
            base_url='https://inventory.example/mcp',
            allowed_tool_names=('objects_list',),
            routing=ProviderRoutingConfiguration(
                mode='target_independent',
            ),
        )
        capability = Capability(
            name='inventory.objects.count',
            description='Count externally managed objects in one scope.',
            provider_bindings=(
                CapabilityProviderBinding(
                    provider_type='inventory',
                    tool_name='objects_list',
                    argument_bindings=(
                        CapabilityArgumentBinding(
                            tool_argument_name='scope',
                            source='semantic',
                            semantic_argument_names=('scope',),
                        ),
                        CapabilityArgumentBinding(
                            tool_argument_name='selector',
                            source='template',
                            semantic_argument_names=('object_name',),
                            value_template='object.name={object_name}',
                            semantic_argument_patterns={
                                'object_name': (
                                    r'[a-z0-9](?:[-a-z0-9.]{0,251}[a-z0-9])?'
                                )
                            },
                            required=False,
                        ),
                    ),
                    result_binding=CapabilityResultBinding(
                        content_source='text_content',
                        content_media_type='application/yaml',
                        content_block_index=0,
                        json_pointer='',
                        operation='count',
                        output_field='object_count',
                        evidence_tool_argument_names=('scope',),
                        maximum_response_characters=(
                            maximum_response_characters
                        ),
                        maximum_collection_items=10,
                    ),
                ),
            ),
        )
        return MCPExecutionGateway(
            capability_catalogue_and_resolver=CapabilityCatalogueAndResolver(
                capabilities=(capability,),
                providers=(configuration,),
            ),
            provider_invoker=AdaMcpCapabilityProviderInvoker(
                configuration=configuration,
                agent_identifier='mosaic-test',
            ),
        )

    def _context(self) -> SimpleNamespace:
        return SimpleNamespace(
            invocation_id='invocation-1',
            session=SimpleNamespace(id='test-session'),
            state={},
        )

    def _sdk_constructors(
        self,
        toolset: SimpleNamespace,
    ) -> dict[str, object]:
        get_headers = Mock(name='get_headers')
        header_provider_constructor = Mock(
            return_value=SimpleNamespace(get_headers=get_headers)
        )
        connection_params = object()
        connection_params_constructor = Mock(return_value=connection_params)
        toolset_constructor = Mock(return_value=toolset)

        header_module = ModuleType('ada_sdk.mcp.mcp_header_provider')
        header_module.MCPHeaderProvider = header_provider_constructor
        mcp_tool_module = ModuleType('google.adk.tools.mcp_tool')
        mcp_tool_module.McpToolset = toolset_constructor
        mcp_tool_module.StreamableHTTPConnectionParams = (
            connection_params_constructor
        )
        return {
            'modules': {
                'ada_sdk': ModuleType('ada_sdk'),
                'ada_sdk.mcp': ModuleType('ada_sdk.mcp'),
                'ada_sdk.mcp.mcp_header_provider': header_module,
                'google': ModuleType('google'),
                'google.adk': ModuleType('google.adk'),
                'google.adk.tools': ModuleType('google.adk.tools'),
                'google.adk.tools.mcp_tool': mcp_tool_module,
            },
            'get_headers': get_headers,
            'connection_params': connection_params,
            'toolset_constructor': toolset_constructor,
        }


if __name__ == '__main__':
    unittest.main()
