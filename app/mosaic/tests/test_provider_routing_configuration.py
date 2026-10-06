import unittest

from pydantic import ValidationError

from mosaic.models.capabilities.provider_routing_configuration import ProviderRoutingConfiguration
from mosaic.models.capabilities.provider_target_binding import ProviderTargetBinding


class TestProviderRoutingConfiguration(unittest.TestCase):
    def test_target_independent_routing_is_accepted(self) -> None:
        routing = ProviderRoutingConfiguration(mode='target_independent')

        self.assertEqual(routing.mode, 'target_independent')

    def test_target_independent_routing_rejects_target_fields(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            'accepts no target fields',
        ):
            ProviderRoutingConfiguration(
                mode='target_independent',
                target_id='openshift/cluster1',
            )

    def test_endpoint_per_target_routing_is_accepted(self) -> None:
        routing = ProviderRoutingConfiguration(
            mode='endpoint_per_target',
            target_id='openshift/cluster1',
        )

        self.assertEqual(routing.target_id, 'openshift/cluster1')

    def test_shared_endpoint_routing_is_accepted(self) -> None:
        routing = ProviderRoutingConfiguration(
            mode='shared_endpoint',
            target_argument_name='cluster',
            target_bindings=(
                ProviderTargetBinding(
                    target_id='openshift/cluster1',
                    argument_value='example-cluster-a',
                ),
                ProviderTargetBinding(
                    target_id='openshift/cluster2',
                    argument_value='example-cluster-b',
                ),
            ),
        )

        self.assertEqual(routing.target_argument_name, 'cluster')
        self.assertEqual(len(routing.target_bindings), 2)

    def test_endpoint_per_target_rejects_shared_fields(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            'requires only target_id',
        ):
            ProviderRoutingConfiguration(
                mode='endpoint_per_target',
                target_id='openshift/cluster1',
                target_argument_name='cluster',
            )

    def test_shared_endpoint_rejects_duplicate_targets(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            'target identities must be unique',
        ):
            ProviderRoutingConfiguration(
                mode='shared_endpoint',
                target_argument_name='cluster',
                target_bindings=(
                    ProviderTargetBinding(
                        target_id='openshift/cluster1',
                        argument_value='example-cluster-a',
                    ),
                    ProviderTargetBinding(
                        target_id='openshift/cluster1',
                        argument_value='duplicate',
                    ),
                ),
            )


if __name__ == '__main__':
    unittest.main()
