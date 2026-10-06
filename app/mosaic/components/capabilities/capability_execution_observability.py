"""Centralized safe observability for governed capability execution."""

import json
import logging
import traceback
from typing import Literal

from ...interfaces.orchestration.callback_context_protocol import CallbackContextProtocol


class CapabilityExecutionObservability:
    """Complement ADA logging with MOSAIC capability lifecycle events."""

    def __init__(
        self,
        logger_name: str = 'mosaic.capability_execution',
    ) -> None:
        """Configure the logger receiving MOSAIC lifecycle events.

        Args:
            logger_name: Python logger configured by the host application.

        Raises:
            ValueError: If the logger name is empty.
        """
        if not logger_name:
            raise ValueError('Capability logger name must not be empty.')
        self._logger = logging.getLogger(logger_name)

    def record(
        self,
        event: Literal[
            'capability_execution_rejected',
            'capability_provider_invocation_started',
            'capability_execution_completed',
            'capability_execution_timed_out',
            'capability_execution_failed',
        ],
        capability_name: str,
        tool_context: CallbackContextProtocol,
        execution_stage: Literal[
            'preparation',
            'provider_invocation',
            'result_processing',
            'completed',
        ],
        target_id: str | None = None,
        provider_name: str | None = None,
        tool_name: str | None = None,
        execution_status: str | None = None,
        duration_ms: float | None = None,
        provider_duration_ms: float | None = None,
        mcp_content_block_count: int | None = None,
        mcp_structured_content_present: bool | None = None,
        mcp_error_result: bool | None = None,
        content_source: str | None = None,
        content_media_type: str | None = None,
        result_operation: str | None = None,
        error: Exception | None = None,
    ) -> None:
        """Emit one event containing only explicitly approved metadata.

        Args:
            event: Stable machine-readable lifecycle event name.
            capability_name: Normalized semantic capability name.
            tool_context: Request context supplying correlation identifiers.
            execution_stage: Current capability lifecycle stage.
            target_id: Canonical target pinned to the active goal, when any.
            provider_name: Governed provider name, when known.
            tool_name: Allowlisted provider tool name, when known.
            execution_status: Safe execution outcome, when final or rejected.
            duration_ms: Total elapsed execution time, when available.
            provider_duration_ms: Provider call duration, when available.
            mcp_content_block_count: Number of standard MCP content blocks.
            mcp_structured_content_present: Whether structured content exists.
            mcp_error_result: Whether the MCP result declared an error.
            content_source: Declared result source selected by the binding.
            content_media_type: Declared serialization of selected content.
            result_operation: Deterministic result reduction operation.
            error: Failure used only for its type and stack locations.
        """
        metadata: dict[str, object] = {
            'mosaic_event': event,
            'capability_name': capability_name,
            'invocation_id': tool_context.invocation_id,
            'session_id': tool_context.session.id,
            'execution_stage': execution_stage,
        }
        optional_metadata: dict[str, object | None] = {
            'target_id': target_id,
            'provider_name': provider_name,
            'tool_name': tool_name,
            'execution_status': execution_status,
            'duration_ms': duration_ms,
            'provider_duration_ms': provider_duration_ms,
            'mcp_content_block_count': mcp_content_block_count,
            'mcp_structured_content_present': (
                mcp_structured_content_present
            ),
            'mcp_error_result': mcp_error_result,
            'content_source': content_source,
            'content_media_type': content_media_type,
            'result_operation': result_operation,
        }
        metadata.update(
            {
                name: value
                for name, value in optional_metadata.items()
                if value is not None
            }
        )
        if error is not None:
            metadata['error_type'] = type(error).__name__
            metadata['error_stack'] = tuple(
                f'{frame.filename}:{frame.lineno}:{frame.name}'
                for frame in traceback.extract_tb(error.__traceback__)[-16:]
            )

        level = logging.INFO
        if event == 'capability_execution_timed_out':
            level = logging.WARNING
        elif event == 'capability_execution_failed':
            level = logging.ERROR
        self._logger.log(
            level,
            f'MOSAIC capability lifecycle {json.dumps(metadata, sort_keys=True)}',
            extra=metadata,
        )
