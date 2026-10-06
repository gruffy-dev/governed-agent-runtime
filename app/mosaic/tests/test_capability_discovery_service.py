import unittest
from types import SimpleNamespace

from mosaic.components.capabilities.capability_catalogue_and_resolver import CapabilityCatalogueAndResolver
from mosaic.components.capabilities.capability_discovery_service import CapabilityDiscoveryService
from mosaic.components.capabilities.session_target_resolver import SessionTargetResolver
from mosaic.components.orchestration.ada_session_target_context_store import AdaSessionTargetContextStore
from mosaic.mocks.mock_ada_capability_catalogue import MockAdaCapabilityCatalogue
from mosaic.models.capabilities.capability_discovery_configuration import CapabilityDiscoveryConfiguration
from mosaic.models.orchestration.orchestration_state import OrchestrationState


class TestCapabilityDiscoveryService(unittest.TestCase):
    def test_only_skill_declared_capabilities_are_exposed(self) -> None:
        resolver = self._create_resolver()

        result = resolver.discover_capability_candidates(
            required_capability_names=('openshift.router.logs.read',),
            optional_capability_names=(
                'prometheus.ingress.metrics.read',
            ),
            target_id='openshift/dev',
        )

        names = [item['name'] for item in result['capabilities']]
        self.assertEqual(
            names,
            [
                'openshift.router.logs.read',
                'prometheus.ingress.metrics.read',
            ],
        )
        self.assertNotIn('openshift.ingress.status.read', names)
        self.assertNotIn('provider_name', str(result))
        self.assertNotIn('tool_name', str(result))

    def test_candidate_overflow_fails_without_truncation(self) -> None:
        resolver = self._create_resolver(maximum_candidate_count=1)

        result = resolver.discover_capability_candidates(
            required_capability_names=(
                'openshift.ingress.status.read',
                'openshift.events.read',
            ),
            optional_capability_names=(),
            target_id='openshift/dev',
        )

        self.assertEqual(result['status'], 'limit_exceeded')
        self.assertEqual(result['capabilities'], [])
        self.assertEqual(result['limit_name'], 'maximum_candidate_count')

    def test_service_adds_skill_requirements_from_trusted_state(self) -> None:
        service = self._create_service()
        context = self._context(
            required_capability_names=('mq.queue.depth.read',),
            optional_capability_names=('database.runbook.search',),
        )

        result = service.discover_capabilities(context)

        self.assertEqual(
            [item['name'] for item in result['capabilities']],
            ['mq.queue.depth.read', 'database.runbook.search'],
        )
        self.assertNotIn('target', result)

    def test_target_aware_discovery_requires_a_target(self) -> None:
        service = self._create_service()
        context = self._context(
            required_capability_names=('openshift.events.read',),
        )

        result = service.discover_capabilities(context)

        self.assertEqual(result['status'], 'target_required')
        self.assertEqual(result['capabilities'], [])
        self.assertEqual(result['required_target_verticals'], ['openshift'])

    def test_optional_target_aware_capability_requires_a_target(self) -> None:
        service = self._create_service()
        context = self._context(
            required_capability_names=(),
            optional_capability_names=('openshift.events.read',),
        )

        result = service.discover_capabilities(context)

        self.assertEqual(result['status'], 'target_required')
        self.assertEqual(result['required_target_verticals'], ['openshift'])

    def test_unknown_inferred_target_is_rejected_for_optional_capability(
        self,
    ) -> None:
        service = self._create_service()
        context = self._context(
            required_capability_names=(),
            optional_capability_names=('openshift.events.read',),
        )

        result = service.discover_capabilities(
            context,
            target_name='openshift',
        )

        self.assertEqual(result['status'], 'target_unknown')
        self.assertEqual(result['capabilities'], [])
        self.assertEqual(result['required_target_verticals'], ['openshift'])

    def test_explicit_target_is_resolved_and_reused(self) -> None:
        service = self._create_service()
        context = self._context(
            required_capability_names=('openshift.events.read',),
        )

        first_result = service.discover_capabilities(
            context,
            target_name='development',
        )
        second_result = service.discover_capabilities(context)

        self.assertEqual(first_result['status'], 'available')
        self.assertEqual(
            first_result['target']['target_id'],
            'openshift/dev',
        )
        self.assertEqual(second_result['status'], 'available')
        self.assertEqual(
            second_result['target']['target_id'],
            'openshift/dev',
        )

    def test_service_rejects_discovery_without_a_loaded_skill(self) -> None:
        service = self._create_service()
        state = OrchestrationState.start('invocation-1').model_copy(
            update={'skill_discovery_completed': True}
        )
        context = SimpleNamespace(
            state={'mosaic:orchestration': state.model_dump(mode='json')}
        )

        result = service.discover_capabilities(context)

        self.assertEqual(result['status'], 'skill_required')
        self.assertEqual(result['capabilities'], [])

    def _create_service(self) -> CapabilityDiscoveryService:
        catalogue = MockAdaCapabilityCatalogue.create()
        return CapabilityDiscoveryService(
            capability_catalogue_and_resolver=self._create_resolver(),
            session_target_resolver=SessionTargetResolver(
                targets=catalogue.targets,
                context_store=AdaSessionTargetContextStore(),
            ),
        )

    def _create_resolver(
        self,
        maximum_candidate_count: int = 20,
    ) -> CapabilityCatalogueAndResolver:
        catalogue = MockAdaCapabilityCatalogue.create()
        return CapabilityCatalogueAndResolver(
            capabilities=catalogue.capabilities,
            providers=catalogue.providers,
            discovery_configuration=CapabilityDiscoveryConfiguration(
                maximum_candidate_count=maximum_candidate_count,
            ),
        )

    def _context(
        self,
        required_capability_names: tuple[str, ...],
        optional_capability_names: tuple[str, ...] = (),
    ) -> SimpleNamespace:
        state = OrchestrationState.start('invocation-1').model_copy(
            update={
                'skill_discovery_completed': True,
                'skill_batch_attempted': True,
                'skill_batch_loaded': True,
                'requested_skill_names': ('diagnose',),
                'loaded_skill_names': ('diagnose',),
                'required_capability_names': required_capability_names,
                'optional_capability_names': optional_capability_names,
            }
        )
        return SimpleNamespace(
            state={'mosaic:orchestration': state.model_dump(mode='json')}
        )


if __name__ == '__main__':
    unittest.main()
