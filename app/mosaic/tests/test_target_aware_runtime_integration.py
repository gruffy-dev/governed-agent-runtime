import unittest
from types import SimpleNamespace

from mosaic.components.capabilities.capability_catalogue_and_resolver import CapabilityCatalogueAndResolver
from mosaic.components.capabilities.capability_discovery_service import CapabilityDiscoveryService
from mosaic.components.capabilities.mcp_execution_gateway import MCPExecutionGateway
from mosaic.components.capabilities.session_target_resolver import SessionTargetResolver
from mosaic.components.orchestration.ada_session_target_context_store import AdaSessionTargetContextStore
from mosaic.components.orchestration.orchestration_transition_controller import OrchestrationTransitionController
from mosaic.mocks.mock_ada_capability_catalogue import MockAdaCapabilityCatalogue
from mosaic.mocks.mock_capability_provider_invoker import MockCapabilityProviderInvoker
from mosaic.models.orchestration.orchestration_state import OrchestrationState


class TestTargetAwareRuntimeIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_clarification_resolution_execution_and_provenance(
        self,
    ) -> None:
        catalogue = MockAdaCapabilityCatalogue.create()
        capability_resolver = CapabilityCatalogueAndResolver(
            capabilities=catalogue.capabilities,
            providers=catalogue.providers,
        )
        target_store = AdaSessionTargetContextStore()
        discovery_service = CapabilityDiscoveryService(
            capability_catalogue_and_resolver=capability_resolver,
            session_target_resolver=SessionTargetResolver(
                targets=catalogue.targets,
                context_store=target_store,
            ),
        )
        gateway = MCPExecutionGateway(
            capability_catalogue_and_resolver=capability_resolver,
            provider_invoker=MockCapabilityProviderInvoker(),
        )
        controller = OrchestrationTransitionController()
        context = SimpleNamespace(
            invocation_id='invocation-1',
            session=SimpleNamespace(id='test-session'),
            state={},
        )
        controller.before_agent_callback(context)
        controller.after_tool_callback(
            SimpleNamespace(name='discover_skills'),
            {},
            context,
            {'status': 'available', 'skills': []},
        )
        controller.after_tool_callback(
            SimpleNamespace(name='load_skills'),
            {'skill_names': ['diagnose-events']},
            context,
            {
                'status': 'loaded',
                'loaded_skills': [
                    {
                        'name': 'diagnose-events',
                        'required_capability_names': [
                            'openshift.events.read'
                        ],
                    }
                ],
            },
        )

        unresolved = discovery_service.discover_capabilities(context)
        controller.after_tool_callback(
            SimpleNamespace(name='discover_capabilities'),
            {},
            context,
            unresolved,
        )

        self.assertEqual(unresolved['status'], 'target_required')
        self.assertFalse(self._state(context).capability_discovery_attempted)

        discovered = discovery_service.discover_capabilities(
            context,
            target_name='development',
        )
        controller.after_tool_callback(
            SimpleNamespace(name='discover_capabilities'),
            {'target_name': 'development'},
            context,
            discovered,
        )

        self.assertEqual(discovered['status'], 'available')
        self.assertEqual(self._state(context).target_id, 'openshift/dev')

        execution_result = await gateway.execute_capability(
            capability_name='openshift.events.read',
            semantic_arguments={
                'cluster_name': 'prod-east',
                'time_window_minutes': 30,
            },
            tool_context=context,
        )
        controller.after_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'openshift.events.read'},
            context,
            execution_result,
        )

        self.assertEqual(execution_result['status'], 'success')
        self.assertEqual(execution_result['target_id'], 'openshift/dev')
        self.assertEqual(
            self._state(context).required_capability_outcomes,
            {'openshift.events.read': 'success'},
        )

    def _state(self, context: SimpleNamespace) -> OrchestrationState:
        return OrchestrationState.model_validate(
            context.state['mosaic:orchestration']
        )


if __name__ == '__main__':
    unittest.main()
