import unittest
from unittest.mock import patch

from pydantic import SecretStr, ValidationError

from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration


class TestPilotAdministrationConfiguration(unittest.TestCase):
    def test_routes_are_disabled_by_default(self) -> None:
        with patch.dict('os.environ', {}, clear=True):
            configuration = PilotAdministrationConfiguration()

        self.assertFalse(configuration.enabled)
        self.assertIsNone(configuration.administrator_secret)

    def test_enabled_routes_read_secret_from_environment(self) -> None:
        with patch.dict(
            'os.environ',
            {
                'MOSAIC_PILOT_ADMIN_ENABLED': 'true',
                'MOSAIC_PILOT_ADMIN_SECRET': 'a' * 32,
            },
            clear=True,
        ):
            configuration = PilotAdministrationConfiguration()

        self.assertTrue(configuration.enabled)
        self.assertEqual(
            configuration.administrator_secret,
            SecretStr('a' * 32),
        )

    def test_enabled_routes_require_secret(self) -> None:
        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_PILOT_ADMIN_ENABLED': 'true'},
                clear=True,
            ),
            self.assertRaises(ValidationError),
        ):
            PilotAdministrationConfiguration()

    def test_invalid_enabled_value_is_rejected(self) -> None:
        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_PILOT_ADMIN_ENABLED': 'sometimes'},
                clear=True,
            ),
            self.assertRaises(ValidationError),
        ):
            PilotAdministrationConfiguration()
