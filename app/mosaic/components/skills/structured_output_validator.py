"""Dynamic model-output constraints for loaded output skills."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from ...interfaces.orchestration.callback_context_protocol import (
    CallbackContextProtocol,
)
from ...models.orchestration.orchestration_state import OrchestrationState
from ...models.skills.skill import Skill
from .google_gen_ai_response_schema_adapter import (
    GoogleGenAiResponseSchemaAdapter,
)
from .session_skill_profile_manager import SessionSkillProfileManager

if TYPE_CHECKING:
    from google.adk.agents import Context
    from google.adk.models import LlmRequest


class StructuredOutputValidator(BaseModel):
    """Apply an authorised loaded output skill's schema to model requests."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    skills: tuple[Skill, ...] = Field(
        description='Approved skills available in the catalogue snapshot.',
        min_length=1,
    )
    profile_manager: SessionSkillProfileManager = Field(
        description='Trusted session skill-profile state manager.',
    )
    response_schema_adapter: GoogleGenAiResponseSchemaAdapter = Field(
        description='Google GenAI response-schema compatibility adapter.',
    )
    orchestration_state_key: str = Field(
        default='mosaic:orchestration',
        description='ADA session-state key containing loaded skill names.',
        min_length=1,
    )

    def before_model_callback(
        self,
        callback_context: Context,
        llm_request: LlmRequest,
    ) -> None:
        """Constrain a final model response with its loaded output schema.

        Args:
            callback_context: ADA context for the current model request.
            llm_request: ADA model request to constrain before execution.

        Raises:
            RuntimeError: If goal orchestration state is not initialized.
            ValueError: If multiple loaded output skills declare schemas.
            pydantic.ValidationError: If persisted state is malformed.
        """
        profile = self.profile_manager.ensure_profile(callback_context)
        orchestration_state = self._read_orchestration_state(
            callback_context
        )
        if orchestration_state.phase == 'awaiting_clarification':
            return

        incomplete_required_capability_names = (
            set(orchestration_state.required_capability_names)
            - set(orchestration_state.required_capability_outcomes.keys())
        )
        if incomplete_required_capability_names:
            return

        allowed_skill_names = set(profile.allowed_skill_names)
        loaded_skill_names = set(orchestration_state.loaded_skill_names)
        output_schemas = [
            skill.output_schema
            for skill in self.skills
            if skill.name in allowed_skill_names
            and skill.name in loaded_skill_names
            and skill.kind == 'output'
            and skill.output_schema is not None
        ]
        if len(output_schemas) > 1:
            raise ValueError(
                'Only one loaded output skill can declare a JSON Schema.'
        )
        if output_schemas:
            llm_request.set_output_schema(
                self.response_schema_adapter.adapt(output_schemas[0])
            )

    def _read_orchestration_state(
        self,
        context: CallbackContextProtocol,
    ) -> OrchestrationState:
        """Read the validated current goal state from ADA session state.

        Args:
            context: ADA tool context containing persisted session state.

        Returns:
            Validated orchestration state for the current goal.

        Raises:
            RuntimeError: If goal orchestration state is not initialized.
            pydantic.ValidationError: If persisted state is malformed.
        """
        raw_state = context.state.get(self.orchestration_state_key)
        if raw_state is None:
            raise RuntimeError('MOSAIC orchestration state is not initialized.')
        return OrchestrationState.model_validate(raw_state)
