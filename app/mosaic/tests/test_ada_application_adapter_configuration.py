import unittest
from unittest.mock import patch

from pydantic import ValidationError

from mosaic.models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration


class TestAdaApplicationAdapterConfiguration(unittest.TestCase):
    def test_environment_overrides(self) -> None:
        with patch.dict(
            'os.environ',
            {
                'MOSAIC_ADA_LIFESPAN_TIMEOUT_SECONDS': '10',
                'MOSAIC_ADA_RESPONSE_QUEUE_CAPACITY': '2',
                'MOSAIC_ADA_MAXIMUM_RESPONSE_BYTES': '1024',
                'MOSAIC_ADA_ASGI_SPEC_VERSION': '2.4',
            },
        ):
            configuration = AdaApplicationAdapterConfiguration()
        self.assertEqual(configuration.lifespan_timeout_seconds, 10)
        self.assertEqual(configuration.response_queue_capacity, 2)
        self.assertEqual(configuration.maximum_response_bytes, 1024)
        self.assertEqual(configuration.asgi_spec_version, '2.4')

    def test_invalid_configuration_is_rejected(self) -> None:
        for values in (
            {'lifespan_timeout_seconds': 0},
            {'response_queue_capacity': 0},
            {'maximum_response_bytes': -1},
            {'asgi_spec_version': '2.5'},
            {'unrecognized': True},
        ):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                AdaApplicationAdapterConfiguration(**values)
