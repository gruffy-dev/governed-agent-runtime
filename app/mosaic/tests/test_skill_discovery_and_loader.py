"""Tests for session-authorised skill discovery and loading."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from mosaic.components.skills.session_skill_profile_manager import (
    SessionSkillProfileManager,
)
from mosaic.components.skills.session_skill_profile_resolver import (
    SessionSkillProfileResolver,
)
from mosaic.components.skills.skill_discovery_and_loader import (
    SkillDiscoveryAndLoader,
)
from mosaic.models.skills.session_skill_profile_configuration import (
    SessionSkillProfileConfiguration,
)
from mosaic.models.skills.skill import Skill
from mosaic.models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot


class TestSkillDiscoveryAndLoader(unittest.TestCase):
    """Verify profile isolation at both progressive-disclosure boundaries."""

    def test_sessions_discover_and_load_only_authorised_skills(self) -> None:
        """Different sessions cannot discover or load one another's skills."""
        loader = self._create_loader()
        platform_context = SimpleNamespace(
            session=SimpleNamespace(id='platform-session'),
            state={},
        )
        database_context = SimpleNamespace(
            session=SimpleNamespace(id='database-session'),
            state={},
        )

        platform_catalogue = loader.discover_skills(platform_context)
        database_catalogue = loader.discover_skills(database_context)
        platform_load = loader.load_skills(
            [
                'investigate-openshift-ingress',
                'match-database-runbook',
            ],
            platform_context,
        )

        self.assertEqual(
            [skill['name'] for skill in platform_catalogue['skills']],
            ['investigate-openshift-ingress'],
        )
        self.assertEqual(
            [skill['name'] for skill in database_catalogue['skills']],
            ['match-database-runbook'],
        )
        self.assertEqual(platform_load['status'], 'not_found')
        self.assertEqual(platform_load['loaded_skills'], [])
        self.assertEqual(
            platform_load['not_found_skill_names'],
            ['match-database-runbook'],
        )

        approved_load = loader.load_skills(
            ['investigate-openshift-ingress'],
            platform_context,
        )
        self.assertEqual(approved_load['status'], 'loaded')
        self.assertEqual(
            [skill['name'] for skill in approved_load['loaded_skills']],
            ['investigate-openshift-ingress'],
        )

    def test_caller_supplied_profile_state_cannot_expand_access(self) -> None:
        """Trusted configuration overwrites a forged session-state profile."""
        loader = self._create_loader()
        context = SimpleNamespace(
            session=SimpleNamespace(id='platform-session'),
            state={
                'mosaic:skill-profile': {
                    'profile_id': 'database-demo',
                    'allowed_skill_names': ['match-database-runbook'],
                    'catalogue_commit_sha': 'a' * 40,
                }
            },
        )

        result = loader.load_skills(
            ['match-database-runbook'],
            context,
        )

        self.assertEqual(result['status'], 'not_found')
        self.assertEqual(
            context.state['mosaic:skill-profile']['profile_id'],
            'platform-demo',
        )

    def test_oversized_full_skill_batch_is_not_partially_loaded(self) -> None:
        """Full skill content is withheld when the configured limit is hit."""
        loader = self._create_loader(maximum_loaded_skill_characters=10)
        context = SimpleNamespace(
            session=SimpleNamespace(id='platform-session'),
            state={},
        )

        result = loader.load_skills(
            ['investigate-openshift-ingress'],
            context,
        )

        self.assertEqual(result['status'], 'limit_exceeded')
        self.assertEqual(result['loaded_skills'], [])

    def _create_loader(
        self,
        maximum_loaded_skill_characters: int = 50000,
    ) -> SkillDiscoveryAndLoader:
        """Create a loader with two isolated demonstration profiles.

        Returns:
            Session-authorised loader backed by an immutable snapshot.
        """
        snapshot = SkillCatalogueSnapshot(
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
        configuration = SessionSkillProfileConfiguration(
            profiles={
                'platform-demo': ('investigate-openshift-ingress',),
                'database-demo': ('match-database-runbook',),
            },
            default_profile_id='platform-demo',
            session_profile_assignments={
                'database-session': 'database-demo',
            },
            maximum_loaded_skill_characters=(
                maximum_loaded_skill_characters
            ),
        )
        resolver = SessionSkillProfileResolver(
            configuration=configuration,
            catalogue_snapshot=snapshot,
        )
        return SkillDiscoveryAndLoader(
            skills=snapshot.skills,
            profile_manager=SessionSkillProfileManager(resolver=resolver),
        )


if __name__ == '__main__':
    unittest.main()
