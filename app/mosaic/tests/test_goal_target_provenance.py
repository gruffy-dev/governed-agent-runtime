import unittest
from types import SimpleNamespace

from mosaic.components.capabilities.capability_execution_observability import CapabilityExecutionObservability
from mosaic.components.orchestration.orchestration_transition_controller import OrchestrationTransitionController
from mosaic.models.orchestration.orchestration_state import OrchestrationState


class TestGoalTargetProvenance(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = OrchestrationTransitionController()
        self.context = SimpleNamespace(
            invocation_id='invocation-1',
            session=SimpleNamespace(id='test-session'),
            state={},
        )

    def test_discovery_pins_target_to_goal(self) -> None:
        self._prepare_loaded_skill()

        self.controller.after_tool_callback(
            SimpleNamespace(name='discover_capabilities'),
            {'target_name': 'development'},
            self.context,
            {
                'status': 'available',
                'capabilities': [{'name': 'cluster.status.read'}],
                'target': {
                    'target_id': 'platform/development',
                    'display_name': 'Development platform',
                },
            },
        )

        state = self._state()
        self.assertEqual(state.target_id, 'platform/development')
        self.assertEqual(
            state.target_display_name,
            'Development platform',
        )

    def test_mismatched_execution_target_is_rejected(self) -> None:
        self._prepare_loaded_skill()
        self.controller.after_tool_callback(
            SimpleNamespace(name='discover_capabilities'),
            {'target_name': 'development'},
            self.context,
            {
                'status': 'available',
                'capabilities': [{'name': 'cluster.status.read'}],
                'target': {
                    'target_id': 'platform/development',
                    'display_name': 'Development platform',
                },
            },
        )

        with self.assertRaisesRegex(RuntimeError, 'does not match'):
            self.controller.after_tool_callback(
                SimpleNamespace(name='execute_capability'),
                {'capability_name': 'cluster.status.read'},
                self.context,
                {
                    'status': 'success',
                    'target_id': 'platform/production',
                },
            )

        self.assertEqual(self._state().required_capability_outcomes, {})

    def test_observability_records_canonical_target(self) -> None:
        observability = CapabilityExecutionObservability()

        with self.assertLogs(
            'mosaic.capability_execution',
            level='INFO',
        ) as captured_logs:
            observability.record(
                event='capability_execution_completed',
                capability_name='cluster.status.read',
                target_id='platform/development',
                provider_name='platform-mcp',
                tool_name='status_read',
                tool_context=self.context,
                execution_stage='completed',
                execution_status='success',
            )

        self.assertEqual(
            captured_logs.records[0].target_id,
            'platform/development',
        )

    def _prepare_loaded_skill(self) -> None:
        self.controller.before_agent_callback(self.context)
        self.controller.after_tool_callback(
            SimpleNamespace(name='discover_skills'),
            {},
            self.context,
            {'status': 'available', 'skills': []},
        )
        self.controller.after_tool_callback(
            SimpleNamespace(name='load_skills'),
            {'skill_names': ['diagnose']},
            self.context,
            {
                'status': 'loaded',
                'loaded_skills': [
                    {
                        'name': 'diagnose',
                        'required_capability_names': [
                            'cluster.status.read'
                        ],
                    }
                ],
            },
        )

    def _state(self) -> OrchestrationState:
        return OrchestrationState.model_validate(
            self.context.state[self.controller.state_key]
        )


if __name__ == '__main__':
    unittest.main()
