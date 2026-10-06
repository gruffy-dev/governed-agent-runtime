"""Tests for Git-binary-free skill-catalogue synchronisation."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dulwich import porcelain
from dulwich.repo import Repo

from mosaic.components.skills.git_skill_catalogue_provider import (
    GitSkillCatalogueProvider,
)
from mosaic.components.skills.skill_package_parser import SkillPackageParser
from mosaic.models.skills.git_skill_catalogue_configuration import (
    GitSkillCatalogueConfiguration,
)


class TestGitSkillCatalogueProvider(unittest.TestCase):
    """Verify live refresh, immutable activation, and safe fallback."""

    def test_valid_remote_commit_is_synchronized(self) -> None:
        """The provider clones and activates a validated remote commit."""
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            provider = self._create_provider(
                repository_path,
                temporary_root / 'cache.git',
            )

            snapshot = provider.synchronize()

            self.assertEqual(snapshot, provider.get_snapshot())
            self.assertEqual(
                snapshot.commit_sha,
                self._head_commit(repository_path),
            )
            self.assertEqual(snapshot.skills[0].version, '1.0.0')

    def test_synchronization_does_not_require_git_executable(self) -> None:
        """Dulwich synchronizes successfully with no executable search path."""
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            provider = self._create_provider(
                repository_path,
                temporary_root / 'cache.git',
            )

            with patch.dict(os.environ, {'PATH': ''}):
                snapshot = provider.synchronize()

            self.assertEqual(snapshot.skills[0].name, 'investigate-platform')

    def test_bearer_token_is_not_persisted_in_repository_cache(self) -> None:
        """The bare Git cache must not retain its Bearer credential."""
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            cache_path = temporary_root / 'cache.git'
            provider = self._create_provider(repository_path, cache_path)

            provider.synchronize()

            cache_configuration = (cache_path / 'config').read_text(
                encoding='utf-8'
            )
            self.assertNotIn('test-token', cache_configuration)
            self.assertNotIn(
                'extraheader',
                cache_configuration.lower(),
            )

    def test_new_valid_commit_replaces_active_snapshot(self) -> None:
        """A later valid remote commit becomes the active snapshot."""
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            provider = self._create_provider(
                repository_path,
                temporary_root / 'cache.git',
            )
            first_snapshot = provider.synchronize()
            self._write_package(repository_path, version='1.1.0')
            self._commit(repository_path, 'Update skill')

            second_snapshot = provider.synchronize()

            self.assertNotEqual(
                first_snapshot.commit_sha,
                second_snapshot.commit_sha,
            )
            self.assertEqual(second_snapshot.skills[0].version, '1.1.0')

    def test_invalid_new_commit_preserves_last_valid_snapshot(self) -> None:
        """An invalid remote update cannot replace validated active skills."""
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            cache_path = temporary_root / 'cache.git'
            provider = self._create_provider(repository_path, cache_path)
            first_snapshot = provider.synchronize()
            metadata_path = (
                repository_path
                / 'skills'
                / 'container-platforms'
                / 'diagnostics'
                / 'investigate-platform'
                / 'mosaic.yaml'
            )
            metadata_path.write_text(
                'schema_version: 1\nversion: invalid\nkind: procedural\n',
                encoding='utf-8',
            )
            self._commit(repository_path, 'Invalid skill')

            retained_snapshot = provider.synchronize()
            restarted_provider = self._create_provider(
                repository_path,
                cache_path,
            )
            restarted_snapshot = restarted_provider.synchronize()

            self.assertEqual(retained_snapshot, first_snapshot)
            self.assertEqual(
                restarted_snapshot.commit_sha,
                first_snapshot.commit_sha,
            )

    def test_unavailable_remote_recovers_persisted_snapshot(self) -> None:
        """A restart can use the last valid commit while Git is unavailable."""
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            cache_path = temporary_root / 'cache.git'
            provider = self._create_provider(repository_path, cache_path)
            first_snapshot = provider.synchronize()
            unavailable_repository_path = temporary_root / 'offline-repository'
            repository_path.rename(unavailable_repository_path)
            restarted_provider = self._create_provider(
                repository_path,
                cache_path,
            )

            recovered_snapshot = restarted_provider.synchronize()

            self.assertEqual(
                recovered_snapshot.commit_sha,
                first_snapshot.commit_sha,
            )

    def test_get_snapshot_requires_prior_synchronization(self) -> None:
        """Read-only access fails clearly before initial synchronization."""
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            provider = self._create_provider(
                temporary_root / 'repository',
                temporary_root / 'cache.git',
            )

            with self.assertRaises(RuntimeError):
                provider.get_snapshot()

    def _create_repository(self, temporary_root: Path) -> Path:
        """Create a local Git repository containing one valid skill.

        Args:
            temporary_root: Temporary directory containing test resources.

        Returns:
            Path of the initialized source repository.
        """
        repository_path = temporary_root / 'repository'
        repository = porcelain.init(repository_path)
        repository.refs.set_symbolic_ref(b'HEAD', b'refs/heads/main')
        repository.close()
        self._write_package(repository_path, version='1.0.0')
        self._commit(repository_path, 'Initial skill')
        return repository_path

    def _create_provider(
        self,
        repository_path: Path,
        cache_path: Path,
    ) -> GitSkillCatalogueProvider:
        """Create a provider targeting the local test repository.

        Args:
            repository_path: Local repository acting as the remote source.
            cache_path: Bare cache path for the provider.

        Returns:
            Configured Git-backed catalogue provider.
        """
        return GitSkillCatalogueProvider(
            configuration=GitSkillCatalogueConfiguration(
                repository_url=str(repository_path),
                revision='main',
                repository_cache_path=cache_path,
                access_token='test-token',
            ),
            package_parser=SkillPackageParser(),
        )

    def _write_package(self, repository_path: Path, version: str) -> None:
        """Write or update the repository's valid skill package.

        Args:
            repository_path: Source repository receiving the package.
            version: Semantic version written to ``mosaic.yaml``.
        """
        package_directory = (
            repository_path
            / 'skills'
            / 'container-platforms'
            / 'diagnostics'
            / 'investigate-platform'
        )
        package_directory.mkdir(parents=True, exist_ok=True)
        (package_directory / 'SKILL.md').write_text(
            '---\n'
            'name: investigate-platform\n'
            'description: Investigate platform failures.\n'
            '---\n\n'
            '# Investigation\n\n'
            'Collect approved platform evidence.\n',
            encoding='utf-8',
        )
        (package_directory / 'mosaic.yaml').write_text(
            'schema_version: 1\n'
            f'version: {version}\n'
            'kind: procedural\n'
            'required_capability_names:\n'
            '  - platform.status.read\n'
            'optional_capability_names: []\n',
            encoding='utf-8',
        )

    def _commit(self, repository_path: Path, message: str) -> None:
        """Commit all test-repository changes.

        Args:
            repository_path: Source repository receiving the commit.
            message: Commit message.
        """
        porcelain.add(repository_path)
        porcelain.commit(
            repository_path,
            message=message,
            author=b'MOSAIC Test <test@example.test>',
            committer=b'MOSAIC Test <test@example.test>',
        )

    def _head_commit(self, repository_path: Path) -> str:
        """Read the source repository's current commit with Dulwich.

        Args:
            repository_path: Source repository containing the commit.

        Returns:
            Full lowercase commit identifier.
        """
        with Repo(repository_path) as repository:
            return repository.head().decode('ascii').lower()


if __name__ == '__main__':
    unittest.main()
