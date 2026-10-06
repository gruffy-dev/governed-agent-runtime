"""Mock generic Kubernetes MCP tools for the MOSAIC prototype."""

from pydantic import BaseModel, ConfigDict


class MockKubernetesMcpTools(BaseModel):
    """Return deterministic Kubernetes evidence without external calls."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    def resources_list(
        self,
        cluster_name: str,
        api_version: str,
        kind: str,
        namespace: str,
        label_selector: str,
    ) -> dict[str, object]:
        """List mock Kubernetes resources using generic selectors.

        Args:
            cluster_name: Cluster from which resources are requested.
            api_version: Kubernetes API version of the resource kind.
            kind: Kubernetes resource kind to list.
            namespace: Namespace containing the requested resources.
            label_selector: Label expression used to filter resources.

        Returns:
            Deterministic router pod data for the approved OpenShift ingress
            query, or an ``invalid_request`` result for invalid inputs. This
            mock performs no external call.
        """
        string_arguments = (
            cluster_name,
            api_version,
            kind,
            namespace,
            label_selector,
        )
        if any(not argument.strip() for argument in string_arguments):
            return {
                'status': 'invalid_request',
                'error': 'Kubernetes resource arguments must not be empty.',
            }

        return {
            'status': 'success',
            'source': 'mock-kubernetes-mcp',
            'request': {
                'cluster_name': cluster_name.strip(),
                'api_version': api_version,
                'kind': kind,
                'namespace': namespace,
                'label_selector': label_selector,
            },
            'resources': [
                {
                    'name': 'router-default-6f4d8',
                    'ready': True,
                    'restart_count': 0,
                },
                {
                    'name': 'router-default-79b6c',
                    'ready': True,
                    'restart_count': 0,
                },
                {
                    'name': 'router-default-b7c9a',
                    'ready': False,
                    'restart_count': 5,
                },
            ],
            'summary': {
                'desired_replicas': 3,
                'available_replicas': 2,
                'degraded': True,
            },
        }

    def pods_log(
        self,
        cluster_name: str,
        namespace: str,
        pod_name: str,
        since_minutes: int,
    ) -> dict[str, object]:
        """Read mock logs through a generic Kubernetes pod log tool.

        Args:
            cluster_name: Cluster containing the selected pod.
            namespace: Namespace containing the selected pod.
            pod_name: Pod whose recent logs are requested.
            since_minutes: Positive recent time window in minutes.

        Returns:
            Deterministic router log evidence, or an ``invalid_request``
            result for invalid inputs. This mock performs no external call.
        """
        if any(
            not argument.strip()
            for argument in (cluster_name, namespace, pod_name)
        ):
            return {
                'status': 'invalid_request',
                'error': 'Kubernetes pod log arguments must not be empty.',
            }
        if since_minutes <= 0:
            return {
                'status': 'invalid_request',
                'error': 'since_minutes must be greater than zero.',
            }

        return {
            'status': 'success',
            'source': 'mock-kubernetes-mcp',
            'request': {
                'cluster_name': cluster_name.strip(),
                'namespace': namespace,
                'pod_name': pod_name,
                'since_minutes': since_minutes,
            },
            'warning_summary': [
                {
                    'message': 'Backend connection timeout',
                    'backend': 'checkout-api',
                    'occurrences': 120,
                },
                {
                    'message': 'Router pod restarted after liveness failure',
                    'pod': pod_name,
                    'occurrences': 5,
                },
            ],
        }

    def events_list(
        self,
        cluster_name: str,
        namespace: str,
        since_minutes: int,
    ) -> dict[str, object]:
        """List deterministic OpenShift ingress events.

        Args:
            cluster_name: Cluster containing the ingress resources.
            namespace: Namespace whose recent events are requested.
            since_minutes: Positive recent time window in minutes.

        Returns:
            Deterministic ingress event evidence, or an ``invalid_request``
            result for invalid inputs. This mock performs no external call.
        """
        if not cluster_name.strip() or not namespace.strip():
            return {
                'status': 'invalid_request',
                'error': 'Cluster and namespace must not be empty.',
            }
        if since_minutes <= 0:
            return {
                'status': 'invalid_request',
                'error': 'since_minutes must be greater than zero.',
            }

        return {
            'status': 'success',
            'source': 'mock-kubernetes-mcp',
            'request': {
                'cluster_name': cluster_name.strip(),
                'namespace': namespace,
                'since_minutes': since_minutes,
            },
            'events': [
                {
                    'reason': 'Unhealthy',
                    'resource_name': 'router-default-b7c9a',
                    'message': 'Router liveness probe failed.',
                    'occurrences': 5,
                    'minutes_ago': 12,
                },
                {
                    'reason': 'Killing',
                    'resource_name': 'router-default-b7c9a',
                    'message': 'Router container restarted.',
                    'occurrences': 5,
                    'minutes_ago': 11,
                },
            ],
        }
