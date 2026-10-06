"""Tests for ADA-session-backed orchestration transitions."""

import unittest
from copy import deepcopy
from types import SimpleNamespace

from mosaic.components.orchestration.concurrent_session_invocation_error import (
    ConcurrentSessionInvocationError,
)
from mosaic.components.orchestration.orchestration_transition_controller import (
    OrchestrationTransitionController,
)
from mosaic.models.orchestration.orchestration_state import OrchestrationState


class TestOrchestrationTransitionController(unittest.TestCase):
    """Verify goal lifecycle and tool-ordering invariants."""

    def setUp(self) -> None:
        """Create an isolated controller and ADA context for each test."""
        self.controller = OrchestrationTransitionController()
        self.context = SimpleNamespace(
            invocation_id='invocation-1',
            state={},
        )

    def test_skill_batch_can_be_loaded_only_once_per_goal(self) -> None:
        """A repeated skill-loading call is short-circuited safely."""
        self.controller.before_agent_callback(self.context)
        self._complete_skill_discovery()
        load_skills = SimpleNamespace(name='load_skills')
        args = {'skill_names': ['diagnose', 'report', 'diagnose']}
        response = {
            'status': 'loaded',
            'loaded_skills': [
                {'name': 'diagnose'},
                {'name': 'report'},
            ]
        }

        self.assertIsNone(
            self.controller.before_tool_callback(
                load_skills,
                args,
                self.context,
            )
        )
        self.controller.after_tool_callback(
            load_skills,
            args,
            self.context,
            response,
        )
        blocked = self.controller.before_tool_callback(
            load_skills,
            {'skill_names': ['another']},
            self.context,
        )
        self.controller.after_tool_callback(
            load_skills,
            {'skill_names': ['another']},
            self.context,
            blocked or {},
        )

        state = self._state()
        self.assertEqual(blocked['status'], 'skill_batch_already_attempted')
        self.assertEqual(
            state.requested_skill_names,
            ('diagnose', 'report'),
        )
        self.assertEqual(state.loaded_skill_names, ('diagnose', 'report'))

    def test_clarification_resumes_the_same_goal_and_skill_batch(self) -> None:
        """A clarification reply retains the goal and its loaded skills."""
        self.controller.before_agent_callback(self.context)
        self._complete_skill_discovery()
        load_skills = SimpleNamespace(name='load_skills')
        self.controller.after_tool_callback(
            load_skills,
            {'skill_names': ['diagnose']},
            self.context,
            {
                'status': 'loaded',
                'loaded_skills': [{'name': 'diagnose'}],
            },
        )
        clarification = SimpleNamespace(name='request_goal_clarification')
        self.controller.after_tool_callback(
            clarification,
            {'question': 'Which cluster?'},
            self.context,
            {'status': 'awaiting_clarification'},
        )
        original = self._state()
        self.controller.after_agent_callback(self.context)

        resumed_context = SimpleNamespace(
            invocation_id='invocation-2',
            state=self.context.state,
        )
        self.controller.before_agent_callback(resumed_context)
        resumed = self._state(resumed_context)
        blocked = self.controller.before_tool_callback(
            load_skills,
            {'skill_names': ['diagnose']},
            resumed_context,
        )

        self.assertEqual(resumed.goal_id, original.goal_id)
        self.assertEqual(resumed.phase, 'planning')
        self.assertTrue(resumed.skill_batch_loaded)
        self.assertEqual(blocked['status'], 'skill_batch_already_attempted')

    def test_completed_invocation_allows_a_new_goal(self) -> None:
        """The invocation after completion starts with clean goal state."""
        self.controller.before_agent_callback(self.context)
        first_goal_id = self._state().goal_id
        self._complete_skill_discovery()
        self.controller.after_agent_callback(self.context)

        next_context = SimpleNamespace(
            invocation_id='invocation-2',
            state=self.context.state,
        )
        self.controller.before_agent_callback(next_context)
        next_state = self._state(next_context)

        self.assertNotEqual(next_state.goal_id, first_goal_id)
        self.assertEqual(next_state.phase, 'planning')
        self.assertFalse(next_state.skill_discovery_completed)
        self.assertFalse(next_state.skill_batch_loaded)

    def test_goal_tools_require_discovery(self) -> None:
        """Goal tools fail closed before authorised skill discovery."""
        self.controller.before_agent_callback(self.context)

        blocked_load = self.controller.before_tool_callback(
            SimpleNamespace(name='load_skills'),
            {'skill_names': ['diagnose']},
            self.context,
        )
        blocked_execution = self.controller.before_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'cluster.status.read'},
            self.context,
        )
        blocked_clarification = self.controller.before_tool_callback(
            SimpleNamespace(name='request_goal_clarification'),
            {'question': 'Which cluster?'},
            self.context,
        )

        self.assertEqual(blocked_load['status'], 'skill_discovery_required')
        self.assertEqual(
            blocked_execution['status'],
            'skill_discovery_required',
        )
        self.assertEqual(
            blocked_clarification['status'],
            'skill_discovery_required',
        )

    def test_skill_discovery_can_complete_only_once_per_goal(self) -> None:
        """A repeated skill-discovery call is short-circuited safely."""
        self.controller.before_agent_callback(self.context)
        self._complete_skill_discovery()

        blocked = self.controller.before_tool_callback(
            SimpleNamespace(name='discover_skills'),
            {},
            self.context,
        )

        self.assertEqual(
            blocked['status'],
            'skill_discovery_already_completed',
        )

    def test_execution_is_limited_to_goal_capability_candidates(self) -> None:
        """Execution is blocked before discovery and outside its candidate set."""
        self.controller.before_agent_callback(self.context)
        self._complete_skill_discovery()
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
                        'optional_capability_names': ['cluster.logs.read'],
                    }
                ],
            },
        )

        loaded_state = self._state()
        before_discovery = self.controller.before_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'cluster.status.read'},
            self.context,
        )
        self._complete_capability_discovery(
            ('cluster.status.read', 'cluster.logs.read')
        )
        optional_candidate = self.controller.before_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'cluster.logs.read'},
            self.context,
        )
        outside_candidates = self.controller.before_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'cluster.metrics.read'},
            self.context,
        )

        self.assertEqual(
            loaded_state.required_capability_names,
            ('cluster.status.read',),
        )
        self.assertEqual(
            loaded_state.optional_capability_names,
            ('cluster.logs.read',),
        )
        self.assertEqual(
            before_discovery['status'],
            'capability_discovery_required',
        )
        self.assertIsNone(optional_candidate)
        self.assertEqual(
            outside_candidates['status'],
            'capability_not_authorized_for_goal',
        )

    def test_capability_tools_require_a_loaded_skill(self) -> None:
        """Capability access cannot bypass the selected skill boundary."""
        self.controller.before_agent_callback(self.context)
        self._complete_skill_discovery()

        blocked_discovery = self.controller.before_tool_callback(
            SimpleNamespace(name='discover_capabilities'),
            {},
            self.context,
        )
        blocked_execution = self.controller.before_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'cluster.status.read'},
            self.context,
        )

        self.assertEqual(
            blocked_discovery['status'],
            'capability_skill_required',
        )
        self.assertEqual(
            blocked_execution['status'],
            'capability_skill_required',
        )

    def test_capability_discovery_limit_is_a_terminal_limitation(self) -> None:
        """A fail-closed discovery limit does not create a continuation loop."""
        self.controller.before_agent_callback(self.context)
        self._complete_skill_discovery()
        self.controller.after_tool_callback(
            SimpleNamespace(name='load_skills'),
            {'skill_names': ['diagnose']},
            self.context,
            {
                'status': 'loaded',
                'loaded_skills': [
                    {
                        'name': 'diagnose',
                        'required_capability_names': ['cluster.status.read'],
                    }
                ],
            },
        )
        self.controller.after_tool_callback(
            SimpleNamespace(name='discover_capabilities'),
            {},
            self.context,
            {'status': 'limit_exceeded', 'capabilities': []},
        )

        self.assertEqual(
            self.controller.incomplete_required_capability_names(self.context),
            (),
        )
        self.controller.after_agent_callback(self.context)
        self.assertEqual(self._state().phase, 'completed')

    def test_agent_cannot_end_with_required_capability_incomplete(self) -> None:
        """Incomplete execution cannot be mislabeled as clarification."""
        self.controller.before_agent_callback(self.context)
        self._complete_skill_discovery()
        load_skills = SimpleNamespace(name='load_skills')
        self.controller.after_tool_callback(
            load_skills,
            {'skill_names': ['diagnose']},
            self.context,
            {
                'status': 'loaded',
                'loaded_skills': [
                    {
                        'name': 'diagnose',
                        'required_capability_names': ['cluster.status.read'],
                    }
                ]
            },
        )
        with self.assertRaisesRegex(
            RuntimeError,
            'cluster.status.read',
        ):
            self.controller.after_agent_callback(self.context)

        self.assertEqual(self._state().phase, 'executing')

    def test_missing_capability_arguments_remain_incomplete(self) -> None:
        """Only a terminal capability result completes a requirement."""
        self.controller.before_agent_callback(self.context)
        self._complete_skill_discovery()
        load_skills = SimpleNamespace(name='load_skills')
        execute_capability = SimpleNamespace(name='execute_capability')
        self.controller.after_tool_callback(
            load_skills,
            {'skill_names': ['diagnose']},
            self.context,
            {
                'status': 'loaded',
                'loaded_skills': [
                    {
                        'name': 'diagnose',
                        'required_capability_names': ['cluster.status.read'],
                    }
                ]
            },
        )
        self._complete_capability_discovery(('cluster.status.read',))
        capability_args = {'capability_name': 'cluster.status.read'}
        self.controller.after_tool_callback(
            execute_capability,
            capability_args,
            self.context,
            {'status': 'missing_arguments'},
        )
        self.assertEqual(
            self.controller.incomplete_required_capability_names(
                self.context
            ),
            ('cluster.status.read',),
        )
        clarification = SimpleNamespace(name='request_goal_clarification')
        self.controller.after_tool_callback(
            clarification,
            {'question': 'Which cluster?'},
            self.context,
            {'status': 'awaiting_clarification'},
        )
        self.controller.after_agent_callback(self.context)

        self.assertEqual(self._state().phase, 'awaiting_clarification')

        resumed_context = SimpleNamespace(
            invocation_id='invocation-2',
            state=self.context.state,
        )
        self.controller.before_agent_callback(resumed_context)
        self.controller.after_tool_callback(
            execute_capability,
            capability_args,
            resumed_context,
            {'status': 'success'},
        )
        self.controller.after_agent_callback(resumed_context)

        self.assertEqual(self._state(resumed_context).phase, 'completed')

    def test_oversized_required_evidence_is_terminal(self) -> None:
        """An oversized result records completion without causing a loop."""
        self.controller.before_agent_callback(self.context)
        self._complete_skill_discovery()
        self.controller.after_tool_callback(
            SimpleNamespace(name='load_skills'),
            {'skill_names': ['diagnose']},
            self.context,
            {
                'status': 'loaded',
                'loaded_skills': [
                    {
                        'name': 'diagnose',
                        'required_capability_names': ['cluster.events.read'],
                    }
                ],
            },
        )
        self._complete_capability_discovery(('cluster.events.read',))
        self.controller.after_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'cluster.events.read'},
            self.context,
            {'status': 'evidence_too_large'},
        )
        self.controller.after_agent_callback(self.context)

        state = self._state()
        self.assertEqual(state.phase, 'completed')
        self.assertEqual(
            state.required_capability_outcomes,
            {'cluster.events.read': 'evidence_too_large'},
        )
        self.assertEqual(
            self.controller.required_capability_limitations(self.context),
            {'cluster.events.read': 'evidence_too_large'},
        )

    def test_parallel_required_completions_are_independently_mergeable(
        self,
    ) -> None:
        """Parallel terminal outcomes survive recursive state-delta merging."""
        self.controller.before_agent_callback(self.context)
        self._complete_skill_discovery()
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
                            'cluster.status.read',
                            'cluster.events.read',
                        ],
                    }
                ],
            },
        )
        self._complete_capability_discovery(
            ('cluster.status.read', 'cluster.events.read')
        )
        initial_state = deepcopy(self.context.state)
        status_context = SimpleNamespace(
            invocation_id='invocation-1',
            state=deepcopy(initial_state),
        )
        events_context = SimpleNamespace(
            invocation_id='invocation-1',
            state=deepcopy(initial_state),
        )

        self.controller.after_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'cluster.status.read'},
            status_context,
            {'status': 'success'},
        )
        self.controller.after_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'cluster.events.read'},
            events_context,
            {'status': 'evidence_too_large'},
        )

        status_outcomes = self._state(
            status_context
        ).required_capability_outcomes
        event_outcomes = self._state(
            events_context
        ).required_capability_outcomes
        merged_outcomes = {
            **status_outcomes,
            **event_outcomes,
        }

        self.assertEqual(
            merged_outcomes,
            {
                'cluster.status.read': 'success',
                'cluster.events.read': 'evidence_too_large',
            },
        )

    def test_overlapping_invocation_fails_closed(self) -> None:
        """A detected concurrent invocation cannot replace active state."""
        self.controller.before_agent_callback(self.context)
        overlapping_context = SimpleNamespace(
            invocation_id='invocation-2',
            state=self.context.state,
        )

        with self.assertRaises(ConcurrentSessionInvocationError):
            self.controller.before_agent_callback(overlapping_context)

    def _complete_skill_discovery(
        self,
        context: SimpleNamespace | None = None,
    ) -> None:
        """Record successful authorised skill discovery for a fake context."""
        selected_context = context or self.context
        discover_skills = SimpleNamespace(name='discover_skills')
        self.controller.after_tool_callback(
            discover_skills,
            {},
            selected_context,
            {'status': 'available', 'skills': []},
        )

    def _complete_capability_discovery(
        self,
        capability_names: tuple[str, ...],
        context: SimpleNamespace | None = None,
    ) -> None:
        """Record one successful goal-scoped capability discovery."""
        selected_context = context or self.context
        self.controller.after_tool_callback(
            SimpleNamespace(name='discover_capabilities'),
            {},
            selected_context,
            {
                'status': 'available' if capability_names else 'none_available',
                'capabilities': [
                    {'name': capability_name}
                    for capability_name in capability_names
                ],
            },
        )

    def _state(
        self,
        context: SimpleNamespace | None = None,
    ) -> OrchestrationState:
        """Return validated state from the selected fake ADA context."""
        selected_context = context or self.context
        return OrchestrationState.model_validate(
            selected_context.state[self.controller.state_key]
        )


if __name__ == '__main__':
    unittest.main()
