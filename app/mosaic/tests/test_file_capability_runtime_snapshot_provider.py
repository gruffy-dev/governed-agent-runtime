import json
import tempfile
import unittest
from pathlib import Path

from mosaic.components.capabilities.file_capability_runtime_snapshot_provider import FileCapabilityRuntimeSnapshotProvider
from mosaic.models.capabilities.capability_runtime_snapshot import CapabilityRuntimeSnapshot
from mosaic.models.capabilities.capability_runtime_snapshot_configuration import CapabilityRuntimeSnapshotConfiguration


class TestFileCapabilityRuntimeSnapshotProvider(unittest.TestCase):
    def test_valid_snapshot_is_loaded(self) -> None:
        snapshot = self._load(self._snapshot_data())

        self.assertEqual(snapshot.snapshot_id, 'inventory-2026.08.24')
        self.assertEqual(snapshot.targets[0].id, 'inventory/warehouse1')
        self.assertEqual(snapshot.providers[0].provider_name, 'inventory-mcp')
        self.assertEqual(
            snapshot.capabilities[0].name,
            'inventory.objects.count',
        )

    def test_non_allowlisted_binding_is_rejected(self) -> None:
        snapshot_data = self._snapshot_data()
        snapshot_data['capabilities'][0]['provider_bindings'][0][
            'tool_name'
        ] = 'undeclared_tool'

        with self.assertRaisesRegex(RuntimeError, 'failed validation'):
            self._load(snapshot_data)

    def test_unknown_provider_target_is_rejected(self) -> None:
        snapshot_data = self._snapshot_data()
        snapshot_data['providers'][0]['routing']['target_id'] = (
            'inventory/missing'
        )

        with self.assertRaisesRegex(RuntimeError, 'failed validation'):
            self._load(snapshot_data)

    def test_duplicate_alias_within_vertical_is_rejected(self) -> None:
        snapshot_data = self._snapshot_data()
        snapshot_data['targets'].append(
            {
                'id': 'inventory/warehouse2',
                'display_name': 'Secondary warehouse',
                'aliases': ['WAREHOUSE'],
            }
        )

        with self.assertRaisesRegex(RuntimeError, 'failed validation'):
            self._load(snapshot_data)

    def test_duplicate_alias_across_verticals_is_accepted(self) -> None:
        snapshot_data = self._snapshot_data()
        snapshot_data['targets'].append(
            {
                'id': 'databases/warehouse1',
                'display_name': 'Warehouse database',
                'aliases': ['warehouse'],
            }
        )

        snapshot = self._load(snapshot_data)

        self.assertEqual(len(snapshot.targets), 2)

    def test_ambiguous_provider_type_and_target_is_rejected(self) -> None:
        snapshot_data = self._snapshot_data()
        duplicate_provider = dict(snapshot_data['providers'][0])
        duplicate_provider['provider_name'] = 'inventory-mcp-duplicate'
        duplicate_provider['base_url'] = 'https://duplicate.example/mcp'
        duplicate_provider['routing'] = dict(
            snapshot_data['providers'][0]['routing']
        )
        snapshot_data['providers'].append(duplicate_provider)

        with self.assertRaisesRegex(RuntimeError, 'failed validation'):
            self._load(snapshot_data)

    def test_legacy_snapshot_schema_is_rejected(self) -> None:
        snapshot_data = self._snapshot_data()
        snapshot_data['schema_version'] = 2

        with self.assertRaisesRegex(RuntimeError, 'failed validation'):
            self._load(snapshot_data)

    def test_deployment_result_ceilings_are_enforced(self) -> None:
        scenarios = (
            ('maximum_response_characters', 10001, 'response limit'),
            ('maximum_collection_items', 101, 'collection limit'),
        )
        for field_name, field_value, expected_message in scenarios:
            with self.subTest(field_name=field_name):
                snapshot_data = self._snapshot_data()
                result_binding = snapshot_data['capabilities'][0][
                    'provider_bindings'
                ][0]['result_binding']
                result_binding[field_name] = field_value

                with self.assertRaisesRegex(
                    RuntimeError,
                    expected_message,
                ):
                    self._load(snapshot_data)

    def _load(
        self,
        snapshot_data: dict[str, object],
    ) -> CapabilityRuntimeSnapshot:
        with tempfile.TemporaryDirectory() as temporary_directory:
            snapshot_path = Path(temporary_directory) / 'snapshot.json'
            snapshot_path.write_text(
                json.dumps(snapshot_data),
                encoding='utf-8',
            )
            provider = FileCapabilityRuntimeSnapshotProvider(
                configuration=CapabilityRuntimeSnapshotConfiguration(
                    snapshot_path=snapshot_path,
                    maximum_snapshot_bytes=10000,
                    maximum_result_response_characters=10000,
                    maximum_result_collection_items=100,
                )
            )
            return provider.load()

    def _snapshot_data(self) -> dict[str, object]:
        return {
            'schema_version': 3,
            'snapshot_id': 'inventory-2026.08.24',
            'targets': [
                {
                    'id': 'inventory/warehouse1',
                    'display_name': 'Primary warehouse',
                    'aliases': ['warehouse', 'primary'],
                }
            ],
            'providers': [
                {
                    'provider_name': 'inventory-mcp',
                    'provider_type': 'inventory',
                    'transport': 'streamable_http',
                    'header_strategy': 'ada_request_context',
                    'base_url': 'https://inventory.example/mcp',
                    'allowed_tool_names': ['objects_list'],
                    'routing': {
                        'mode': 'endpoint_per_target',
                        'target_id': 'inventory/warehouse1',
                    },
                }
            ],
            'capabilities': [
                {
                    'name': 'inventory.objects.count',
                    'description': 'Count objects in one scope.',
                    'provider_bindings': [
                        {
                            'provider_type': 'inventory',
                            'tool_name': 'objects_list',
                            'argument_bindings': [
                                {
                                    'tool_argument_name': 'scope',
                                    'source': 'semantic',
                                    'semantic_argument_names': ['scope'],
                                }
                            ],
                            'result_binding': {
                                'content_source': 'structured_content',
                                'content_media_type': None,
                                'content_block_index': None,
                                'json_pointer': '/items',
                                'operation': 'count',
                                'output_field': 'object_count',
                                'evidence_tool_argument_names': ['scope'],
                                'maximum_response_characters': 10000,
                                'maximum_collection_items': 100,
                            },
                        }
                    ],
                }
            ],
        }


if __name__ == '__main__':
    unittest.main()
