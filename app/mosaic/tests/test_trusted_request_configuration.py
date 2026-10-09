import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from mosaic.models.identity.trusted_request_configuration import TrustedRequestConfiguration


class TestTrustedRequestConfiguration(unittest.TestCase):
    def test_default_matches_mosaic_application(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            configuration = TrustedRequestConfiguration()

        self.assertEqual(configuration.app_name, 'mosaic')

    def test_application_name_uses_server_environment(self) -> None:
        with patch.dict(
            os.environ,
            {'MOSAIC_APP_NAME': 'configured-application'},
            clear=True,
        ):
            configuration = TrustedRequestConfiguration()

        self.assertEqual(configuration.app_name, 'configured-application')

    def test_invalid_application_names_are_rejected(self) -> None:
        for app_name in ('', ' ', '../other-application', 'name/with/path'):
            with (
                self.subTest(app_name=app_name),
                self.assertRaises(ValidationError),
            ):
                TrustedRequestConfiguration(app_name=app_name)
