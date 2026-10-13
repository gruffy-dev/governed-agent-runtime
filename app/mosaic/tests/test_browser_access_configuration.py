import os
import unittest
from unittest.mock import patch

from mosaic.models.identity.browser_access_configuration import BrowserAccessConfiguration


class TestBrowserAccessConfiguration(unittest.TestCase):
    def test_default_denies_browser_origins_and_environment_is_explicit(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(BrowserAccessConfiguration().allowed_origins, ())
        with patch.dict(
            os.environ,
            {
                'MOSAIC_BROWSER_ALLOWED_ORIGINS': '["http://127.0.0.1:8050","https://pilot.example.com"]'
            },
        ):
            self.assertEqual(
                BrowserAccessConfiguration().allowed_origins,
                ('http://127.0.0.1:8050', 'https://pilot.example.com'),
            )

    def test_canonical_local_and_https_origins_are_accepted(self) -> None:
        for origin in (
            'http://localhost:8050',
            'http://[::1]:8050',
            'https://pilot.example.com:8443',
        ):
            self.assertEqual(
                BrowserAccessConfiguration(allowed_origins=(origin,)).allowed_origins,
                (origin,),
            )

    def test_unsafe_or_non_canonical_origins_are_rejected(self) -> None:
        for origin in (
            '*',
            'null',
            'https://*.example.com',
            'http://pilot.example.com',
            'https://pilot.example.com/',
            'https://pilot.example.com/path',
            'https://pilot.example.com?query=1',
            'https://pilot.example.com#fragment',
            'https://user:password@pilot.example.com',
            ' https://pilot.example.com',
            'https://PILOT.example.com',
            'file:///tmp/example',
        ):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                BrowserAccessConfiguration(allowed_origins=(origin,))
        with self.assertRaises(ValueError):
            BrowserAccessConfiguration(
                allowed_origins=(
                    'https://pilot.example.com',
                    'https://pilot.example.com',
                )
            )
