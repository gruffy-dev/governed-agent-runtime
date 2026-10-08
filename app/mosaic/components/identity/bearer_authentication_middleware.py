from fastapi.responses import JSONResponse
from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send

from .pilot_bearer_authenticator import PilotBearerAuthenticator
from ...models.identity.trusted_user_context import TrustedUserContext


class BearerAuthenticationMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        authenticator: PilotBearerAuthenticator,
    ) -> None:
        """
        Protect the complete application with pilot bearer authentication.

        :param app: Inner ADA and MOSAIC ASGI application.
        :param authenticator: Pilot credential validation boundary.
        """
        self._app = app
        self._authenticator = authenticator

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        Authenticate HTTP and WebSocket requests before inner middleware.

        :param scope: ASGI connection scope.
        :param receive: ASGI inbound-message receiver.
        :param send: ASGI outbound-message sender.
        """
        if scope['type'] not in {'http', 'websocket'}:
            await self._app(scope, receive, send)
            return
        if self._is_unauthenticated_path(scope):
            await self._app(scope, receive, send)
            return

        authorization_values = Headers(scope=scope).getlist(
            'authorization'
        )
        trusted_user_context = self._authenticate(authorization_values)
        if trusted_user_context is None:
            await self._reject(scope, receive, send)
            return

        scope.setdefault('state', {})[
            'trusted_user_context'
        ] = trusted_user_context
        await self._app(scope, receive, send)

    def _authenticate(
        self,
        authorization_values: list[str],
    ) -> TrustedUserContext | None:
        """
        Parse exactly one strict bearer header and validate its credential.

        :param authorization_values: Authorization header values from ASGI.

        :return: Immutable trusted context, or ``None`` when unauthorized.
        """
        if len(authorization_values) != 1:
            return None
        scheme, separator, plaintext_token = authorization_values[0].partition(
            ' '
        )
        if (
            separator != ' '
            or scheme.casefold() != 'bearer'
            or not plaintext_token
            or plaintext_token != plaintext_token.strip()
            or any(character.isspace() for character in plaintext_token)
        ):
            return None
        return self._authenticator.authenticate(plaintext_token)

    @staticmethod
    def _is_unauthenticated_path(scope: Scope) -> bool:
        """
        Identify fixed bootstrap and internal paths using separate controls.

        :param scope: ASGI request scope containing the path and method.

        :return: Whether pilot user authentication must be bypassed.
        """
        path = scope.get('path', '')
        method = scope.get('method', '')
        if path in {'/health', '/ready'}:
            return True
        if path == '/api/v1/auth/token' and method == 'POST':
            return True
        return path == '/api/v1/admin' or path.startswith(
            '/api/v1/admin/'
        )

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        Return the same generic unauthorized outcome for every failure.

        :param scope: Unauthorized HTTP or WebSocket connection scope.
        :param receive: ASGI inbound-message receiver.
        :param send: ASGI outbound-message sender.
        """
        if scope['type'] == 'websocket':
            await send(
                {
                    'type': 'websocket.close',
                    'code': 4401,
                    'reason': 'Unauthorized',
                }
            )
            return
        response = JSONResponse(
            status_code=401,
            content={'detail': 'Unauthorized'},
            headers={
                'Cache-Control': 'no-store',
                'WWW-Authenticate': 'Bearer',
            },
        )
        await response(scope, receive, send)
