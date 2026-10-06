"""Tests for generic structured output validation."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from mosaic.components.skills.google_gen_ai_response_schema_adapter import (
    GoogleGenAiResponseSchemaAdapter,
)
from mosaic.components.skills.session_skill_profile_manager import (
    SessionSkillProfileManager,
)
from mosaic.components.skills.session_skill_profile_resolver import (
    SessionSkillProfileResolver,
)
from mosaic.components.skills.structured_output_validator import (
    StructuredOutputValidator,
)
from mosaic.models.orchestration.orchestration_state import OrchestrationState
from mosaic.models.skills.session_skill_profile_configuration import (
    SessionSkillProfileConfiguration,
)
from mosaic.models.skills.skill import Skill
from mosaic.models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot


class TestStructuredOutputValidator(unittest.TestCase):
    """Verify dynamic schemas are restricted to ready loaded output skills."""

    def test_ready_loaded_output_schema_is_applied(self) -> None:
        """A ready goal constrains the next model response."""
        validator, context, expected_schema = self._create_fixture(
            loaded_skill_names=('format-diagnostic-json',),
        )
        llm_request = Mock()

        result = validator.before_model_callback(
            context,
            llm_request,
        )

        self.assertIsNone(result)
        llm_request.set_output_schema.assert_called_once_with(expected_schema)

    def test_incomplete_required_capability_defers_schema(self) -> None:
        """Structured output is not forced while evidence remains missing."""
        validator, context, _ = self._create_fixture(
            loaded_skill_names=('format-diagnostic-json',),
            required_capability_names=('openshift.ingress.status.read',),
        )
        llm_request = Mock()

        result = validator.before_model_callback(
            context,
            llm_request,
        )

        self.assertIsNone(result)
        llm_request.set_output_schema.assert_not_called()

    def test_terminal_required_capability_allows_schema(self) -> None:
        """A non-success terminal outcome still completes evidence work."""
        validator, context, expected_schema = self._create_fixture(
            loaded_skill_names=('format-diagnostic-json',),
            required_capability_names=('cluster.events.read',),
            required_capability_outcomes={
                'cluster.events.read': 'evidence_too_large',
            },
        )
        llm_request = Mock()

        validator.before_model_callback(context, llm_request)

        llm_request.set_output_schema.assert_called_once_with(expected_schema)

    def test_unloaded_output_skill_does_not_apply_schema(self) -> None:
        """An authorised but unloaded output skill cannot constrain output."""
        validator, context, _ = self._create_fixture(
            loaded_skill_names=(),
        )
        llm_request = Mock()

        result = validator.before_model_callback(
            context,
            llm_request,
        )

        self.assertIsNone(result)
        llm_request.set_output_schema.assert_not_called()

    def _create_fixture(
        self,
        loaded_skill_names: tuple[str, ...],
        required_capability_names: tuple[str, ...] = (),
        required_capability_outcomes: dict[str, str] | None = None,
    ) -> tuple[
        StructuredOutputValidator,
        SimpleNamespace,
        dict[str, object],
    ]:
        """Create a validator, active context, and output schema fixture.

        Args:
            loaded_skill_names: Skill names recorded as loaded for the goal.
            required_capability_names: Required capabilities still incomplete.
            required_capability_outcomes: Terminal outcomes already recorded.

        Returns:
            Configured validator, ADA-like context, and expected schema.
        """
        output_schema = {
            '$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'https://mosaic.example/diagnostic.schema.json',
            'type': 'object',
            'additionalProperties': False,
            'required': ['status', 'time_window'],
            'properties': {
                'status': {
                    'type': 'string',
                    'enum': ['healthy', 'failed'],
                },
                'time_window': {
                    'type': ['string', 'null'],
                },
            },
        }
        expected_schema = {
            'type': 'object',
            'additionalProperties': False,
            'required': ['status', 'time_window'],
            'properties': {
                'status': {
                    'type': 'string',
                    'enum': ['healthy', 'failed'],
                },
                'time_window': {
                    'anyOf': [
                        {'type': 'string'},
                        {'type': 'null'},
                    ]
                },
            },
        }
        output_skill = Skill(
            name='format-diagnostic-json',
            version='1.0.0',
            kind='output',
            description='Format diagnostic evidence as JSON.',
            instruction='Return a schema-conformant JSON object.',
            output_schema=output_schema,
        )
        snapshot = SkillCatalogueSnapshot(
            commit_sha='a' * 40,
            loaded_at=datetime.now(timezone.utc),
            skills=(output_skill,),
        )
        profile_manager = SessionSkillProfileManager(
            resolver=SessionSkillProfileResolver(
                configuration=SessionSkillProfileConfiguration(
                    profiles={
                        'diagnostic-demo': ('format-diagnostic-json',),
                    },
                    default_profile_id='diagnostic-demo',
                ),
                catalogue_snapshot=snapshot,
            )
        )
        initial_orchestration_state = OrchestrationState.start(
            'invocation-1'
        )
        orchestration_state = initial_orchestration_state.model_copy(
            update={
                'phase': 'executing',
                'skill_discovery_completed': True,
                'skill_batch_attempted': bool(loaded_skill_names),
                'skill_batch_loaded': bool(loaded_skill_names),
                'requested_skill_names': loaded_skill_names,
                'loaded_skill_names': loaded_skill_names,
                'required_capability_names': required_capability_names,
                'required_capability_outcome_records': {
                    capability_name: (
                        initial_orchestration_state.goal_id,
                        outcome,
                    )
                    for capability_name, outcome in (
                        required_capability_outcomes or {}
                    ).items()
                },
            }
        )
        context = SimpleNamespace(
            invocation_id='invocation-1',
            session=SimpleNamespace(id='diagnostic-session'),
            state={
                'mosaic:orchestration': orchestration_state.model_dump(
                    mode='json'
                )
            },
        )
        return (
            StructuredOutputValidator(
                skills=snapshot.skills,
                profile_manager=profile_manager,
                response_schema_adapter=(
                    GoogleGenAiResponseSchemaAdapter()
                ),
            ),
            context,
            expected_schema,
        )


if __name__ == '__main__':
    unittest.main()
