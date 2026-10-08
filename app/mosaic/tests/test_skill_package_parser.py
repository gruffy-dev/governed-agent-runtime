import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mosaic.components.skills.skill_package_parser import SkillPackageParser


class TestSkillPackageParser(unittest.TestCase):
    def test_valid_package_builds_immutable_snapshot(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            package_directory = self._write_package(repository_root)
            assets_directory = package_directory / 'assets'
            assets_directory.mkdir()
            (assets_directory / 'result.schema.json').write_text(
                json.dumps(
                    {
                        '$schema': (
                            'https://json-schema.org/draft/2020-12/schema'
                        ),
                        'type': 'object',
                        'properties': {'status': {'type': 'string'}},
                        'required': ['status'],
                    }
                ),
                encoding='utf-8',
            )
            self._write_metadata(
                package_directory,
                output_schema_file='assets/result.schema.json',
            )

            snapshot = SkillPackageParser().parse_catalogue(
                repository_root,
                'a' * 40,
            )

        self.assertEqual(snapshot.commit_sha, 'a' * 40)
        self.assertEqual(len(snapshot.skills), 1)
        self.assertEqual(snapshot.skills[0].name, 'investigate-platform')
        self.assertEqual(snapshot.skills[0].version, '1.0.0')
        self.assertEqual(snapshot.skills[0].output_schema['type'], 'object')

    def test_catalogue_builds_current_hierarchy_groups(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            self._write_package(repository_root)

            snapshot = SkillPackageParser().parse_catalogue(
                repository_root,
                '1' * 40,
            )

        self.assertEqual(
            tuple(group.group_id for group in snapshot.groups),
            (
                'container-platforms',
                'container-platforms/diagnostics',
            ),
        )
        self.assertEqual(
            snapshot.groups[0].skill_ids,
            ('investigate-platform',),
        )

    def test_directory_and_frontmatter_names_must_match(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            self._write_package(
                repository_root,
                directory_name='different-name',
            )

            with self.assertRaises(ValueError):
                SkillPackageParser().parse_catalogue(
                    repository_root,
                    'b' * 40,
                )

    def test_invalid_json_schema_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            package_directory = self._write_package(repository_root)
            assets_directory = package_directory / 'assets'
            assets_directory.mkdir()
            (assets_directory / 'invalid.schema.json').write_text(
                '{"type": 123}',
                encoding='utf-8',
            )
            self._write_metadata(
                package_directory,
                output_schema_file='assets/invalid.schema.json',
            )

            with self.assertRaises(ValueError):
                SkillPackageParser().parse_catalogue(
                    repository_root,
                    'c' * 40,
                )

    def test_executable_skill_scripts_are_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            package_directory = self._write_package(repository_root)
            scripts_directory = package_directory / 'scripts'
            scripts_directory.mkdir()
            script_path = scripts_directory / 'run.sh'
            script_path.write_text('#!/bin/sh\n', encoding='utf-8')
            script_path.chmod(0o700)

            with self.assertRaises(ValueError):
                SkillPackageParser().parse_catalogue(
                    repository_root,
                    'd' * 40,
                )

    def test_flat_skill_package_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            package_directory = self._write_package(repository_root)
            flat_package_directory = (
                repository_root / 'skills' / package_directory.name
            )
            package_directory.rename(flat_package_directory)

            with self.assertRaises(ValueError):
                SkillPackageParser().parse_catalogue(
                    repository_root,
                    'e' * 40,
                )

    def test_duplicate_skill_names_across_domains_are_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            self._write_package(repository_root)
            self._write_package(
                repository_root,
                domain_name='messaging',
            )

            with self.assertRaises(ValueError):
                SkillPackageParser().parse_catalogue(
                    repository_root,
                    'f' * 40,
                )

    def test_unpaired_metadata_file_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            repository_root = Path(temporary_directory)
            self._write_package(repository_root)
            category_metadata_path = (
                repository_root
                / 'skills'
                / 'container-platforms'
                / 'mosaic.yaml'
            )
            category_metadata_path.write_text(
                'schema_version: 1\n',
                encoding='utf-8',
            )

            with self.assertRaises(ValueError):
                SkillPackageParser().parse_catalogue(
                    repository_root,
                    '0' * 40,
                )

    def _write_package(
        self,
        repository_root: Path,
        directory_name: str = 'investigate-platform',
        domain_name: str = 'container-platforms',
        function_name: str = 'diagnostics',
    ) -> Path:
        package_directory = (
            repository_root
            / 'skills'
            / domain_name
            / function_name
            / directory_name
        )
        package_directory.mkdir(parents=True)
        (package_directory / 'SKILL.md').write_text(
            '---\n'
            'name: investigate-platform\n'
            'description: Investigate platform failures using approved data.\n'
            'metadata:\n'
            '  owner: platform-operations\n'
            '---\n\n'
            '# Platform investigation\n\n'
            'Collect the approved evidence and report uncertainty.\n',
            encoding='utf-8',
        )
        self._write_metadata(package_directory)
        return package_directory

    def _write_metadata(
        self,
        package_directory: Path,
        output_schema_file: str | None = None,
    ) -> None:
        schema_line = (
            f'output_schema_file: {output_schema_file}\n'
            if output_schema_file is not None
            else ''
        )
        (package_directory / 'mosaic.yaml').write_text(
            'schema_version: 1\n'
            'version: 1.0.0\n'
            'kind: procedural\n'
            f'{schema_line}'
            'required_capability_names:\n'
            '  - platform.status.read\n'
            'optional_capability_names: []\n',
            encoding='utf-8',
        )


if __name__ == '__main__':
    unittest.main()
