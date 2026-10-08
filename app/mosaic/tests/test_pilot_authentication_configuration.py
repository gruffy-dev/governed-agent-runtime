import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration


class TestPilotAuthenticationConfiguration(unittest.TestCase):
    def test_defaults_use_seven_day_secure_production_cookie(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            configuration = PilotAuthenticationConfiguration()

        self.assertEqual(configuration.mode, 'production')
        self.assertEqual(
            configuration.cookie_name,
            'mosaic_pilot_session',
        )
        self.assertEqual(configuration.cookie_lifetime_seconds, 604800)
        self.assertTrue(configuration.secure_cookie)

    def test_explicit_local_mode_allows_insecure_cookie(self) -> None:
        configuration = PilotAuthenticationConfiguration(
            mode='local',
            secure_cookie=False,
        )

        self.assertFalse(configuration.secure_cookie)

    def test_production_mode_rejects_insecure_cookie(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            'requires a secure cookie',
        ):
            PilotAuthenticationConfiguration(
                mode='production',
                secure_cookie=False,
            )
