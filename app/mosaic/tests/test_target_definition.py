import unittest

from pydantic import ValidationError

from mosaic.models.capabilities.target_definition import TargetDefinition


class TestTargetDefinition(unittest.TestCase):
    def test_vertical_qualified_target_is_accepted(self) -> None:
        target = TargetDefinition(
            id='openshift/cluster1',
            display_name='UK development OpenShift',
            aliases=('cluster1', 'uk-dev'),
        )

        self.assertEqual(target.vertical, 'openshift')
        self.assertEqual(target.aliases, ('cluster1', 'uk-dev'))

    def test_unqualified_target_identity_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            TargetDefinition(
                id='cluster1',
                display_name='UK development OpenShift',
                aliases=('cluster1',),
            )

    def test_case_insensitive_duplicate_aliases_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            'case-insensitively unique',
        ):
            TargetDefinition(
                id='openshift/cluster1',
                display_name='UK development OpenShift',
                aliases=('cluster1', 'CLUSTER1'),
            )


if __name__ == '__main__':
    unittest.main()
