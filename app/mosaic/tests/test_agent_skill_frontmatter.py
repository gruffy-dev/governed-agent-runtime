"""Tests for standard Agent Skills frontmatter."""

import unittest

from pydantic import ValidationError

from mosaic.models.skills.agent_skill_frontmatter import AgentSkillFrontmatter


class TestAgentSkillFrontmatter(unittest.TestCase):
    """Verify the supported Agent Skills frontmatter contract."""

    def test_standard_frontmatter_fields_are_accepted(self) -> None:
        """Standard required and optional fields validate together."""
        frontmatter = AgentSkillFrontmatter.model_validate(
            {
                'name': 'investigate-openshift',
                'description': (
                    'Investigate OpenShift when platform failures occur.'
                ),
                'license': 'Proprietary',
                'compatibility': 'Designed for MOSAIC.',
                'metadata': {'owner': 'platform-operations'},
                'allowed-tools': 'Read',
            }
        )

        self.assertEqual(frontmatter.name, 'investigate-openshift')
        self.assertEqual(frontmatter.allowed_tools, 'Read')

    def test_consecutive_hyphens_are_rejected(self) -> None:
        """A standard skill name cannot contain consecutive hyphens."""
        with self.assertRaises(ValidationError):
            AgentSkillFrontmatter(
                name='investigate--openshift',
                description='Investigate OpenShift failures.',
            )

    def test_unknown_frontmatter_field_is_rejected(self) -> None:
        """Unsupported frontmatter fields cannot bypass validation."""
        with self.assertRaises(ValidationError):
            AgentSkillFrontmatter.model_validate(
                {
                    'name': 'investigate-openshift',
                    'description': 'Investigate OpenShift failures.',
                    'provider': 'kubernetes-mcp',
                }
            )


if __name__ == '__main__':
    unittest.main()
