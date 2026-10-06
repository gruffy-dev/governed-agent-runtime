import unittest
from unittest.mock import patch

from pydantic import ValidationError

from mosaic.models.backend_configuration import BackendConfiguration


class TestBackendConfiguration(unittest.TestCase):
    def test_local_defaults_are_applied(self) -> None:
        with patch.dict('os.environ', {}, clear=True):
            configuration = BackendConfiguration()

        self.assertEqual(configuration.host, '127.0.0.1')
        self.assertEqual(configuration.port, 8000)

    def test_environment_values_are_applied(self) -> None:
        with patch.dict(
            'os.environ',
            {
                'MOSAIC_BACKEND_HOST': '0.0.0.0',
                'PORT': '9090',
            },
            clear=True,
        ):
            configuration = BackendConfiguration()

        self.assertEqual(configuration.host, '0.0.0.0')
        self.assertEqual(configuration.port, 9090)

    def test_invalid_host_is_rejected(self) -> None:
        with (
            patch.dict(
                'os.environ',
                {'MOSAIC_BACKEND_HOST': 'invalid host'},
                clear=True,
            ),
            self.assertRaises(ValidationError),
        ):
            BackendConfiguration()

    def test_invalid_port_is_rejected(self) -> None:
        with (
            patch.dict('os.environ', {'PORT': '70000'}, clear=True),
            self.assertRaises(ValidationError),
        ):
            BackendConfiguration()
