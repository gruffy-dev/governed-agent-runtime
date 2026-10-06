"""Mock generic IBM MQ command tunnel for the MOSAIC prototype."""

from pydantic import BaseModel, ConfigDict


class MockMqMcpTools(BaseModel):
    """Return deterministic MQ command evidence without external calls."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    def run_mqsc(
        self,
        queue_manager_name: str,
        command: str,
    ) -> dict[str, object]:
        """Execute a mock command through a generic MQSC tunnel.

        Args:
            queue_manager_name: Queue manager receiving the command.
            command: Complete MQSC command prepared by capability metadata.

        Returns:
            Deterministic queue status evidence for an approved display
            command, or an ``invalid_request`` result for invalid inputs. This
            mock performs no external call.
        """
        if not queue_manager_name.strip() or not command.strip():
            return {
                'status': 'invalid_request',
                'error': 'MQSC arguments must not be empty.',
            }
        if not command.startswith('DISPLAY QSTATUS('):
            return {
                'status': 'invalid_request',
                'error': 'The mock accepts only DISPLAY QSTATUS commands.',
            }

        return {
            'status': 'success',
            'source': 'mock-mq-mcp',
            'queue_manager_name': queue_manager_name,
            'command': command,
            'queue_status': {
                'current_depth': 842,
                'maximum_depth': 5000,
                'open_input_count': 3,
                'open_output_count': 1,
            },
        }
