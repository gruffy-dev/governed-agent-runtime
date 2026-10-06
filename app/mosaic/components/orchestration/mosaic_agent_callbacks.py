"""Composed ADA callbacks for profile and goal orchestration policy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from ..skills.session_skill_profile_manager import SessionSkillProfileManager
from .orchestration_transition_controller import (
    OrchestrationTransitionController,
)

if TYPE_CHECKING:
    from google.adk.agents import Context
    from google.adk.models import LlmRequest, LlmResponse
    from google.adk.tools import BaseTool


class MosaicAgentCallbacks(BaseModel):
    """Apply trusted profile binding before existing goal transitions."""

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
        """Bind the trusted profile before starting or resuming a goal.

        Args:
            callback_context: ADA callback context for the new invocation.

        Raises:
            ValueError: If the session identifier or profile is invalid.
            ConcurrentSessionInvocationError: If another invocation remains
                active for the session goal.
        """
        self.profile_manager.ensure_profile(callback_context)
        self.orchestration_controller.before_agent_callback(callback_context)

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
        """Force bounded skill discovery before the first model inference.

        Args:
            callback_context: ADA context for the current model invocation.
            llm_request: Prepared request that will be skipped for discovery.

        Returns:
            A synthetic ``discover_skills`` function call for a new goal,
            otherwise ``None`` to continue normal model processing.

        Raises:
            RuntimeError: If orchestration state was not initialized.
            ConcurrentSessionInvocationError: If the invocation is stale.
            pydantic.ValidationError: If ADK rejects the synthetic response.
        """
        if not self.orchestration_controller.skill_discovery_required(
            callback_context
        ):
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
