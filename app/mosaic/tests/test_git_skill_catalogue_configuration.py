"""Tests for trusted Git skill-catalogue configuration."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from mosaic.models.skills.git_skill_catalogue_configuration import (
    GitSkillCatalogueConfiguration,
)


class TestGitSkillCatalogueConfiguration(unittest.TestCase):
    """Verify environment loading and secret-safe validation."""

    def test_environment_configuration_excludes_credentials_from_dump(
        self,
    ) -> None:
        environment = {
            'MOSAIC_SKILLS_REPOSITORY_URL': (
                'https://bitbucket.example/skills.git'
            ),
            'MOSAIC_SKILLS_REPOSITORY_REVISION': 'release/mvp',
            'MOSAIC_SKILLS_REPOSITORY_CACHE_PATH': (
                '/tmp/mosaic-test/skills.git'
            ),
            'MOSAIC_SKILLS_REPOSITORY_ACCESS_TOKEN': 'secret-token',
            'MOSAIC_SKILLS_SYNCHRONIZATION_TIMEOUT_SECONDS': '30',
        }

        with patch.dict(os.environ, environment, clear=True):
            configuration = GitSkillCatalogueConfiguration()

        self.assertEqual(configuration.revision, 'release/mvp')
        self.assertEqual(
            configuration.repository_cache_path,
            Path('/tmp/mosaic-test/skills.git'),
        )
        self.assertEqual(configuration.synchronisation_timeout_seconds, 30)
        self.assertEqual(
            configuration.model_dump()['synchronisation_timeout_seconds'], 30
        )
        self.assertNotIn('access_token', configuration.model_dump())
        self.assertNotIn('secret-token', repr(configuration))

    def test_british_timeout_field_accepts_explicit_configuration(self) -> None:
        configuration = GitSkillCatalogueConfiguration(
            repository_url='https://example.test/skills.git',
            access_token='synthetic-token',
            synchronisation_timeout_seconds=17,
        )
        self.assertEqual(configuration.synchronisation_timeout_seconds, 17)

    def test_timeout_limits_are_enforced(self) -> None:
        for timeout in (0, -1, 301):
            with self.subTest(timeout=timeout), self.assertRaises(ValidationError):
                GitSkillCatalogueConfiguration(
                    repository_url='https://example.test/skills.git',
                    access_token='synthetic-token',
                    synchronisation_timeout_seconds=timeout,
                )

    def test_embedded_repository_credentials_are_rejected(self) -> None:
        """Repository URLs cannot carry credentials that may reach logs."""
        with self.assertRaises(ValidationError):
            GitSkillCatalogueConfiguration(
                repository_url='https://user:secret@example.test/skills.git',
                access_token='secret-token',
            )

    def test_repository_access_token_is_required(self) -> None:
        """Startup requires a Bearer token for the private repository."""
        with self.assertRaises(ValidationError):
            GitSkillCatalogueConfiguration(
                repository_url='https://example.test/skills.git',
            )

    def test_access_token_with_newline_is_rejected(self) -> None:
        """Bearer tokens cannot inject additional HTTP headers."""
        with self.assertRaises(ValidationError):
            GitSkillCatalogueConfiguration(
                repository_url='https://example.test/skills.git',
                access_token='secret-token\ninjected-header',
            )

    def test_repository_url_is_required_from_environment(self) -> None:
        """Startup fails clearly when no live repository is configured."""
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaises(ValidationError),
        ):
            GitSkillCatalogueConfiguration()


if __name__ == '__main__':
    unittest.main()
