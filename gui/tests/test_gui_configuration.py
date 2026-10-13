import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from mosaic_gui.gui_configuration import GuiConfiguration


class TestGuiConfiguration(unittest.TestCase):
    def test_default_is_local_and_independent(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            configuration = GuiConfiguration()
        self.assertEqual(configuration.backend_url, 'http://127.0.0.1:8000')
        self.assertEqual(configuration.host, '127.0.0.1')
        self.assertEqual(configuration.port, 8050)
        self.assertIsNone(configuration.organisation_logo_path)

    def test_environment_and_https_are_supported(self) -> None:
        with patch.dict(
            os.environ,
            {
                'MOSAIC_GUI_BACKEND_URL': 'https://api.example.com',
                'MOSAIC_GUI_PORT': '8051',
                'MOSAIC_GUI_ORGANISATION_LOGO_WIDTH': '120',
                'MOSAIC_GUI_ORGANISATION_LOGO_HEIGHT': '35',
            },
        ):
            configuration = GuiConfiguration()
        self.assertEqual(configuration.backend_url, 'https://api.example.com')
        self.assertEqual(
            (
                configuration.port,
                configuration.organisation_logo_width,
                configuration.organisation_logo_height,
            ),
            (8051, 120, 35),
        )

    def test_credentials_paths_nonlocal_http_and_invalid_dimensions_are_rejected(
        self,
    ) -> None:
        for origin in (
            'https://user:password@api.example.com',
            'https://api.example.com/path',
            'https://api.example.com/',
            'http://api.example.com',
            'https://api.example.com?query=value',
            'https://api.example.com#fragment',
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                GuiConfiguration(backend_url=origin)
        for dimensions in (
            {'organisation_logo_width': 0},
            {'organisation_logo_height': 999},
            {'port': 0},
        ):
            with self.assertRaises(ValueError):
                GuiConfiguration(**dimensions)

    def test_private_logo_requires_a_png_signature(self) -> None:
        with TemporaryDirectory() as directory:
            logo = Path(directory) / 'synthetic-logo.png'
            logo.write_bytes(b'not a PNG')
            with self.assertRaises(ValueError):
                GuiConfiguration(organisation_logo_path=logo)
            logo.write_bytes(b'\x89PNG\r\n\x1a\nsynthetic-data')
            self.assertEqual(
                GuiConfiguration(organisation_logo_path=logo).organisation_logo_path,
                logo,
            )
