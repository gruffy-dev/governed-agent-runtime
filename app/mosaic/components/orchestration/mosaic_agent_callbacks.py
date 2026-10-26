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
        """
        Delegate completion handling to goal orchestration.

        :param callback_context: ADA callback context for the ending invocation.

        :raises RuntimeError: If orchestration state was not initialised.
        :raises ConcurrentSessionInvocationError: If another invocation replaced
            the active invocation before completion.
        """
        self.orchestration_controller.after_agent_callback(callback_context)

    def before_model_callback(
        self,
        callback_context: Context,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        """
        End clarification turns or constrain the model's next genuine tool call.

        :param callback_context: ADA context for the current model invocation.
        :param llm_request: Prepared request receiving goal-scoped tool selection.

        :return: A final clarification question, or ``None`` to allow model
            inference with the required function-calling configuration.

        :raises RuntimeError: If orchestration state was not initialised.
        :raises ConcurrentSessionInvocationError: If the invocation is stale.
        :raises pydantic.ValidationError: If the SDK rejects the tool configuration
            or clarification response.
        """
        question = self.orchestration_controller.pending_clarification_question(
            callback_context
        )
        if question is not None:
            from google.adk.models import LlmResponse as AdkLlmResponse

            return AdkLlmResponse.model_validate(
                {'content': {'role': 'model', 'parts': [{'text': question}]}}
            )

        from google.genai.types import FunctionCallingConfig
        from google.genai.types import ToolConfig

        required_names = self.orchestration_controller.required_model_tool_names(
            callback_context
        )
        tool_config = llm_request.config.tool_config
        if tool_config is None:
            tool_config = ToolConfig()
        llm_request.config.tool_config = tool_config.model_copy(
            update={
                'function_calling_config': FunctionCallingConfig(
                    mode='ANY' if required_names else 'AUTO',
                    allowed_function_names=list(required_names) if required_names else None,
                )
            }
        )
        return None

    def after_model_callback(
        self,
        callback_context: Context,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        """
        Preserve genuine model parts and reject premature final responses.

        :param callback_context: ADA context for the current model invocation.
        :param llm_response: Model response before it is emitted as an event.

        :return: ``None`` to preserve the model response and its thought signatures.

        :raises RuntimeError: If orchestration state was not initialised, or the
            model ends despite a required tool-selection constraint.
        :raises ConcurrentSessionInvocationError: If the invocation is stale.
        """
        if (
            llm_response.error_code
            or llm_response.partial
            or not llm_response.content
            or not llm_response.content.parts
            or llm_response.get_function_calls()
        ):
            return None

        if self.orchestration_controller.required_model_tool_names(callback_context):
            raise RuntimeError(
                'The model ended before required goal tools completed.'
            )
        return None

    def before_tool_callback(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: Context,
    ) -> dict[str, object] | None:
        """
        Delegate pre-execution tool enforcement to goal orchestration.

        :param tool: ADA tool about to be invoked.
        :param args: Model-supplied tool arguments.
        :param tool_context: ADA context for the current tool invocation.

        :return: A short-circuit result when blocked, otherwise ``None``.

        :raises RuntimeError: If orchestration state was not initialised.
        :raises ConcurrentSessionInvocationError: If the invocation is stale.
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
        """
        Delegate completed tool transitions to goal orchestration.

        :param tool: ADA tool that completed.
        :param args: Semantic arguments supplied to the tool.
        :param tool_context: ADA context for the current tool invocation.
        :param tool_response: Serialised result returned by the tool.

        :raises ValueError: If a clarification transition is invalid.
        :raises RuntimeError: If orchestration state was not initialised.
        :raises ConcurrentSessionInvocationError: If the invocation is stale.
        """
        self.orchestration_controller.after_tool_callback(
            tool,
            args,
            tool_context,
            tool_response,
        )
