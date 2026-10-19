import sys
import unittest
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from mosaic.components.orchestration.mosaic_agent_callbacks import MosaicAgentCallbacks
from mosaic.components.orchestration.orchestration_transition_controller import OrchestrationTransitionController
from mosaic.components.skills.session_skill_profile_manager import SessionSkillProfileManager
from mosaic.components.skills.session_skill_profile_resolver import SessionSkillProfileResolver
from mosaic.models.orchestration.orchestration_state import OrchestrationState
from mosaic.models.skills.session_skill_profile_configuration import SessionSkillProfileConfiguration
from mosaic.models.skills.skill import Skill
from mosaic.models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot
from mosaic.tests.fake_llm_response import FakeLlmResponse


class TestOrchestrationClarification(unittest.TestCase):
    def setUp(self) -> None:
        self.controller = OrchestrationTransitionController()
        self.callbacks = MosaicAgentCallbacks(
            orchestration_controller=self.controller,
            profile_manager=SessionSkillProfileManager(
                resolver=SessionSkillProfileResolver(
                    configuration=SessionSkillProfileConfiguration(
                        profiles={'test': ('inspect-mq',)},
                        default_profile_id='test',
                    ),
                    catalogue_snapshot=SkillCatalogueSnapshot(
                        commit_sha='a' * 40,
                        loaded_at=datetime.now(timezone.utc),
                        skills=(
                            Skill(
                                name='inspect-mq',
                                version='1.0.0',
                                kind='procedural',
                                description='Inspect a fictional MQ platform.',
                                instruction='Check queue-manager health.',
                                required_capability_names=('mq.qmgr.status.read',),
                            ),
                        ),
                    ),
                )
            ),
        )
        self.context = SimpleNamespace(
            invocation_id='invocation-1',
            session=SimpleNamespace(id='test-session'),
            state={},
        )
        self.callbacks.before_agent_callback(self.context)
        self._tool('discover_skills', {}, {'status': 'available'})
        self._tool(
            'load_skills',
            {'skill_names': ['inspect-mq']},
            {
                'status': 'loaded',
                'loaded_skills': [
                    {
                        'name': 'inspect-mq',
                        'required_capability_names': ['mq.qmgr.status.read'],
                    }
                ],
            },
        )

    def test_unresolved_targets_end_with_a_question_without_model_inference(self) -> None:
        for status in ('target_required', 'target_unknown', 'target_ambiguous'):
            with self.subTest(status=status):
                self.setUp()
                self._tool(
                    'discover_capabilities',
                    {},
                    {
                        'status': status,
                        'candidate_targets': [
                            {'target_id': 'messaging/example-a', 'display_name': 'Example A'},
                            {'target_id': 'messaging/example-b', 'display_name': 'Example B'},
                        ],
                    },
                )
                self.assertEqual(self._state().phase, 'awaiting_clarification')
                self.assertFalse(self._state().capability_discovery_attempted)
                response = self._question_response()
                self.assertFalse(response.get_function_calls())
                self.assertEqual(
                    response.content.parts[0].text,
                    self._state().clarification_question,
                )
                if status == 'target_ambiguous':
                    self.assertIn('Example A', response.content.parts[0].text)
                    self.assertIn('Example B', response.content.parts[0].text)
                self.assertIsNone(
                    self.callbacks.after_model_callback(self.context, response)
                )
                self.callbacks.after_agent_callback(self.context)
                self.assertEqual(self._state().required_capability_outcomes, {})

    def test_target_reply_resumes_the_same_goal_and_executes_required_check(self) -> None:
        goal_id = self._state().goal_id
        self._tool('discover_capabilities', {}, {'status': 'target_required'})
        self._question_response()
        self.callbacks.after_agent_callback(self.context)
        self._resume()
        self.assertEqual(self._state().goal_id, goal_id)
        self.assertEqual(self._state().loaded_skill_names, ('inspect-mq',))
        self.assertIsNone(self._question_response())
        self._discover()
        self._tool(
            'execute_capability',
            {'capability_name': 'mq.qmgr.status.read'},
            {'status': 'success', 'target_id': 'messaging/example'},
        )
        self.callbacks.after_agent_callback(self.context)
        self.assertEqual(self._state().phase, 'completed')

    def test_missing_arguments_pause_and_resume_without_rediscovery(self) -> None:
        self._discover()
        goal_id = self._state().goal_id
        self._tool(
            'execute_capability',
            {'capability_name': 'mq.qmgr.status.read'},
            {
                'status': 'missing_arguments',
                'target_id': 'messaging/example',
                'missing_semantic_argument_names': ['queue_manager_name'],
            },
        )
        self.assertIn('queue manager name', self._question_response().content.parts[0].text)
        self.assertEqual(self._state().required_capability_outcomes, {})
        self.callbacks.after_agent_callback(self.context)
        self._resume()
        self.assertEqual(self._state().goal_id, goal_id)
        self.assertEqual(self._state().target_id, 'messaging/example')
        self.assertTrue(self._state().capability_discovery_completed)
        self.assertEqual(
            self.controller.incomplete_required_capability_names(self.context),
            ('mq.qmgr.status.read',),
        )
        self._tool(
            'execute_capability',
            {
                'capability_name': 'mq.qmgr.status.read',
                'semantic_arguments': {'queue_manager_name': 'EXAMPLE'},
            },
            {'status': 'success', 'target_id': 'messaging/example'},
        )
        self.callbacks.after_agent_callback(self.context)
        self.assertEqual(self._state().phase, 'completed')

    def test_paused_goal_blocks_tools_and_preserves_its_question(self) -> None:
        self._tool('discover_capabilities', {}, {'status': 'target_required'})
        question = self._state().clarification_question
        for name in ('discover_capabilities', 'execute_capability', 'request_goal_clarification'):
            tool = SimpleNamespace(name=name)
            blocked = self.controller.before_tool_callback(tool, {}, self.context)
            self.assertEqual(blocked['status'], 'blocked_awaiting_clarification')
            self.controller.after_tool_callback(tool, {}, self.context, blocked)
        self.assertEqual(self._state().clarification_question, question)

    def test_explicit_clarification_also_skips_further_inference(self) -> None:
        self._tool(
            'request_goal_clarification',
            {'question': 'Which queue manager should I check?'},
            {'status': 'awaiting_clarification'},
        )
        self.assertEqual(
            self._question_response().content.parts[0].text,
            'Which queue manager should I check?',
        )

    def test_in_flight_completion_is_retained_during_a_clarification_pause(self) -> None:
        self._discover()
        tool = SimpleNamespace(name='execute_capability')
        args = {'capability_name': 'mq.qmgr.status.read'}
        self.assertIsNone(self.controller.before_tool_callback(tool, args, self.context))
        self._tool(
            'request_goal_clarification',
            {'question': 'Which additional information should I use?'},
            {'status': 'awaiting_clarification'},
        )
        self.controller.after_tool_callback(
            tool,
            args,
            self.context,
            {'status': 'success', 'target_id': 'messaging/example'},
        )
        self.assertEqual(self._state().phase, 'awaiting_clarification')
        self.assertEqual(
            self._state().required_capability_outcomes,
            {'mq.qmgr.status.read': 'success'},
        )

    def test_premature_answers_still_require_execution(self) -> None:
        self._discover()
        response = FakeLlmResponse(
            content=SimpleNamespace(
                parts=[SimpleNamespace(text='Everything is healthy.', function_call=None)]
            )
        )
        replacement = self.callbacks.after_model_callback(self.context, response)
        self.assertEqual(replacement.get_function_calls()[0].name, 'continue_goal_execution')

    def test_invalid_arguments_are_not_automatically_treated_as_missing(self) -> None:
        self._discover()
        self._tool(
            'execute_capability',
            {'capability_name': 'mq.qmgr.status.read'},
            {
                'status': 'invalid_arguments',
                'target_id': 'messaging/example',
                'invalid_semantic_argument_names': ['queue_manager_name'],
            },
        )
        self.assertIsNone(self.controller.pending_clarification_question(self.context))
        self.assertEqual(self._state().required_capability_outcomes, {})

    def test_unbound_execution_cannot_create_a_clarification_pause(self) -> None:
        self._discover()
        self.controller.after_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'mq.other.read'},
            self.context,
            {
                'status': 'missing_arguments',
                'target_id': 'messaging/example',
                'missing_semantic_argument_names': ['queue_manager_name'],
            },
        )
        self.assertIsNone(self.controller.pending_clarification_question(self.context))

    def test_wrong_target_result_cannot_create_a_clarification_pause(self) -> None:
        self._discover()
        self._tool(
            'execute_capability',
            {'capability_name': 'mq.qmgr.status.read'},
            {
                'status': 'missing_arguments',
                'target_id': 'messaging/other',
                'missing_semantic_argument_names': ['queue_manager_name'],
            },
        )
        self.assertIsNone(self.controller.pending_clarification_question(self.context))

    def _tool(
        self,
        name: str,
        args: dict[str, object],
        response: dict[str, object],
    ) -> None:
        tool = SimpleNamespace(name=name)
        self.assertIsNone(self.controller.before_tool_callback(tool, args, self.context))
        self.controller.after_tool_callback(tool, args, self.context, response)

    def _discover(self) -> None:
        self._tool(
            'discover_capabilities',
            {'target_name': 'example'},
            {
                'status': 'available',
                'target': {'target_id': 'messaging/example', 'display_name': 'Example'},
                'capabilities': [{'name': 'mq.qmgr.status.read'}],
            },
        )

    def _question_response(self) -> FakeLlmResponse | None:
        models = ModuleType('google.adk.models')
        models.LlmResponse = FakeLlmResponse
        with patch.dict(sys.modules, {'google.adk.models': models}):
            return self.callbacks.before_model_callback(self.context, SimpleNamespace())

    def _resume(self) -> None:
        self.context = SimpleNamespace(
            invocation_id='invocation-2',
            session=self.context.session,
            state=self.context.state,
        )
        self.callbacks.before_agent_callback(self.context)

    def _state(self) -> OrchestrationState:
        return OrchestrationState.model_validate(self.context.state['mosaic:orchestration'])
