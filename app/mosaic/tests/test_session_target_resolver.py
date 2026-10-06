import unittest
from types import SimpleNamespace

from mosaic.components.capabilities.session_target_resolver import SessionTargetResolver
from mosaic.components.orchestration.ada_session_target_context_store import AdaSessionTargetContextStore
from mosaic.models.capabilities.target_definition import TargetDefinition


class TestSessionTargetResolver(unittest.TestCase):
    def setUp(self) -> None:
        self.store = AdaSessionTargetContextStore()
        self.context = SimpleNamespace(state={})
        self.resolver = SessionTargetResolver(
            targets=(
                TargetDefinition(
                    id='openshift/cluster1',
                    display_name='UK development OpenShift',
                    aliases=('cluster1', 'uk-dev'),
                ),
                TargetDefinition(
                    id='databases/cluster1',
                    display_name='Payments development database',
                    aliases=('cluster1', 'payments-db'),
                ),
                TargetDefinition(
                    id='openshift/cluster2',
                    display_name='UK test OpenShift',
                    aliases=('cluster2', 'uk-test'),
                ),
            ),
            context_store=self.store,
        )

    def test_missing_target_requires_user_input(self) -> None:
        result = self.resolver.resolve(self.context)

        self.assertEqual(result.status, 'required')

    def test_vertical_context_resolves_duplicate_alias(self) -> None:
        result = self.resolver.resolve(
            self.context,
            target_name='cluster1',
            allowed_verticals=('openshift',),
        )

        self.assertEqual(result.status, 'resolved')
        self.assertEqual(
            result.resolved_target.target_id,
            'openshift/cluster1',
        )
        self.assertEqual(
            self.store.get(self.context).target_id,
            'openshift/cluster1',
        )

    def test_unscoped_duplicate_alias_is_ambiguous(self) -> None:
        result = self.resolver.resolve(
            self.context,
            target_name='cluster1',
        )

        self.assertEqual(result.status, 'ambiguous')
        self.assertEqual(
            tuple(
                candidate.display_name
                for candidate in result.candidate_targets
            ),
            (
                'UK development OpenShift',
                'Payments development database',
            ),
        )
        self.assertIsNone(self.store.get(self.context))

    def test_current_target_is_reused(self) -> None:
        self.store.set(self.context, 'openshift/cluster1')

        result = self.resolver.resolve(self.context)

        self.assertEqual(result.status, 'resolved')
        self.assertEqual(
            result.resolved_target.target_id,
            'openshift/cluster1',
        )
        self.assertFalse(result.target_changed)

    def test_explicit_target_change_is_recorded(self) -> None:
        self.store.set(self.context, 'openshift/cluster1')

        result = self.resolver.resolve(
            self.context,
            target_name='cluster2',
        )

        self.assertEqual(result.status, 'resolved')
        self.assertTrue(result.target_changed)
        self.assertEqual(
            result.previous_target.target_id,
            'openshift/cluster1',
        )
        self.assertEqual(
            result.resolved_target.target_id,
            'openshift/cluster2',
        )

    def test_unknown_explicit_target_does_not_fall_back(self) -> None:
        self.store.set(self.context, 'openshift/cluster1')

        result = self.resolver.resolve(
            self.context,
            target_name='missing',
        )

        self.assertEqual(result.status, 'unknown')
        self.assertIsNone(result.resolved_target)
        self.assertEqual(
            self.store.get(self.context).target_id,
            'openshift/cluster1',
        )

    def test_stale_persisted_target_is_cleared(self) -> None:
        self.store.set(self.context, 'openshift/retired')

        result = self.resolver.resolve(self.context)

        self.assertEqual(result.status, 'required')
        self.assertIsNone(self.store.get(self.context))


if __name__ == '__main__':
    unittest.main()
