import unittest
from collections.abc import Awaitable, Callable
from unittest.mock import Mock

from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mosaic.components.identity.bearer_authentication_middleware import BearerAuthenticationMiddleware
from mosaic.models.identity.trusted_user_context import TrustedUserContext


class TestBearerAuthenticationMiddleware(unittest.TestCase):
    def test_valid_token_sets_trusted_context_before_inner_middleware(
        self,
    ) -> None:
        application = FastAPI()
        observed_user_ids: list[str] = []

        @application.middleware('http')
        async def observe_trusted_context(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            observed_user_ids.append(
                request.state.trusted_user_context.user_id
            )
            return await call_next(request)

        @application.post('/users/{claimed_user_id}')
        async def inspect_identity(
            claimed_user_id: str,
            request: Request,
        ) -> dict[str, str]:
            request_body = await request.json()
            return {
                'trusted_user_id': (
                    request.state.trusted_user_context.user_id
                ),
                'claimed_path_user_id': claimed_user_id,
                'claimed_body_user_id': request_body['user_id'],
                'claimed_header_user_id': request.headers['X-User-ID'],
            }

        authenticator = Mock()
        authenticator.authenticate.return_value = TrustedUserContext(
            user_id='authenticated-user'
        )
        application.add_middleware(
            BearerAuthenticationMiddleware,
            authenticator=authenticator,
        )

        with TestClient(application) as client:
            response = client.post(
                '/users/spoofed-path-user',
                headers={
                    'Authorization': 'Bearer valid-token',
                    'X-User-ID': 'spoofed-header-user',
                },
                json={'user_id': 'spoofed-body-user'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                'trusted_user_id': 'authenticated-user',
                'claimed_path_user_id': 'spoofed-path-user',
                'claimed_body_user_id': 'spoofed-body-user',
                'claimed_header_user_id': 'spoofed-header-user',
            },
        )
        self.assertEqual(observed_user_ids, ['authenticated-user'])
        authenticator.authenticate.assert_called_once_with('valid-token')

    def test_all_invalid_credentials_return_same_generic_response(
        self,
    ) -> None:
        application = FastAPI()

        @application.get('/protected')
        async def protected() -> dict[str, str]:
            return {'status': 'unexpected'}

        authenticator = Mock()
        authenticator.authenticate.return_value = None
        application.add_middleware(
            BearerAuthenticationMiddleware,
            authenticator=authenticator,
        )

        with TestClient(application) as client:
            responses = (
                client.get('/protected'),
                client.get(
                    '/protected',
                    headers={'Authorization': 'Basic invalid'},
                ),
                client.get(
                    '/protected',
                    headers={'Authorization': 'Bearer'},
                ),
                client.get(
                    '/protected',
                    headers={'Authorization': 'Bearer unknown-token'},
                ),
            )

        for response in responses:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {'detail': 'Unauthorized'})
            self.assertEqual(
                response.headers['WWW-Authenticate'],
                'Bearer',
            )
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
        authenticator.authenticate.assert_called_once_with('unknown-token')

    def test_fixed_bootstrap_paths_bypass_user_authentication(self) -> None:
        application = FastAPI()

        @application.get('/health')
        async def health() -> dict[str, str]:
            return {'status': 'ok'}

        @application.get('/ready')
        async def ready() -> dict[str, str]:
            return {'status': 'ready'}

        @application.post('/api/v1/auth/token')
        async def sign_in() -> dict[str, str]:
            return {'status': 'available'}

        @application.get('/api/v1/admin/users')
        async def administration() -> dict[str, str]:
            return {'status': 'separately-protected'}

        authenticator = Mock()
        application.add_middleware(
            BearerAuthenticationMiddleware,
            authenticator=authenticator,
        )

        with TestClient(application) as client:
            responses = (
                client.get('/health'),
                client.get('/ready'),
                client.post('/api/v1/auth/token'),
                client.get('/api/v1/admin/users'),
            )

        self.assertTrue(
            all(response.status_code == 200 for response in responses)
        )
        authenticator.authenticate.assert_not_called()

    def test_websocket_rejects_missing_bearer_token(self) -> None:
        application = FastAPI()

        @application.websocket('/run_live')
        async def run_live(websocket: WebSocket) -> None:
            await websocket.accept()

        application.add_middleware(
            BearerAuthenticationMiddleware,
            authenticator=Mock(),
        )

        with (
            TestClient(application) as client,
            self.assertRaises(WebSocketDisconnect) as raised,
            client.websocket_connect('/run_live'),
        ):
            pass

        self.assertEqual(raised.exception.code, 4401)
