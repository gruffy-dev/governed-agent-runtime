import unittest
from types import SimpleNamespace

from mosaic.components.orchestration.orchestration_transition_controller import OrchestrationTransitionController
from mosaic.models.orchestration.orchestration_state import OrchestrationState


class TestGoalOutcomeIsolation(unittest.TestCase):
    def test_previous_goal_outcomes_do_not_enter_new_goal(self) -> None:
        controller = OrchestrationTransitionController()
        context = SimpleNamespace(
            invocation_id='invocation-1',
            state={},
        )
        controller.before_agent_callback(context)
        first_state = OrchestrationState.model_validate(
            context.state[controller.state_key]
        )
        previous_records = {
            'cluster.status.read': (
                first_state.goal_id,
                'success',
            )
        }
        context.state[controller.state_key] = first_state.model_copy(
            update={
                'phase': 'completed',
                'skill_discovery_completed': True,
                'skill_batch_attempted': True,
                'skill_batch_loaded': True,
                'requested_skill_names': ('inspect-status',),
                'loaded_skill_names': ('inspect-status',),
                'required_capability_names': ('cluster.status.read',),
                'required_capability_outcome_records': previous_records,
            }
        ).model_dump(mode='json')

        context.invocation_id = 'invocation-2'
        controller.before_agent_callback(context)
        context.state[controller.state_key][
            'required_capability_outcome_records'
        ].update(previous_records)

        second_state = OrchestrationState.model_validate(
            context.state[controller.state_key]
        )
        self.assertNotEqual(second_state.goal_id, first_state.goal_id)
        self.assertEqual(second_state.required_capability_outcomes, {})
        self.assertEqual(
            second_state.required_capability_outcome_records,
            previous_records,
        )


if __name__ == '__main__':
    unittest.main()
