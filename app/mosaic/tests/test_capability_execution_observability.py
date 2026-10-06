"""Tests for centralized safe capability execution observability."""

import unittest
from types import SimpleNamespace

from mosaic.components.capabilities.capability_execution_observability import (
    CapabilityExecutionObservability,
)


class TestCapabilityExecutionObservability(unittest.TestCase):
    """Verify correlation metadata and sensitive-data exclusion."""

    def test_completion_logs_safe_envelope_metadata_only(self) -> None:
        """Completion metadata cannot contain raw provider results."""
        observability = CapabilityExecutionObservability()
        provider_result: dict[str, object] = {
            'content': [
                {'type': 'text', 'text': 'sensitive-provider-payload'}
            ],
            'structuredContent': {'secret': 'sensitive-structured-value'},
            'isError': False,
        }

        with self.assertLogs(
            'mosaic.capability_execution',
            level='INFO',
        ) as captured_logs:
            observability.record(
                event='capability_execution_completed',
                capability_name='inventory.objects.count',
                provider_name='inventory-mcp',
                tool_name='objects_list',
                tool_context=self._context(),
                execution_stage='completed',
                execution_status='success',
                provider_duration_ms=12.5,
                mcp_content_block_count=1,
                mcp_structured_content_present=True,
                mcp_error_result=False,
            )

        record = captured_logs.records[0]
        self.assertEqual(
            record.mosaic_event,
            'capability_execution_completed',
        )
        self.assertEqual(record.invocation_id, 'invocation-1')
        self.assertEqual(record.session_id, 'test-session')
        self.assertEqual(record.mcp_content_block_count, 1)
        self.assertTrue(record.mcp_structured_content_present)
        record_values = tuple(record.__dict__.values())
        self.assertNotIn('sensitive-provider-payload', record_values)
        self.assertNotIn('sensitive-structured-value', record_values)
        self.assertNotIn(provider_result, record_values)

    def test_failure_logs_type_and_stack_without_exception_message(self) -> None:
        """SDK error text that may contain provider data is not disclosed."""
        observability = CapabilityExecutionObservability()

        try:
            raise ValueError('sensitive-provider-error-content')
        except ValueError as error:
            with self.assertLogs(
                'mosaic.capability_execution',
                level='ERROR',
            ) as captured_logs:
                observability.record(
                    event='capability_execution_failed',
                    capability_name='inventory.objects.count',
                    provider_name='inventory-mcp',
                    tool_name='objects_list',
                    tool_context=self._context(),
                    execution_stage='result_processing',
                    execution_status='failed',
                    error=error,
                    duration_ms=15.0,
                )

        record = captured_logs.records[0]
        self.assertEqual(record.error_type, 'ValueError')
        self.assertTrue(record.error_stack)
        self.assertNotIn(
            'sensitive-provider-error-content',
            '\n'.join(captured_logs.output),
        )
        self.assertNotIn(
            'sensitive-provider-error-content',
            record.__dict__.values(),
        )

    def _context(self) -> SimpleNamespace:
        """Create the minimal request context used for correlation.

        Returns:
            ADK-like context with invocation and session identifiers.
        """
        return SimpleNamespace(
            invocation_id='invocation-1',
            session=SimpleNamespace(id='test-session'),
            state={},
        )


if __name__ == '__main__':
    unittest.main()
