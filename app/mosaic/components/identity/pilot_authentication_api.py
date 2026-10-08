from typing import Any

from fastapi import APIRouter, HTTPException, Response

from .pilot_bearer_authenticator import PilotBearerAuthenticator
from ...models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration
from ...models.identity.pilot_token_sign_in_request import PilotTokenSignInRequest


class PilotAuthenticationApi:
    def __init__(
        self,
        configuration: PilotAuthenticationConfiguration,
        authenticator: PilotBearerAuthenticator,
    ) -> None:
        """
        Bind pilot browser authentication routes to token validation.

        :param configuration: Cookie security and lifetime configuration.
        :param authenticator: Pilot bearer-token validation boundary.
        """
        self._configuration = configuration
        self._authenticator = authenticator

    def register_routes(self, application: Any) -> None:
        """
        Register token exchange and logout beneath the public API prefix.

        :param application: FastAPI-compatible application receiving routes.
        """
        router = APIRouter(prefix='/api/v1/auth')
        router.add_api_route(
            '/token',
            self.sign_in,
            methods=['POST'],
            status_code=204,
        )
        router.add_api_route(
            '/logout',
            self.sign_out,
            methods=['POST'],
            status_code=204,
        )
        application.include_router(router)

    def sign_in(
        self,
        request: PilotTokenSignInRequest,
    ) -> Response:
        """
        Exchange one valid pilot token for a protected browser cookie.

        :param request: Opaque pilot token submitted by the browser.

        :return: Empty response setting the authentication cookie.

        :raises HTTPException: If the supplied token does not resolve.
        """
        plaintext_token = request.token.get_secret_value()
        if self._authenticator.authenticate(plaintext_token) is None:
            raise HTTPException(
                status_code=401,
                detail='Unauthorized',
                headers={
                    'Cache-Control': 'no-store',
                    'WWW-Authenticate': 'Bearer',
                },
            )

        response = Response(
            status_code=204,
            headers={'Cache-Control': 'no-store'},
        )
        response.set_cookie(
            key=self._configuration.cookie_name,
            value=plaintext_token,
            max_age=self._configuration.cookie_lifetime_seconds,
            path='/',
            secure=self._configuration.secure_cookie,
            httponly=True,
            samesite='strict',
        )
        return response

    def sign_out(self) -> Response:
        """
        Clear the pilot authentication cookie without requiring validity.

        :return: Empty response expiring the authentication cookie.
        """
        response = Response(
            status_code=204,
            headers={'Cache-Control': 'no-store'},
        )
        response.delete_cookie(
            key=self._configuration.cookie_name,
            path='/',
            secure=self._configuration.secure_cookie,
            httponly=True,
            samesite='strict',
        )
        return response
