from starlette.datastructures import Headers
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Receive, Scope, Send

from .authentication_failure_handler import AuthenticationFailureHandler
from ...models.identity.browser_access_configuration import BrowserAccessConfiguration


class BrowserOriginMiddleware:
    def __init__(
        self, app: ASGIApp, configuration: BrowserAccessConfiguration, cookie_name: str
    ) -> None:
        """
        Enforce trusted browser origins separately from credential authentication.

        :param app: Inner public MOSAIC application.
        :param configuration: Explicit GUI-origin allowlist.
        :param cookie_name: Authentication cookie requiring protection on writes.
        """
        self._app = app
        self._configuration = configuration
        self._cookie_name = cookie_name
        self._failure_handler = AuthenticationFailureHandler()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """
        Reject unapproved origins and cookie-authenticated writes without Origin.

        Cover sign-in and sign-out as well as user and administration APIs. Headers
        do not authenticate callers: approved origins still require valid credentials.
        Originless bearer and administrator CLI requests remain supported.

        :param scope: Public ASGI request scope.
        :param receive: Inbound ASGI message receiver.
        :param send: Outbound ASGI message sender.
        """
        path = scope.get('path', '')
        if scope['type'] != 'http' or not (
            path == '/api/v1' or path.startswith('/api/v1/')
        ):
            await self._app(scope, receive, send)
            return
        origins = Headers(scope=scope).getlist('origin')
        has_cookie = self._cookie_name in HTTPConnection(scope).cookies
        unsafe_method = scope['method'] not in {'GET', 'HEAD', 'OPTIONS'}
        if (
            origins
            and (
                len(origins) != 1
                or origins[0] not in self._configuration.allowed_origins
            )
        ) or (not origins and has_cookie and unsafe_method):
            response = self._failure_handler.create_response(403)
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)
