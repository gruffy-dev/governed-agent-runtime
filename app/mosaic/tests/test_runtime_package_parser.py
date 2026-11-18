import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dulwich import porcelain
from dulwich.repo import Repo

from mosaic.components.skills.git_skill_catalogue_provider import GitSkillCatalogueProvider
from mosaic.components.skills.runtime_package_parser import RuntimePackageParser
from mosaic.models.skills.git_skill_catalogue_configuration import GitSkillCatalogueConfiguration


class TestRuntimePackageParser(unittest.TestCase):
    def test_same_commit_supplies_skills_and_capabilities(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self._repository(root)
            provider = self._provider(repository, root / 'cache.git')
            with patch.dict(
                os.environ,
                {'MOSAIC_CAPABILITY_RUNTIME_SNAPSHOT_PATH': '/unused/snapshot.json'},
            ):
                snapshot = provider.synchronise()

            with Repo(repository) as source:
                self.assertEqual(snapshot.commit_sha, source.head().decode())
            self.assertEqual(snapshot.skills[0].version, '1.0.0')
            self.assertEqual(snapshot.capability_runtime_snapshot.snapshot_id, 'release-1')
            self.assertNotIn('capability_runtime_snapshot', snapshot.model_dump())
            self.assertEqual(snapshot, provider.get_snapshot())

    def test_new_commit_updates_the_pair(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self._repository(root)
            provider = self._provider(repository, root / 'cache.git')
            first = provider.synchronise()
            self._write_release(repository, '2.0.0', 'release-2')
            self._commit(repository)

            second = provider.synchronise()

            self.assertNotEqual(first.commit_sha, second.commit_sha)
            self.assertEqual(second.skills[0].version, '2.0.0')
            self.assertEqual(second.capability_runtime_snapshot.snapshot_id, 'release-2')

    def test_invalid_candidate_preserves_pair_in_memory_and_after_restart(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self._repository(root)
            cache = root / 'cache.git'
            provider = self._provider(repository, cache)
            first = provider.synchronise()
            self._write_release(repository, '2.0.0', 'release-2')
            (repository / 'config/capability-runtime-snapshot.json').write_text('{')
            self._commit(repository)

            for loader in (provider, self._provider(repository, cache)):
                with self.subTest(loader=type(loader).__name__):
                    retained = loader.synchronise()
                    self.assertEqual(retained.commit_sha, first.commit_sha)
                    self.assertEqual(retained.skills[0].version, '1.0.0')
                    self.assertEqual(
                        retained.capability_runtime_snapshot.snapshot_id,
                        'release-1',
                    )

    def test_missing_file_fails_without_previous_release(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            repository = self._repository(root)
            (repository / 'config/capability-runtime-snapshot.json').unlink()
            self._commit(repository)
            cache = root / 'cache.git'

            with self.assertRaises(RuntimeError):
                self._provider(repository, cache).synchronise()

            self.assertFalse((cache / 'mosaic-active-commit').exists())

    def test_missing_required_or_optional_capability_is_rejected(self) -> None:
        for kind in ('required', 'optional'):
            with self.subTest(kind=kind), TemporaryDirectory() as directory:
                root = Path(directory)
                self._write_release(root, '1.0.0', 'release-1')
                metadata = root / 'skills/itsm/incidents/count-records/mosaic.yaml'
                metadata.write_text(
                    'version: 1.0.0\nkind: procedural\n'
                    f'{kind}_capability_names: [itsm.missing.read]\n'
                )

                with self.assertRaisesRegex(ValueError, 'references must exist'):
                    RuntimePackageParser().parse_catalogue(root, 'a' * 40)

    def test_snapshot_size_limit_is_enforced(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_release(root, '1.0.0', 'release-1')
            with patch.dict(
                os.environ, {'MOSAIC_CAPABILITY_RUNTIME_SNAPSHOT_MAXIMUM_BYTES': '1'}
            ), self.assertRaisesRegex(RuntimeError, 'size limit'):
                RuntimePackageParser().parse_catalogue(root, 'a' * 40)

    def test_result_limit_is_enforced(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_release(root, '1.0.0', 'release-1')
            with patch.dict(
                os.environ, {'MOSAIC_CAPABILITY_RESULT_MAXIMUM_COLLECTION_ITEMS': '1'}
            ), self.assertRaisesRegex(RuntimeError, 'deployment ceiling'):
                RuntimePackageParser().parse_catalogue(root, 'a' * 40)

    def test_invalid_snapshot_schema_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            self._write_release(root, '1.0.0', 'release-1')
            (root / 'config/capability-runtime-snapshot.json').write_text('{}')

            with self.assertRaisesRegex(RuntimeError, 'failed validation'):
                RuntimePackageParser().parse_catalogue(root, 'a' * 40)

    def _repository(self, root: Path) -> Path:
        repository = root / 'repository'
        with porcelain.init(repository) as source:
            source.refs.set_symbolic_ref(b'HEAD', b'refs/heads/main')
        self._write_release(repository, '1.0.0', 'release-1')
        self._commit(repository)
        return repository

    def _provider(self, repository: Path, cache: Path) -> GitSkillCatalogueProvider:
        return GitSkillCatalogueProvider(
            configuration=GitSkillCatalogueConfiguration(
                repository_url=str(repository),
                revision='main',
                repository_cache_path=cache,
                access_token='synthetic-token',
            ),
            package_parser=RuntimePackageParser(),
        )

    def _write_release(self, root: Path, version: str, snapshot_id: str) -> None:
        package = root / 'skills/itsm/incidents/count-records'
        package.mkdir(parents=True, exist_ok=True)
        (package / 'SKILL.md').write_text(
            '---\nname: count-records\ndescription: Count approved records.\n'
            '---\nUse the inventory count capability.\n'
        )
        (package / 'mosaic.yaml').write_text(
            f'version: {version}\nkind: procedural\n'
            'required_capability_names: [inventory.objects.count]\n'
        )
        data = {
            'schema_version': 3,
            'snapshot_id': snapshot_id,
            'targets': [],
            'providers': [
                {
                    'provider_name': 'inventory-mcp',
                    'provider_type': 'inventory',
                    'transport': 'streamable_http',
                    'header_strategy': 'ada_request_context',
                    'base_url': 'https://mcp.example.com/mcp',
                    'allowed_tool_names': ['objects_list'],
                    'routing': {'mode': 'target_independent'},
                }
            ],
            'capabilities': [
                {
                    'name': 'inventory.objects.count',
                    'description': 'Count objects within one scope.',
                    'provider_bindings': [
                        {
                            'provider_type': 'inventory',
                            'tool_name': 'objects_list',
                            'read_only': True,
                            'argument_bindings': [
                                {
                                    'tool_argument_name': 'scope',
                                    'source': 'semantic',
                                    'semantic_argument_names': ['scope'],
                                    'required': True,
                                }
                            ],
                            'result_binding': {
                                'content_source': 'text_content',
                                'content_media_type': 'application/json',
                                'content_block_index': 0,
                                'json_pointer': '/items',
                                'operation': 'count',
                                'output_field': 'object_count',
                                'evidence_tool_argument_names': ['scope'],
                                'maximum_response_characters': 500000,
                                'maximum_collection_items': 2000,
                            },
                        }
                    ],
                }
            ],
        }
        configuration = root / 'config/capability-runtime-snapshot.json'
        configuration.parent.mkdir(exist_ok=True)
        configuration.write_text(json.dumps(data))

    def _commit(self, repository: Path) -> None:
        porcelain.add(repository)
        porcelain.commit(
            repository,
            message=b'Test runtime release',
            author=b'MOSAIC Test <test@example.test>',
            committer=b'MOSAIC Test <test@example.test>',
        )
