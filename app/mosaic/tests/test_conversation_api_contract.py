import unittest
from typing import Any

from fastapi.openapi.models import OpenAPI

from mosaic.components.api.conversation_api_contract import ConversationApiContract
from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration


class TestConversationApiContract(unittest.TestCase):
    def test_contract_is_valid_openapi_with_only_owned_public_schemas(self) -> None:
        contract = self._build_contract()
        OpenAPI.model_validate(contract)
        self.assertEqual(contract['openapi'], '3.1.0')
        self.assertEqual(contract['info']['version'], '1.0.0')
        self.assertEqual(len(contract['paths']), 3)
        self.assertEqual(sum(len(path) for path in contract['paths'].values()), 4)
        self.assertTrue(
            all(path.startswith('/api/v1/conversations') for path in contract['paths'])
        )
        self.assertNotIn('RunAgentRequest', contract['components']['schemas'])
        self._check_references(contract, contract)

    def test_every_operation_declares_identity_security_and_errors(self) -> None:
        contract = self._build_contract()
        for path, operations in contract['paths'].items():
            for operation in operations.values():
                with self.subTest(path=path, operation=operation['operationId']):
                    self.assertEqual(
                        operation['security'], [{'BearerAuth': []}, {'PilotCookie': []}]
                    )
                    self.assertEqual(
                        operation['x-mosaic-identity-source'], 'trusted_request_context'
                    )
                    self.assertEqual(operation['x-mosaic-implementation'], 'planned')
                    self.assertTrue(
                        {'400', '401', '403', '500'} <= operation['responses'].keys()
                    )
                    self.assertIn(
                        'WWW-Authenticate', operation['responses']['401']['headers']
                    )
                    self.assertNotIn(
                        'WWW-Authenticate', operation['responses']['403']['headers']
                    )
                    if '{conversation_id}' in path:
                        self.assertIn('404', operation['responses'])
                        self.assertEqual(
                            operation['parameters'][0]['schema']['format'], 'uuid'
                        )
        self.assertEqual(
            contract['components']['securitySchemes']['PilotCookie']['name'],
            'configured-pilot-cookie',
        )
        self.assertEqual(len(contract['x-mosaic-authentication-examples']), 2)

    def test_streaming_contract_documents_native_adk_and_disconnect(
        self,
    ) -> None:
        operation = self._build_contract()['paths'][
            '/api/v1/conversations/{conversation_id}/messages'
        ]['post']
        stream = operation['responses']['200']
        self.assertIn('text/event-stream', stream['content'])
        self.assertEqual(
            stream['content']['text/event-stream']['schema'], {'type': 'string'}
        )
        self.assertEqual(
            stream['headers']['X-Accel-Buffering']['schema']['const'], 'no'
        )
        self.assertEqual(operation['x-mosaic-sse']['format'], 'ADK')
        self.assertTrue(operation['x-mosaic-sse']['framing'].endswith('\n\n'))
        self.assertIn('409', operation['responses'])
        self.assertIn('can_continue', operation['x-mosaic-sse']['availability'])
        self.assertNotIn('terminal_events', operation['x-mosaic-sse'])
        self.assertIn('Stop private execution', operation['x-mosaic-sse']['disconnect'])
        self.assertNotIn('x-mosaic-event-schema', stream['content']['text/event-stream'])
        self.assertNotIn('InvocationStreamEvent', self._build_contract()['components']['schemas'])

    def _check_references(self, value: Any, contract: dict[str, Any]) -> None:
        if isinstance(value, dict):
            if '$ref' in value:
                resolved: Any = contract
                for part in value['$ref'].removeprefix('#/').split('/'):
                    resolved = resolved[part]
                self.assertIsInstance(resolved, dict)
            for child in value.values():
                self._check_references(child, contract)
        elif isinstance(value, list):
            for child in value:
                self._check_references(child, contract)

    @staticmethod
    def _build_contract() -> dict[str, Any]:
        return ConversationApiContract(
            PilotAuthenticationConfiguration(cookie_name='configured-pilot-cookie')
        ).build()
