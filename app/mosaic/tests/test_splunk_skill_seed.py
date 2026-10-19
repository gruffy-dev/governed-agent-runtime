import shutil
import tempfile
import unittest
from pathlib import Path

from mosaic.components.capabilities.capability_catalogue_and_resolver import CapabilityCatalogueAndResolver
from mosaic.components.capabilities.file_capability_runtime_snapshot_provider import FileCapabilityRuntimeSnapshotProvider
from mosaic.components.capabilities.mcp_capability_result_processor import McpCapabilityResultProcessor
from mosaic.components.skills.skill_package_parser import SkillPackageParser
from mosaic.models.capabilities.capability_runtime_snapshot import CapabilityRuntimeSnapshot
from mosaic.models.capabilities.capability_runtime_snapshot_configuration import CapabilityRuntimeSnapshotConfiguration


class TestSplunkSkillSeed(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]
        self.primary = FileCapabilityRuntimeSnapshotProvider(
            configuration=CapabilityRuntimeSnapshotConfiguration(
                snapshot_path=self.root
                / 'config'
                / 'local'
                / 'capability-runtime-snapshot.json'
            )
        ).load()
        providers = tuple(
            provider for provider in self.primary.providers
            if provider.provider_type in ('splunk', 'splunk-workloads')
        )
        target_ids = {provider.routing.target_id for provider in providers}
        self.snapshot = CapabilityRuntimeSnapshot(
            schema_version=3,
            snapshot_id=self.primary.snapshot_id,
            targets=tuple(
                target for target in self.primary.targets if target.id in target_ids
            ),
            providers=providers,
            capabilities=tuple(
                capability for capability in self.primary.capabilities
                if capability.name.startswith('splunk.')
            ),
        )
        self.workload_target = next(
            provider.routing.target_id for provider in providers
            if provider.provider_type == 'splunk-workloads'
        )
        self.platform_target = next(
            provider.routing.target_id for provider in providers
            if provider.provider_type == 'splunk'
        )
        self.resolver = CapabilityCatalogueAndResolver(
            capabilities=self.snapshot.capabilities,
            providers=self.snapshot.providers,
        )
        self.arguments = {
            'namespace': 'example-tenant',
            'pod_name': 'example-api-abc-123',
            'request_id': 'example-request-123',
            'window': '15m',
        }

    def test_bindings_are_read_only_and_tools_remain_restricted(self) -> None:
        self.assertEqual(len(self.snapshot.capabilities), 10)
        self.assertEqual(
            {
                tool
                for provider in self.snapshot.providers
                for tool in provider.allowed_tool_names
            },
            {'get_indexes', 'search_oneshot'},
        )
        for capability in self.snapshot.capabilities:
            for binding in capability.provider_bindings:
                self.assertTrue(binding.read_only)

    def test_new_searches_bind_matching_time_ranges_and_safe_output(self) -> None:
        for capability in self.snapshot.capabilities:
            if not capability.name.startswith(
                ('splunk.pod.', 'splunk.request.', 'splunk.index.ingestion.',
                 'splunk.index.sources.', 'splunk.index.volume.')
            ):
                continue
            for window in ('15m', '30m', '1h'):
                with self.subTest(capability=capability.name, window=window):
                    invocation = self.resolver.prepare_capability_invocation(
                        capability.name,
                        {**self.arguments, 'window': window},
                        target_id=self.workload_target,
                    )
                    self.assertEqual(invocation['status'], 'ready')
                    arguments = invocation['tool_arguments']
                    self.assertEqual(arguments['earliest_time'], '-' + window)
                    self.assertEqual(arguments['latest_time'], 'now')
                    self.assertIn('earliest=-' + window, arguments['query'])
                    self.assertIn('latest=now', arguments['query'])
                    self.assertEqual(arguments['max_count'], 30)
                    self.assertEqual(arguments['output_format'], 'json')
                    self.assertEqual(arguments['risk_tolerance'], 75)
                    self.assertIs(arguments['sanitize_output'], True)
                    self.assertFalse(arguments['query'].startswith('search '))
                    self.assertEqual(
                        invocation['result_binding']['json_pointer'],
                        '/result/events',
                    )

    def test_templates_expose_only_validated_data_not_arbitrary_spl(self) -> None:
        for capability in self.snapshot.capabilities:
            for binding in capability.provider_bindings:
                for argument in binding.argument_bindings:
                    if argument.tool_argument_name != 'query':
                        continue
                    self.assertIn(argument.source, ('fixed', 'template'))
                    self.assertNotIn('query', argument.semantic_argument_names)
                    self.assertEqual(
                        set(argument.semantic_argument_names),
                        set(argument.semantic_argument_patterns),
                    )
                    query = argument.value_template or argument.fixed_value
                    commands = {
                        segment.strip().split()[0]
                        for segment in query.split(' | ')[1:]
                    }
                    self.assertTrue(
                        commands.issubset(
                            {'eval', 'where', 'head', 'table', 'stats', 'bin', 'sort'}
                        )
                    )

    def test_namespace_pod_request_and_window_injection_is_rejected(self) -> None:
        scenarios = (
            ('splunk.pod.logs.read', 'namespace', '*'),
            ('splunk.pod.logs.read', 'namespace', '_internal'),
            ('splunk.pod.logs.read', 'namespace', 'example" OR index=*'),
            ('splunk.pod.logs.read', 'namespace', 'example\n| delete'),
            ('splunk.pod.logs.read', 'namespace', 'a' * 64),
            ('splunk.pod.logs.read', 'pod_name', '*'),
            ('splunk.pod.logs.read', 'pod_name', 'example" OR 1=1'),
            ('splunk.request.trace.read', 'request_id', '`macro`'),
            ('splunk.request.trace.read', 'request_id', 'example | outputlookup x'),
            ('splunk.request.trace.read', 'request_id', 'example\\id'),
            ('splunk.pod.logs.read', 'window', '24h'),
            ('splunk.pod.logs.read', 'window', '15m | delete'),
            ('splunk.pod.logs.read', 'window', 15),
        )
        for name, argument, value in scenarios:
            with self.subTest(capability=name, argument=argument, value=value):
                invocation = self.resolver.prepare_capability_invocation(
                    name,
                    {**self.arguments, argument: value},
                    target_id=self.workload_target,
                )
                self.assertEqual(invocation['status'], 'invalid_arguments')

    def test_caller_cannot_override_query_limits_or_provider_controls(self) -> None:
        overrides = {
            'query': '| delete',
            'max_count': 0,
            'earliest_time': '0',
            'latest_time': '+1y',
            'output_format': 'csv',
            'risk_tolerance': 100,
            'sanitize_output': False,
            'index': '*',
        }
        invocation = self.resolver.prepare_capability_invocation(
            'splunk.pod.logs.read',
            {**self.arguments, **overrides},
            target_id=self.workload_target,
        )
        self.assertEqual(invocation['status'], 'ready')
        self.assertEqual(
            set(invocation['ignored_semantic_argument_names']),
            set(overrides) | {'request_id'},
        )
        arguments = invocation['tool_arguments']
        self.assertEqual(arguments['max_count'], 30)
        self.assertEqual(arguments['earliest_time'], '-15m')
        self.assertEqual(arguments['latest_time'], 'now')
        self.assertEqual(arguments['risk_tolerance'], 75)
        self.assertIs(arguments['sanitize_output'], True)
        self.assertNotIn('delete', arguments['query'])

    def test_platform_and_workload_routes_remain_separate(self) -> None:
        for target in (None, self.platform_target, 'container-platforms/unknown'):
            invocation = self.resolver.prepare_capability_invocation(
                'splunk.pod.logs.read', self.arguments, target_id=target
            )
            self.assertEqual(invocation['status'], 'unavailable')
        invocation = self.resolver.prepare_capability_invocation(
            'splunk.internal.errors.read',
            {},
            target_id=self.workload_target,
        )
        self.assertEqual(invocation['status'], 'unavailable')
        invocation = self.resolver.prepare_capability_invocation(
            'splunk.indexes.read', {}, target_id=self.workload_target
        )
        self.assertEqual(invocation['status'], 'unavailable')

    def test_existing_activity_outcome_is_available_on_both_approved_targets(
        self,
    ) -> None:
        for target in (self.platform_target, self.workload_target):
            invocation = self.resolver.prepare_capability_invocation(
                'splunk.index.activity.count',
                {'index_name': 'example-tenant'},
                target_id=target,
            )
            self.assertEqual(invocation['status'], 'ready')
            self.assertEqual(invocation['tool_arguments']['max_count'], 1)
        invocation = self.resolver.prepare_capability_invocation(
            'splunk.index.activity.count',
            {'index_name': '_internal'},
            target_id=self.workload_target,
        )
        self.assertEqual(invocation['status'], 'invalid_arguments')

    def test_structured_result_wrapper_and_failure_are_distinguished(self) -> None:
        invocation = self.resolver.prepare_capability_invocation(
            'splunk.pod.logs.read', self.arguments,
            target_id=self.workload_target,
        )
        binding = next(
            capability.provider_bindings[0].result_binding
            for capability in self.snapshot.capabilities
            if capability.name == 'splunk.pod.logs.read'
        )
        processor = McpCapabilityResultProcessor()
        for events in ([], [{'_time': '1800000000', 'log_excerpt': 'Synthetic log'}]):
            result = processor.process(
                {'structuredContent': {'result': {'events': events}}},
                binding, invocation['tool_arguments'],
            )
            self.assertEqual(result['pod_log_evidence'], events)
        with self.assertRaises(LookupError):
            processor.process(
                {'structuredContent': {'result': {'error': 'Synthetic denial'}}},
                binding, invocation['tool_arguments'],
            )
        with self.assertRaises(ValueError):
            processor.process({'isError': True}, binding, {})
        with self.assertRaises(ValueError):
            processor.process(
                {'structuredContent': {'result': {'events': [{}] * 31}}},
                binding, invocation['tool_arguments'],
            )

    def test_function_hierarchy_skill_ids_and_cross_domain_references(self) -> None:
        source = self.root / 'mosaic-skill-catalogue' / 'skills'
        packages = [
            *sorted((source / 'splunk').glob('*/*')),
            source / 'container-platforms' / 'investigations'
            / 'investigate-openshift-application-logs',
        ]
        packages = [path for path in packages if (path / 'SKILL.md').is_file()]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for package in packages:
                shutil.copytree(package, root / 'skills' / package.relative_to(source))
            catalogue = SkillPackageParser().parse_catalogue(root, 'a' * 40)
        self.assertEqual(len(catalogue.skills), 8)
        self.assertEqual(
            {path.parts[-2] for path in packages},
            {'indexes', 'platform-health', 'investigations', 'application-logs',
             'ingestion', 'request-tracing', 'volume'},
        )
        external = {
            'kubernetes.pods.status.read', 'kubernetes.events.read',
            'kubernetes.pod.detail.read', 'kubernetes.pod.logs.read',
            'kubernetes.deployments.status.read',
        }
        known = {capability.name for capability in self.snapshot.capabilities}
        for skill in catalogue.skills:
            references = set(skill.required_capability_names) | set(
                skill.optional_capability_names
            )
            self.assertTrue(references.issubset(known | external))
        cross_domain = next(
            skill for skill in catalogue.skills
            if skill.name == 'investigate-openshift-application-logs'
        )
        self.assertIn('kubernetes.events.read', cross_domain.required_capability_names)
        self.assertIn('splunk.pod.logs.read', cross_domain.required_capability_names)

    def test_cross_domain_requirements_resolve_without_switching_targets(self) -> None:
        names = ('kubernetes.pods.status.read', 'kubernetes.events.read')
        resolver = CapabilityCatalogueAndResolver(
            capabilities=self.primary.capabilities,
            providers=self.primary.providers,
        )
        result = resolver.resolve_capabilities(
            [*names, 'splunk.pod.logs.read'],
            target_id=self.workload_target,
        )
        self.assertEqual(result['status'], 'resolved')

    def test_primary_contains_container_mq_and_splunk_without_name_collisions(
        self,
    ) -> None:
        names = [capability.name for capability in self.primary.capabilities]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({
            'kubernetes.pods.status.read',
            'mq.queue.status.read',
            'splunk.index.activity.count',
            'splunk.pod.logs.read',
        }.issubset(names))
