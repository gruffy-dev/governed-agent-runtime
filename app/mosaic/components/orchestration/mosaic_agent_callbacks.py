from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from ..skills.session_skill_profile_manager import SessionSkillProfileManager
from .orchestration_transition_controller import OrchestrationTransitionController

if TYPE_CHECKING:
    from google.adk.agents import Context
    from google.adk.models import LlmRequest, LlmResponse
    from google.adk.tools import BaseTool


class MosaicAgentCallbacks(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    profile_manager: SessionSkillProfileManager = Field(
        description='Trusted session skill-profile state manager.',
    )
    orchestration_controller: OrchestrationTransitionController = Field(
        description='Existing goal-scoped orchestration controller.',
    )

    def before_agent_callback(
        self,
        callback_context: Context,
    ) -> None:
        """
        Start or resume the owned Goal before binding its immutable workspace Skills.

        :param callback_context: ADA callback context for the new invocation.

        :raises ValueError: If session ownership or the Skill snapshot is invalid.
        :raises ConcurrentSessionInvocationError: If another invocation owns the Goal.
        """
        self.orchestration_controller.before_agent_callback(callback_context)
        self.profile_manager.ensure_profile(callback_context)

    def after_agent_callback(
        self,
        callback_context: Context,
    ) -> None:
        """Delegate completion handling to goal orchestration.

        Args:
            callback_context: ADA callback context for the ending invocation.

        Raises:
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If another invocation replaced
                the active invocation before completion.
        """
        self.orchestration_controller.after_agent_callback(callback_context)

    def before_model_callback(
        self,
        callback_context: Context,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        """
        End clarification turns or force discovery before model inference.

        :param callback_context: ADA context for the current model invocation.
        :param llm_request: Prepared request skipped for clarification or discovery.

        :return: A final clarification question, an initial discovery call, or
            ``None`` to allow normal model inference.

        :raises RuntimeError: If orchestration state was not initialised.
        :raises ConcurrentSessionInvocationError: If the invocation is stale.
        :raises pydantic.ValidationError: If ADK rejects the synthetic response.
        """
        question = self.orchestration_controller.pending_clarification_question(
            callback_context
        )
        if question is not None:
            from google.adk.models import LlmResponse as AdkLlmResponse

            return AdkLlmResponse.model_validate(
                {'content': {'role': 'model', 'parts': [{'text': question}]}}
            )

        if not self.orchestration_controller.skill_discovery_required(callback_context):
            return None

        from google.adk.models import LlmResponse as AdkLlmResponse

        return AdkLlmResponse.model_validate(
            {
                'content': {
                    'role': 'model',
                    'parts': [
                        {
                            'function_call': {
                                'name': 'discover_skills',
                                'args': {},
                            }
                        }
                    ],
                }
            }
        )

    def after_model_callback(
        self,
        callback_context: Context,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        """Replace a premature final response with a continuation tool call.

        Args:
            callback_context: ADA context for the current model invocation.
            llm_response: Model response before it is emitted as an event.

        Returns:
            A synthetic continuation call while required capabilities remain,
            otherwise ``None`` to preserve normal ADK processing.

        Raises:
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If the invocation is stale.
            pydantic.ValidationError: If ADK rejects the replacement response.
        """
        if (
            llm_response.error_code
            or llm_response.partial
            or not llm_response.content
            or not llm_response.content.parts
            or llm_response.get_function_calls()
        ):
            return None

        missing_names = (
            self.orchestration_controller.incomplete_required_capability_names(
                callback_context
            )
        )
        if not missing_names:
            return None

        return type(llm_response).model_validate(
            {
                'content': {
                    'role': 'model',
                    'parts': [
                        {
                            'function_call': {
                                'name': 'continue_goal_execution',
                                'args': {
                                    'missing_required_capability_names': list(
                                        missing_names
                                    )
                                },
                            }
                        }
                    ],
                }
            }
        )

    def before_tool_callback(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: Context,
    ) -> dict[str, object] | None:
        """Delegate pre-execution tool enforcement to goal orchestration.

        Args:
            tool: ADA tool about to be invoked.
            args: Model-supplied tool arguments.
            tool_context: ADA context for the current tool invocation.

        Returns:
            A short-circuit result when blocked, otherwise ``None``.

        Raises:
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If the invocation is stale.
        """
        return self.orchestration_controller.before_tool_callback(
            tool,
            args,
            tool_context,
        )

    def after_tool_callback(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: Context,
        tool_response: dict[str, Any],
    ) -> None:
        """Delegate completed tool transitions to goal orchestration.

        Args:
            tool: ADA tool that completed.
            args: Semantic arguments supplied to the tool.
            tool_context: ADA context for the current tool invocation.
            tool_response: Serialized result returned by the tool.

        Raises:
            ValueError: If a clarification transition is invalid.
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If the invocation is stale.
        """
        self.orchestration_controller.after_tool_callback(
            tool,
            args,
            tool_context,
            tool_response,
        )
