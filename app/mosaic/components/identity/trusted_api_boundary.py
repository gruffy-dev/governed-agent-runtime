from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import Mount

from .pilot_administration_api import PilotAdministrationApi
from .pilot_authentication_api import PilotAuthenticationApi
from .trusted_request_context_dependency import TrustedRequestContextDependency


class TrustedApiBoundary:
    def __init__(self, context_dependency: TrustedRequestContextDependency) -> None:
        """
        Bind route verification to the backend's one trusted identity dependency.

        :param context_dependency: Server-configured identity resolver for user APIs.
        """
        self._context_dependency = context_dependency

    def validate_routes(self, application: FastAPI) -> None:
        """
        Fail startup if a public wrapper can execute without trusted identity.

        Only the owned sign-in/logout handlers and independently authenticated
        pilot administration handlers are exempt from user identity resolution.
        Mounted applications and WebSocket wrappers are not approved surfaces.

        :param application: Public application after all routes are registered.

        :raises RuntimeError: If a wrapper omits identity or mounts an unchecked app.
        """
        if application.dependency_overrides:
            raise RuntimeError(
                'Public API dependency overrides can bypass trusted identity.'
            )
        for route in application.routes:
            path = getattr(route, 'path', '')
            if isinstance(route, Mount) and (
                path in {'', '/', '/api', '/api/v1'} or path.startswith('/api/v1/')
            ):
                raise RuntimeError(
                    'Public API mounts bypass trusted identity verification.'
                )
            if path != '/api/v1' and not path.startswith('/api/v1/'):
                continue
            if not isinstance(route, APIRoute):
                raise RuntimeError(  # noqa: TRY004 - This is an unsafe startup configuration.
                    'Public API requires verified HTTP wrapper routes.'
                )
            owner = getattr(route.endpoint, '__self__', None)
            name = getattr(route.endpoint, '__name__', '')
            if (
                isinstance(owner, PilotAuthenticationApi)
                and route.methods == {'POST'}
                and (path, name)
                in {
                    ('/api/v1/auth/token', 'sign_in'),
                    ('/api/v1/auth/logout', 'sign_out'),
                }
            ):
                continue
            if (
                path.startswith('/api/v1/admin/')
                and isinstance(owner, PilotAdministrationApi)
                and self._contains(route.dependant, owner._authenticate)
            ):
                continue
            if not self._contains(route.dependant, self._context_dependency):
                raise RuntimeError(
                    'Public API handler requires the trusted identity dependency.'
                )

    @classmethod
    def _contains(cls, dependant: Dependant, expected: object) -> bool:
        """
        Check nested dependency graphs including router-level requirements.

        :param dependant: FastAPI dependency graph for an endpoint or dependency.
        :param expected: Backend-owned callable required before the endpoint runs.

        :return: Whether the required callable exists anywhere in the graph.
        """
        return dependant.call == expected or any(
            cls._contains(child, expected) for child in dependant.dependencies
        )
