"""Tests for the MOSAIC Agent Skills governance extension."""

import unittest

from pydantic import ValidationError

from mosaic.models.skills.mosaic_skill_metadata import MosaicSkillMetadata


class TestMosaicSkillMetadata(unittest.TestCase):
    """Verify governed capability and output metadata."""

    def test_procedural_metadata_accepts_safe_references(self) -> None:
        """A procedural skill can declare semantic capabilities and files."""
        metadata = MosaicSkillMetadata(
            version='1.0.0',
            kind='procedural',
            output_form_file='references/output-form.md',
            required_capability_names=('openshift.status.read',),
        )

        self.assertEqual(metadata.schema_version, 1)
        self.assertEqual(metadata.version, '1.0.0')

    def test_output_metadata_can_rely_on_skill_instructions(self) -> None:
        """An output skill may define its format entirely in ``SKILL.md``."""
        metadata = MosaicSkillMetadata(
            version='1.0.0',
            kind='output',
        )

        self.assertEqual(metadata.kind, 'output')

    def test_output_metadata_cannot_declare_capabilities(self) -> None:
        """An output skill cannot increase external-system access."""
        with self.assertRaises(ValidationError):
            MosaicSkillMetadata(
                version='1.0.0',
                kind='output',
                required_capability_names=('platform.status.read',),
            )

    def test_parent_traversal_is_rejected(self) -> None:
        """An extension file cannot escape its skill directory."""
        with self.assertRaises(ValidationError):
            MosaicSkillMetadata(
                version='1.0.0',
                kind='procedural',
                output_form_file='../output-form.md',
            )

    def test_non_semantic_version_is_rejected(self) -> None:
        """MOSAIC skill versions must follow Semantic Versioning."""
        with self.assertRaises(ValidationError):
            MosaicSkillMetadata(
                version='version-one',
                kind='procedural',
            )


if __name__ == '__main__':
    unittest.main()
