"""Tests for the immutable runtime skill contract."""

import unittest

from pydantic import ValidationError

from mosaic.models.skills.skill import Skill


class TestSkill(unittest.TestCase):
    """Verify procedural and output skill invariants."""

    def test_procedural_skill_accepts_semantic_capabilities(self) -> None:
        """A procedural skill can declare governed semantic capabilities."""
        skill = Skill(
            name='investigate-platform',
            version='1.2.0',
            kind='procedural',
            description='Investigate a platform.',
            instruction='Collect approved evidence.',
            required_capability_names=('platform.status.read',),
            optional_capability_names=('platform.metrics.read',),
        )

        self.assertEqual(skill.version, '1.2.0')
        self.assertEqual(skill.kind, 'procedural')

    def test_output_skill_can_define_its_contract_in_instructions(self) -> None:
        """The standard ``SKILL.md`` body can fully define an output skill."""
        skill = Skill(
            name='format-result',
            version='1.0.0',
            kind='output',
            description='Format a result.',
            instruction='Produce the requested machine-readable format.',
        )

        self.assertEqual(skill.kind, 'output')

    def test_output_skill_cannot_declare_capabilities(self) -> None:
        """Output selection cannot expand external-system access."""
        with self.assertRaises(ValidationError):
            Skill(
                name='format-result',
                version='1.0.0',
                kind='output',
                description='Format a result.',
                instruction='Produce the requested format.',
                output_form='Return Markdown.',
                required_capability_names=('platform.status.read',),
            )

    def test_malformed_capability_name_is_rejected(self) -> None:
        """Capability references must use the semantic dotted format."""
        with self.assertRaises(ValidationError):
            Skill(
                name='investigate-platform',
                version='1.0.0',
                kind='procedural',
                description='Investigate a platform.',
                instruction='Collect approved evidence.',
                required_capability_names=('concrete_tool',),
            )


if __name__ == '__main__':
    unittest.main()
