"""Tests for trusted session skill-profile environment configuration."""

import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from mosaic.models.skills.session_skill_profile_configuration import (
    SessionSkillProfileConfiguration,
)


class TestSessionSkillProfileConfiguration(unittest.TestCase):
    """Verify profile parsing and trusted assignment validation."""

    def test_environment_configuration_is_parsed(self) -> None:
        """JSON environment values produce immutable profile mappings."""
        environment = {
            'MOSAIC_SKILLS_PROFILES': (
                '{"platform-demo":["investigate-openshift-ingress"],'
                '"database-demo":["match-database-runbook"]}'
            ),
            'MOSAIC_SKILLS_DEFAULT_PROFILE_ID': 'platform-demo',
            'MOSAIC_SKILLS_SESSION_PROFILE_ASSIGNMENTS': (
                '{"database-session":"database-demo"}'
            ),
            'MOSAIC_SKILLS_MAXIMUM_ENABLED_SKILL_COUNT': '25',
            'MOSAIC_SKILLS_MAXIMUM_DISCOVERY_METADATA_CHARACTERS': '12000',
            'MOSAIC_SKILLS_MAXIMUM_LOADED_SKILL_COUNT': '7',
            'MOSAIC_SKILLS_MAXIMUM_LOADED_SKILL_CHARACTERS': '30000',
        }

        with patch.dict(os.environ, environment, clear=True):
            configuration = SessionSkillProfileConfiguration()

        self.assertEqual(configuration.default_profile_id, 'platform-demo')
        self.assertEqual(
            configuration.profiles['database-demo'],
            ('match-database-runbook',),
        )
        self.assertEqual(
            configuration.session_profile_assignments['database-session'],
            'database-demo',
        )
        self.assertEqual(configuration.maximum_enabled_skill_count, 25)
        self.assertEqual(
            configuration.maximum_discovery_metadata_characters,
            12000,
        )
        self.assertEqual(configuration.maximum_loaded_skill_count, 7)
        self.assertEqual(configuration.maximum_loaded_skill_characters, 30000)

    def test_undefined_assignment_profile_is_rejected(self) -> None:
        """Every session assignment must reference a defined profile."""
        with self.assertRaises(ValidationError):
            SessionSkillProfileConfiguration(
                profiles={'platform-demo': ()},
                default_profile_id='platform-demo',
                session_profile_assignments={
                    'database-session': 'database-demo'
                },
            )

    def test_missing_profile_environment_is_rejected(self) -> None:
        """Startup fails closed when no trusted profiles are configured."""
        with (
            patch.dict(os.environ, {}, clear=True),
            self.assertRaises(ValidationError),
        ):
            SessionSkillProfileConfiguration()


if __name__ == '__main__':
    unittest.main()
