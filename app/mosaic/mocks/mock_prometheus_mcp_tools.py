"""Mock read-only Prometheus MCP tools for the MOSAIC prototype."""

from pydantic import BaseModel, ConfigDict


class MockPrometheusMcpTools(BaseModel):
    """Return deterministic Prometheus evidence without external calls."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    def query_range(
        self,
        cluster_name: str,
        query: str,
        time_window_minutes: int,
    ) -> dict[str, object]:
        """Execute a mock generic Prometheus range query.

        Args:
            cluster_name: Cluster whose metrics are requested.
            query: Approved Prometheus query supplied by capability metadata.
            time_window_minutes: Positive number of recent minutes to inspect.

        Returns:
            Deterministic Prometheus evidence, or an ``invalid_request`` result
            for an empty cluster name or non-positive time window. This mock
            makes no external call and raises no validation exception for those
            expected input errors.
        """
        if not cluster_name.strip() or not query.strip():
            return {
                'status': 'invalid_request',
                'error': 'cluster_name and query must not be empty.',
            }
        if time_window_minutes <= 0:
            return {
                'status': 'invalid_request',
                'error': 'time_window_minutes must be greater than zero.',
            }

        return {
            'status': 'success',
            'source': 'mock-prometheus-mcp',
            'cluster_name': cluster_name.strip(),
            'query': query,
            'time_window_minutes': time_window_minutes,
            'router_p95_latency_seconds': 2.8,
            'router_pod_cpu_utilisation_percent': 92.0,
            'router_pod_memory_utilisation_percent': 68.0,
            'backend_connection_error_percent': 14.0,
            'router_restart_increase': 5,
        }
