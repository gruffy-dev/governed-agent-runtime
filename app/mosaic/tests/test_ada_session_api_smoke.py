import asyncio
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from mosaic.backend import Backend
from mosaic.models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration
from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from mosaic.models.identity.trusted_request_configuration import TrustedRequestConfiguration
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


@unittest.skipUnless(
    os.getenv('MOSAIC_RUN_ADA_SMOKE_TESTS') == '1',
    'Live ADA verification requires explicit opt-in and the target SDK environment.',
)
class TestAdaSessionApiSmoke(unittest.IsolatedAsyncioTestCase):
    async def test_private_session_list_through_backend_transport(self) -> None:
        configuration = AdaApplicationAdapterConfiguration()
        identity_configuration = TrustedRequestConfiguration()
        user_id = f'adapter-smoke-{uuid4()}'
        path = f'/apps/{identity_configuration.app_name}/users/{user_id}/sessions'

        with TemporaryDirectory() as temporary_directory:
            application = Backend.create_application(
                database_configuration=MosaicDatabaseConfiguration(
                    database_path=Path(temporary_directory) / 'mosaic.db',
                ),
                pilot_administration_configuration=PilotAdministrationConfiguration(
                    enabled=False,
                ),
                trusted_request_configuration=identity_configuration,
                ada_adapter_configuration=configuration,
            )
            async with application.router.lifespan_context(application):
                result = await asyncio.wait_for(
                    application.state.ada_transport.request_json('GET', path),
                    timeout=configuration.lifespan_timeout_seconds,
                )
                self.assertTrue(
                    isinstance(result, list),
                    'Private ADA session listing must return a JSON array.',
                )
                self.assertEqual(
                    len(result), 0,
                    'A fresh synthetic user must not receive existing conversations.',
                )
