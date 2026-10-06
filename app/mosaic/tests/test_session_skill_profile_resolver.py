"""Tests for immutable session skill-profile resolution."""

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from mosaic.components.skills.session_skill_profile_resolver import (
    SessionSkillProfileResolver,
)
from mosaic.models.skills.session_skill_profile_configuration import (
    SessionSkillProfileConfiguration,
)
from mosaic.models.skills.skill import Skill
from mosaic.models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot


class TestSessionSkillProfileResolver(unittest.TestCase):
    """Verify default, assigned, and invalid profile resolution."""

    def test_sessions_resolve_to_different_profiles(self) -> None:
        """An explicit session assignment overrides the trusted default."""
        resolver = SessionSkillProfileResolver(
            configuration=self._create_configuration(),
            catalogue_snapshot=self._create_snapshot(),
        )

        platform_profile = resolver.resolve('platform-session')
        database_profile = resolver.resolve('database-session')

        self.assertEqual(platform_profile.profile_id, 'platform-demo')
        self.assertEqual(database_profile.profile_id, 'database-demo')
        self.assertEqual(
            database_profile.allowed_skill_names,
            ('match-database-runbook',),
        )
        self.assertEqual(database_profile.catalogue_commit_sha, 'a' * 40)

    def test_profile_cannot_reference_an_absent_skill(self) -> None:
        """Deployment configuration cannot authorise missing catalogue data."""
        configuration = SessionSkillProfileConfiguration(
            profiles={'invalid-demo': ('missing-skill',)},
            default_profile_id='invalid-demo',
        )

        with self.assertRaises(ValidationError):
            SessionSkillProfileResolver(
                configuration=configuration,
                catalogue_snapshot=self._create_snapshot(),
            )

    def test_profile_exceeding_discovery_budget_is_rejected(self) -> None:
        """Authorised summaries must fit their configured exposure budget."""
        configuration = SessionSkillProfileConfiguration(
            profiles={
                'platform-demo': ('investigate-openshift-ingress',),
            },
            default_profile_id='platform-demo',
            maximum_discovery_metadata_characters=10,
        )

        with self.assertRaisesRegex(ValidationError, 'metadata size'):
            SessionSkillProfileResolver(
                configuration=configuration,
                catalogue_snapshot=self._create_snapshot(),
            )

    def _create_configuration(self) -> SessionSkillProfileConfiguration:
        """Create trusted profiles for two demonstration sessions.

        Returns:
            Validated platform and database profile configuration.
        """
        return SessionSkillProfileConfiguration(
            profiles={
                'platform-demo': ('investigate-openshift-ingress',),
                'database-demo': ('match-database-runbook',),
            },
            default_profile_id='platform-demo',
            session_profile_assignments={
                'database-session': 'database-demo',
            },
        )

    def _create_snapshot(self) -> SkillCatalogueSnapshot:
        """Create an immutable two-skill catalogue fixture.

        Returns:
            Snapshot containing platform and database demonstration skills.
        """
        return SkillCatalogueSnapshot(
            commit_sha='a' * 40,
            loaded_at=datetime.now(timezone.utc),
            skills=(
                Skill(
                    name='investigate-openshift-ingress',
                    version='1.0.0',
                    kind='procedural',
                    description='Investigate OpenShift ingress.',
                    instruction='Collect approved ingress evidence.',
                ),
                Skill(
                    name='match-database-runbook',
                    version='1.0.0',
                    kind='procedural',
                    description='Match an approved database runbook.',
                    instruction='Search and retrieve the exact runbook.',
                ),
            ),
        )


if __name__ == '__main__':
    unittest.main()
