from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from .authentication_failure_handler import AuthenticationFailureHandler
from .pilot_bearer_authenticator import PilotBearerAuthenticator
from ...models.identity.trusted_user_context import TrustedUserContext


class PilotAuthenticationMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        authenticator: PilotBearerAuthenticator,
        cookie_name: str,
    ) -> None:
        """
        Protect the application with pilot bearer and cookie authentication.

        :param app: Inner ADA and MOSAIC ASGI application.
        :param authenticator: Pilot credential validation boundary.
        :param cookie_name: Name of the protected browser credential cookie.
        """
        self._app = app
        self._authenticator = authenticator
        self._cookie_name = cookie_name
        self._failure_handler = AuthenticationFailureHandler()

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

        trusted_user_context = self._authenticate(scope)
        if trusted_user_context is None:
            await self._reject(scope, receive, send)
            return

        scope.setdefault('state', {})[
            'trusted_user_context'
        ] = trusted_user_context
        await self._app(scope, receive, send)

    def _authenticate(self, scope: Scope) -> TrustedUserContext | None:
        """
        Validate exactly one bearer-header or browser-cookie credential.

        :param scope: ASGI request scope containing headers and cookies.

        :return: Immutable trusted context, or ``None`` when unauthorised.
        """
        authorisation_values = Headers(scope=scope).getlist(
            'authorization'
        )
        cookie_token = HTTPConnection(scope).cookies.get(self._cookie_name)
        if authorisation_values and cookie_token is not None:
            return None
        if authorisation_values:
            plaintext_token = self._parse_bearer(authorisation_values)
        else:
            plaintext_token = cookie_token
        if (
            plaintext_token is None
            or not plaintext_token
            or plaintext_token != plaintext_token.strip()
            or any(character.isspace() for character in plaintext_token)
        ):
            return None
        return self._authenticator.authenticate(plaintext_token)

    @staticmethod
    def _parse_bearer(
        authorisation_values: list[str],
    ) -> str | None:
        """
        Parse exactly one strict Authorization bearer value.

        :param authorisation_values: Authorization header values from ASGI.

        :return: Opaque bearer token, or ``None`` when malformed.
        """
        if len(authorisation_values) != 1:
            return None
        scheme, separator, plaintext_token = authorisation_values[0].partition(
            ' '
        )
        if separator != ' ' or scheme.casefold() != 'bearer':
            return None
        return plaintext_token

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
        if path in {
            '/api/v1/auth/token',
            '/api/v1/auth/logout',
        } and method == 'POST':
            return True
        return path == '/api/v1/admin' or path.startswith(
            '/api/v1/admin/'
        )

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        """
        Log and return the same correlated unauthorised HTTP failure.

        :param scope: Unauthorised HTTP or WebSocket connection scope.
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
        response = self._failure_handler.create_response(401)
        await response(scope, receive, send)
