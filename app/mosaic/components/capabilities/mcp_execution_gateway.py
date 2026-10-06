"""Governed capability execution boundary for the MOSAIC runtime."""

import asyncio
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from ...interfaces.capabilities.capability_provider_invoker import CapabilityProviderInvoker
from ...interfaces.orchestration.callback_context_protocol import CallbackContextProtocol
from ...models.capabilities.capability_execution_result import CapabilityExecutionResult
from ...models.capabilities.capability_evidence_limit_exceeded_error import CapabilityEvidenceLimitExceededError
from ...models.capabilities.prepared_capability_invocation import PreparedCapabilityInvocation
from ...models.orchestration.orchestration_state import OrchestrationState
from .capability_catalogue_and_resolver import CapabilityCatalogueAndResolver
from .capability_execution_observability import CapabilityExecutionObservability
from .mcp_capability_result_processor import McpCapabilityResultProcessor


class MCPExecutionGateway(BaseModel):
    """Resolve and execute semantic capabilities through governed providers."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='forbid',
        frozen=True,
    )

    capability_catalogue_and_resolver: CapabilityCatalogueAndResolver = Field(
        description='Preconfigured local capability catalogue and resolver.',
    )
    provider_invoker: CapabilityProviderInvoker = Field(
        description='Internal adapter for approved ADA MCP invocations.',
    )
    orchestration_state_key: str = Field(
        default='mosaic:orchestration',
        description='ADA session-state key containing the pinned goal target.',
        min_length=1,
    )
    result_processor: McpCapabilityResultProcessor = Field(
        default_factory=McpCapabilityResultProcessor,
        description='Bounded processor for declared raw MCP result bindings.',
    )
    observability: CapabilityExecutionObservability = Field(
        default_factory=CapabilityExecutionObservability,
        description='Centralized safe capability lifecycle observability.',
    )
    execution_timeout_seconds: float = Field(
        default=30.0,
        description='Maximum duration for a provider invocation.',
        gt=0,
        le=300,
    )

    async def execute_capability(
        self,
        capability_name: str,
        semantic_arguments: dict[str, JsonValue],
        tool_context: CallbackContextProtocol,
    ) -> dict[str, object]:
        """Execute one semantic capability through the governed boundary.

        Supply only semantic values from the user's context or trusted prior
        evidence. This gateway selects the provider, prepares concrete
        arguments from a prevalidated local catalogue, enforces capability
        policy, and invokes the provider. It makes no registry or catalogue
        calls. The caller cannot select an MCP server, tool, query, command,
        or fixed argument directly.

        Args:
            capability_name: Approved semantic capability name from a loaded
                skill or the current capability catalogue.
            semantic_arguments: Runtime values keyed by the capability's
                declared semantic input names.
            tool_context: ADK-injected context for request-scoped MCP headers.

        Returns:
            A serialized execution result containing provider evidence on
            success or safe missing, invalid, unavailable, timeout, or failure
            information. Concrete provider arguments are never returned.
        """
        execution_started_at = perf_counter()
        normalized_name = capability_name.strip().lower()
        target_id = self._goal_target_id(tool_context)
        if not normalized_name:
            result = CapabilityExecutionResult(
                status='invalid_arguments',
                capability_name='<empty>',
                target_id=target_id,
                invalid_semantic_argument_names=('capability_name',),
            )
            self.observability.record(
                event='capability_execution_rejected',
                capability_name='<empty>',
                target_id=target_id,
                execution_status=result.status,
                tool_context=tool_context,
                execution_stage='preparation',
                duration_ms=self._elapsed_milliseconds(
                    execution_started_at
                ),
            )
            return result.model_dump(mode='json')

        try:
            preparation = PreparedCapabilityInvocation.model_validate(
                self.capability_catalogue_and_resolver
                .prepare_capability_invocation(
                    capability_name=normalized_name,
                    semantic_arguments=semantic_arguments,
                    target_id=target_id,
                )
            )
        except Exception as error:  # noqa: BLE001 - fail closed at boundary.
            self.observability.record(
                event='capability_execution_failed',
                capability_name=normalized_name,
                target_id=target_id,
                tool_context=tool_context,
                execution_stage='preparation',
                execution_status='failed',
                error=error,
                duration_ms=self._elapsed_milliseconds(
                    execution_started_at
                ),
            )
            return CapabilityExecutionResult(
                status='failed',
                capability_name=normalized_name,
                target_id=target_id,
                error_message='Capability preparation failed safely.',
            ).model_dump(mode='json')

        if preparation.status != 'ready':
            result = self._build_non_ready_result(preparation, target_id)
            self.observability.record(
                event='capability_execution_rejected',
                capability_name=normalized_name,
                target_id=target_id,
                execution_status=result.status,
                tool_context=tool_context,
                execution_stage='preparation',
                duration_ms=self._elapsed_milliseconds(
                    execution_started_at
                ),
            )
            return result.model_dump(mode='json')

        provider_name = preparation.provider_name
        tool_name = preparation.tool_name
        if provider_name is None or tool_name is None:
            error = RuntimeError(
                'Ready capability preparation omitted provider details.'
            )
            self.observability.record(
                event='capability_execution_failed',
                capability_name=normalized_name,
                target_id=target_id,
                tool_context=tool_context,
                execution_stage='preparation',
                execution_status='failed',
                error=error,
                duration_ms=self._elapsed_milliseconds(
                    execution_started_at
                ),
            )
            return CapabilityExecutionResult(
                status='failed',
                capability_name=normalized_name,
                target_id=target_id,
                error_message='Capability preparation failed safely.',
            ).model_dump(mode='json')

        self.observability.record(
            event='capability_provider_invocation_started',
            capability_name=normalized_name,
            target_id=target_id,
            provider_name=provider_name,
            tool_name=tool_name,
            tool_context=tool_context,
            execution_stage='provider_invocation',
        )
        provider_started_at = perf_counter()
        try:
            provider_result = await asyncio.wait_for(
                self.provider_invoker.invoke(
                    provider_name=provider_name,
                    tool_name=tool_name,
                    tool_arguments=preparation.tool_arguments,
                    tool_context=tool_context,
                ),
                timeout=self.execution_timeout_seconds,
            )
        except TimeoutError:
            self.observability.record(
                event='capability_execution_timed_out',
                capability_name=normalized_name,
                target_id=target_id,
                provider_name=provider_name,
                tool_name=tool_name,
                tool_context=tool_context,
                execution_stage='provider_invocation',
                execution_status='timed_out',
                duration_ms=self._elapsed_milliseconds(
                    execution_started_at
                ),
            )
            return CapabilityExecutionResult(
                status='timed_out',
                capability_name=normalized_name,
                target_id=target_id,
                ignored_semantic_argument_names=(
                    preparation.ignored_semantic_argument_names
                ),
                error_message='Capability provider invocation timed out.',
            ).model_dump(mode='json')
        except Exception as error:  # noqa: BLE001 - isolate provider failures.
            self.observability.record(
                event='capability_execution_failed',
                capability_name=normalized_name,
                target_id=target_id,
                provider_name=provider_name,
                tool_name=tool_name,
                tool_context=tool_context,
                execution_stage='provider_invocation',
                execution_status='failed',
                error=error,
                duration_ms=self._elapsed_milliseconds(
                    execution_started_at
                ),
            )
            return CapabilityExecutionResult(
                status='failed',
                capability_name=normalized_name,
                target_id=target_id,
                ignored_semantic_argument_names=(
                    preparation.ignored_semantic_argument_names
                ),
                error_message='Capability provider invocation failed safely.',
            ).model_dump(mode='json')

        provider_duration_ms = self._elapsed_milliseconds(
            provider_started_at
        )
        content = provider_result.get('content')
        content_block_count = (
            len(content) if isinstance(content, list) else 0
        )
        structured_content_present = 'structuredContent' in provider_result
        mcp_error_result = provider_result.get('isError') is True
        try:
            if preparation.result_binding is None:
                evidence = provider_result
            else:
                evidence = self.result_processor.process(
                    provider_result=provider_result,
                    result_binding=preparation.result_binding,
                    tool_arguments=preparation.tool_arguments,
                )
            result = CapabilityExecutionResult(
                status='success',
                capability_name=normalized_name,
                target_id=target_id,
                evidence=evidence,
                ignored_semantic_argument_names=(
                    preparation.ignored_semantic_argument_names
                ),
            )
        except Exception as error:  # noqa: BLE001 - reject unsafe evidence.
            evidence_too_large = isinstance(
                error,
                CapabilityEvidenceLimitExceededError,
            )
            execution_status: Literal['evidence_too_large', 'failed'] = (
                'evidence_too_large' if evidence_too_large else 'failed'
            )
            self.observability.record(
                event='capability_execution_failed',
                capability_name=normalized_name,
                target_id=target_id,
                provider_name=provider_name,
                tool_name=tool_name,
                tool_context=tool_context,
                execution_stage='result_processing',
                execution_status=execution_status,
                provider_duration_ms=provider_duration_ms,
                mcp_content_block_count=content_block_count,
                mcp_structured_content_present=(
                    structured_content_present
                ),
                mcp_error_result=mcp_error_result,
                error=error,
                duration_ms=self._elapsed_milliseconds(
                    execution_started_at
                ),
            )
            return CapabilityExecutionResult(
                status=execution_status,
                capability_name=normalized_name,
                target_id=target_id,
                ignored_semantic_argument_names=(
                    preparation.ignored_semantic_argument_names
                ),
                error_message=(
                    'Capability provider evidence exceeded its governed limit.'
                    if evidence_too_large
                    else 'Capability provider result processing failed safely.'
                ),
            ).model_dump(mode='json')

        self.observability.record(
            event='capability_execution_completed',
            capability_name=normalized_name,
            target_id=target_id,
            provider_name=provider_name,
            tool_name=tool_name,
            tool_context=tool_context,
            execution_stage='completed',
            execution_status='success',
            duration_ms=self._elapsed_milliseconds(execution_started_at),
            provider_duration_ms=provider_duration_ms,
            mcp_content_block_count=content_block_count,
            mcp_structured_content_present=structured_content_present,
            mcp_error_result=mcp_error_result,
            content_source=(
                preparation.result_binding.content_source
                if preparation.result_binding is not None
                else None
            ),
            content_media_type=(
                preparation.result_binding.content_media_type
                if preparation.result_binding is not None
                else None
            ),
            result_operation=(
                preparation.result_binding.operation
                if preparation.result_binding is not None
                else None
            ),
        )
        return result.model_dump(mode='json')

    def _elapsed_milliseconds(self, started_at: float) -> float:
        """Calculate a non-negative elapsed duration.

        Args:
            started_at: Monotonic start time from ``perf_counter``.

        Returns:
            Elapsed milliseconds rounded to three decimal places.
        """
        return round(max(0.0, perf_counter() - started_at) * 1000, 3)

    def _build_non_ready_result(
        self,
        preparation: PreparedCapabilityInvocation,
        target_id: str | None,
    ) -> CapabilityExecutionResult:
        """Translate a non-ready preparation into an execution result.

        Args:
            preparation: Validated preparation that cannot be invoked.
            target_id: Canonical target pinned to the active goal.

        Returns:
            A safe execution result preserving argument diagnostics.

        Raises:
            ValueError: If called with a ready preparation.
        """
        if preparation.status == 'ready':
            raise ValueError(
                'A ready preparation cannot become a non-ready result.'
            )

        return CapabilityExecutionResult(
            status=preparation.status,
            capability_name=preparation.capability_name,
            target_id=target_id,
            missing_semantic_argument_names=(
                preparation.missing_semantic_argument_names
            ),
            invalid_semantic_argument_names=(
                preparation.invalid_semantic_argument_names
            ),
            ignored_semantic_argument_names=(
                preparation.ignored_semantic_argument_names
            ),
        )

    def _goal_target_id(
        self,
        tool_context: CallbackContextProtocol,
    ) -> str | None:
        """Read the immutable target captured by capability discovery.

        Args:
            tool_context: ADK context containing goal-scoped state.

        Returns:
            Canonical goal target, or ``None`` for target-independent work or
            direct boundary tests without orchestration state.

        Raises:
            pydantic.ValidationError: If persisted goal state is malformed.
        """
        raw_state = tool_context.state.get(self.orchestration_state_key)
        if raw_state is None:
            return None
        return OrchestrationState.model_validate(raw_state).target_id
