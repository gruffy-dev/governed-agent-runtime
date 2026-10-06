"""Tests for composed MOSAIC profile and orchestration callbacks."""

import sys
import unittest
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from mosaic.components.orchestration.mosaic_agent_callbacks import (
    MosaicAgentCallbacks,
)
from mosaic.components.orchestration.orchestration_transition_controller import (
    OrchestrationTransitionController,
)
from mosaic.components.skills.session_skill_profile_manager import (
    SessionSkillProfileManager,
)
from mosaic.components.skills.session_skill_profile_resolver import (
    SessionSkillProfileResolver,
)
from mosaic.models.skills.session_skill_profile_configuration import (
    SessionSkillProfileConfiguration,
)
from mosaic.models.skills.skill import Skill
from mosaic.models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot
from mosaic.tests.fake_llm_response import FakeLlmResponse


class TestMosaicAgentCallbacks(unittest.TestCase):
    """Verify profile binding precedes goal-state initialization."""

    def test_before_agent_binds_profile_and_starts_goal(self) -> None:
        """One callback persists both trusted session and goal state."""
        snapshot = SkillCatalogueSnapshot(
            commit_sha='a' * 40,
            loaded_at=datetime.now(timezone.utc),
            skills=(
                Skill(
                    name='match-database-runbook',
                    version='1.0.0',
                    kind='procedural',
                    description='Match an approved database runbook.',
                    instruction='Retrieve the exact approved runbook.',
                ),
            ),
        )
        resolver = SessionSkillProfileResolver(
            configuration=SessionSkillProfileConfiguration(
                profiles={
                    'database-demo': ('match-database-runbook',),
                },
                default_profile_id='database-demo',
            ),
            catalogue_snapshot=snapshot,
        )
        callbacks = MosaicAgentCallbacks(
            profile_manager=SessionSkillProfileManager(resolver=resolver),
            orchestration_controller=OrchestrationTransitionController(),
        )
        context = SimpleNamespace(
            invocation_id='invocation-1',
            session=SimpleNamespace(id='database-session'),
            state={},
        )

        callbacks.before_agent_callback(context)

        self.assertEqual(
            context.state['mosaic:skill-profile']['profile_id'],
            'database-demo',
        )
        self.assertEqual(
            context.state['mosaic:orchestration']['active_invocation_id'],
            'invocation-1',
        )

    def test_after_model_forces_incomplete_capability_execution(self) -> None:
        """Premature user output becomes an internal continuation call."""
        snapshot = SkillCatalogueSnapshot(
            commit_sha='a' * 40,
            loaded_at=datetime.now(timezone.utc),
            skills=(
                Skill(
                    name='diagnose',
                    version='1.0.0',
                    kind='procedural',
                    description='Diagnose a cluster.',
                    instruction='Inspect status and logs.',
                    required_capability_names=(
                        'cluster.status.read',
                        'cluster.logs.read',
                    ),
                ),
            ),
        )
        controller = OrchestrationTransitionController()
        callbacks = MosaicAgentCallbacks(
            profile_manager=SessionSkillProfileManager(
                resolver=SessionSkillProfileResolver(
                    configuration=SessionSkillProfileConfiguration(
                        profiles={'test': ('diagnose',)},
                        default_profile_id='test',
                    ),
                    catalogue_snapshot=snapshot,
                )
            ),
            orchestration_controller=controller,
        )
        context = SimpleNamespace(
            invocation_id='invocation-1',
            session=SimpleNamespace(id='test-session'),
            state={},
        )
        callbacks.before_agent_callback(context)
        controller.after_tool_callback(
            SimpleNamespace(name='discover_skills'),
            {},
            context,
            {'status': 'available'},
        )
        controller.after_tool_callback(
            SimpleNamespace(name='load_skills'),
            {'skill_names': ['diagnose']},
            context,
            {
                'status': 'loaded',
                'loaded_skills': [
                    {
                        'name': 'diagnose',
                        'required_capability_names': [
                            'cluster.status.read',
                            'cluster.logs.read',
                        ],
                    }
                ]
            },
        )
        controller.after_tool_callback(
            SimpleNamespace(name='discover_capabilities'),
            {},
            context,
            {
                'status': 'available',
                'capabilities': [
                    {'name': 'cluster.status.read'},
                    {'name': 'cluster.logs.read'},
                ],
            },
        )
        controller.after_tool_callback(
            SimpleNamespace(name='execute_capability'),
            {'capability_name': 'cluster.status.read'},
            context,
            {'status': 'success'},
        )
        premature_response = FakeLlmResponse(
            content=SimpleNamespace(
                parts=[
                    SimpleNamespace(
                        text='Premature result',
                        function_call=None,
                    )
                ]
            )
        )

        replacement = callbacks.after_model_callback(
            context,
            premature_response,
        )

        self.assertIsNotNone(replacement)
        function_call = replacement.get_function_calls()[0]
        self.assertEqual(function_call.name, 'continue_goal_execution')
        self.assertEqual(
            function_call.args['missing_required_capability_names'],
            ['cluster.logs.read'],
        )

    def test_before_model_forces_skill_discovery_for_a_new_goal(self) -> None:
        """The first inference is replaced with automatic skill discovery."""
        snapshot = SkillCatalogueSnapshot(
            commit_sha='a' * 40,
            loaded_at=datetime.now(timezone.utc),
            skills=(
                Skill(
                    name='diagnose',
                    version='1.0.0',
                    kind='procedural',
                    description='Diagnose a cluster.',
                    instruction='Inspect status.',
                ),
            ),
        )
        callbacks = MosaicAgentCallbacks(
            profile_manager=SessionSkillProfileManager(
                resolver=SessionSkillProfileResolver(
                    configuration=SessionSkillProfileConfiguration(
                        profiles={'test': ('diagnose',)},
                        default_profile_id='test',
                    ),
                    catalogue_snapshot=snapshot,
                )
            ),
            orchestration_controller=OrchestrationTransitionController(),
        )
        context = SimpleNamespace(
            invocation_id='invocation-1',
            session=SimpleNamespace(id='test-session'),
            state={},
        )
        callbacks.before_agent_callback(context)
        fake_models = ModuleType('google.adk.models')
        fake_models.LlmResponse = FakeLlmResponse

        with patch.dict(sys.modules, {'google.adk.models': fake_models}):
            response = callbacks.before_model_callback(
                context,
                SimpleNamespace(),
            )

        self.assertIsNotNone(response)
        self.assertEqual(
            response.get_function_calls()[0].name,
            'discover_skills',
        )


if __name__ == '__main__':
    unittest.main()
