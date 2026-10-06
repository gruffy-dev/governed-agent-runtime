"""Tests for governed capability-provider routing."""

import unittest
from types import SimpleNamespace

from pydantic import ValidationError

from mosaic.components.capabilities.capability_provider_invoker_router import (
    CapabilityProviderInvokerRouter,
)
from mosaic.mocks.mock_capability_provider_invoker import (
    MockCapabilityProviderInvoker,
)


class TestCapabilityProviderInvokerRouter(unittest.IsolatedAsyncioTestCase):
    """Verify provider ownership is unique and dispatch is deterministic."""

    async def test_mock_provider_is_routed(self) -> None:
        """A known provider call reaches its sole owning invoker."""
        router = CapabilityProviderInvokerRouter(
            provider_invokers=(MockCapabilityProviderInvoker(),),
        )

        result = await router.invoke(
            provider_name='mock-kubernetes-mcp',
            tool_name='events_list',
            tool_arguments={
                'cluster_name': 'dev',
                'namespace': 'openshift-ingress',
                'since_minutes': 30,
            },
            tool_context=SimpleNamespace(),
        )

        self.assertEqual(result['status'], 'success')

    def test_duplicate_provider_ownership_is_rejected(self) -> None:
        """Two invokers cannot ambiguously claim the same provider."""
        with self.assertRaises(ValidationError):
            CapabilityProviderInvokerRouter(
                provider_invokers=(
                    MockCapabilityProviderInvoker(),
                    MockCapabilityProviderInvoker(),
                ),
            )


if __name__ == '__main__':
    unittest.main()
