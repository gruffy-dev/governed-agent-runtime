import asyncio
import json
import os
import unittest
from contextlib import aclosing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote
from uuid import uuid4

from mosaic.backend import Backend
from mosaic.models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration
from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from mosaic.models.identity.trusted_request_configuration import TrustedRequestConfiguration
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration
from mosaic.utilities.environment_configuration_reader import EnvironmentConfigurationReader


@unittest.skipUnless(
    os.getenv('MOSAIC_RUN_ADA_STREAMING_SMOKE_TESTS') == '1',
    'Live streaming verification requires explicit opt-in and a configured model.',
)
class TestAdaStreamingApiSmoke(unittest.IsolatedAsyncioTestCase):
    async def test_private_stream_and_saved_response(self) -> None:
        configuration = AdaApplicationAdapterConfiguration()
        identity_configuration = TrustedRequestConfiguration()
        timeout_seconds = EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_ADA_STREAMING_SMOKE_TIMEOUT_SECONDS', 120,
        )
        user_id = f'adapter-stream-smoke-{uuid4()}'
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
                transport = application.state.ada_transport
                created = await asyncio.wait_for(
                    transport.request_json('POST', path, {}),
                    timeout=configuration.lifespan_timeout_seconds,
                )
                self.assertTrue(isinstance(created, dict), 'Session creation must return an object.')
                session_id = created.get('id')
                self.assertTrue(
                    isinstance(session_id, str) and bool(session_id),
                    'Session creation must return a nonempty ID.',
                )
                # This invokes the real agent/model. The synthetic conversation
                # remains in ADA storage; no production payload is printed.
                payload = {
                    'app_name': identity_configuration.app_name,
                    'user_id': user_id,
                    'session_id': session_id,
                    'new_message': {
                        'role': 'user',
                        'parts': [{'text': 'Hello. Please reply with a short greeting; do not use tools.'}],
                    },
                    'streaming': True,
                }
                body = bytearray()
                saw_stream_chunk = False
                saw_completion = False
                async with asyncio.timeout(timeout_seconds), aclosing(
                    transport.stream_response('POST', '/run_sse', payload)
                ) as stream:
                    async for message in stream:
                        if message['type'] == 'http.response.start':
                            self.assertEqual(message['status'], 200)
                            headers = dict(message.get('headers', []))
                            self.assertTrue(
                                headers.get(b'content-type', b'').startswith(b'text/event-stream'),
                                'Private execution must return an SSE response.',
                            )
                        else:
                            chunk = message.get('body', b'')
                            body.extend(chunk)
                            self.assertLessEqual(
                                len(body), configuration.maximum_response_bytes,
                                'Smoke-test response exceeded its bounded capture limit.',
                            )
                            if message.get('more_body', False):
                                saw_stream_chunk = saw_stream_chunk or bool(chunk)
                            else:
                                saw_completion = True
                self.assertTrue(saw_stream_chunk, 'Expected data before the final ASGI body message.')
                self.assertTrue(saw_completion, 'Private SSE response must terminate normally.')
                saw_final_text = False
                for line in body.decode('utf-8').splitlines():
                    if not line.startswith('data:'):
                        continue
                    event = json.loads(line[5:].strip())
                    self.assertTrue(isinstance(event, dict), 'SSE data must contain a JSON event.')
                    self.assertFalse(
                        bool(event.get('error') or event.get('error_code') or event.get('errorCode')),
                        'Private execution returned an error event; inspect locally without sharing sensitive payloads.',
                    )
                    saw_final_text = saw_final_text or self._has_final_text(event)
                self.assertTrue(saw_final_text, 'Expected a complete model text response, not just partial events.')

                retrieved = await asyncio.wait_for(
                    transport.request_json('GET', f'{path}/{quote(session_id, safe="")}'),
                    timeout=configuration.lifespan_timeout_seconds,
                )
                self.assertTrue(isinstance(retrieved, dict), 'Session retrieval must return an object.')
                events = retrieved.get('events', [])
                self.assertTrue(isinstance(events, list), 'Session events must be an array.')
                self.assertTrue(
                    any(isinstance(event, dict) and self._has_final_text(event) for event in events),
                    'The completed model response must be retained in the ADA session.',
                )

    @staticmethod
    def _has_final_text(event: dict[str, object]) -> bool:
        content = event.get('content')
        if not isinstance(content, dict) or content.get('role') != 'model' or event.get('partial'):
            return False
        parts = content.get('parts', [])
        if not isinstance(parts, list):
            return False
        if any(
            isinstance(part, dict)
            and any(part.get(key) for key in ('function_call', 'functionCall', 'function_response', 'functionResponse'))
            for part in parts
        ):
            return False
        return any(
            isinstance(part, dict)
            and isinstance(part.get('text'), str)
            and bool(part['text'].strip())
            and not part.get('thought')
            for part in parts
        )
