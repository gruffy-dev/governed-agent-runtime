import unittest
from typing import Annotated
from unittest.mock import Mock

from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from mosaic.components.identity.authentication_failure_handler import AuthenticationFailureHandler
from mosaic.components.identity.pilot_authentication_api import PilotAuthenticationApi
from mosaic.components.identity.trusted_api_boundary import TrustedApiBoundary
from mosaic.components.identity.trusted_request_context_dependency import TrustedRequestContextDependency
from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration
from mosaic.models.identity.trusted_request_configuration import TrustedRequestConfiguration
from mosaic.models.identity.trusted_request_context import TrustedRequestContext


class TestTrustedApiBoundary(unittest.TestCase):
    def setUp(self) -> None:
        self.application = FastAPI()
        self.dependency = TrustedRequestContextDependency(
            TrustedRequestConfiguration(app_name='synthetic-app')
        )
        self.boundary = TrustedApiBoundary(self.dependency)

    def test_rejects_wrapper_without_dependency(self) -> None:
        async def unchecked() -> dict[str, str]:
            return {'status': 'unchecked'}

        self.application.add_api_route('/api/v1/conversations', unchecked)
        with self.assertRaisesRegex(RuntimeError, 'trusted identity dependency'):
            self.boundary.validate_routes(self.application)

    def test_accepts_router_dependency_and_nested_dependency(self) -> None:
        async def nested(
            context: Annotated[TrustedRequestContext, Depends(self.dependency)],
        ) -> TrustedRequestContext:
            return context

        async def checked() -> dict[str, str]:
            return {'status': 'checked'}

        router = APIRouter(prefix='/api/v1', dependencies=[Depends(nested)])
        router.add_api_route('/conversations', checked)
        self.application.include_router(router)
        self.boundary.validate_routes(self.application)

    def test_wrong_server_dependency_is_not_accepted(self) -> None:
        other = TrustedRequestContextDependency(
            TrustedRequestConfiguration(app_name='another-app')
        )

        async def unchecked() -> dict[str, str]:
            return {}

        self.application.add_api_route(
            '/api/v1/conversations',
            unchecked,
            dependencies=[Depends(other)],
        )
        with self.assertRaises(RuntimeError):
            self.boundary.validate_routes(self.application)

    def test_exemption_requires_owned_authentication_handlers(self) -> None:
        PilotAuthenticationApi(
            PilotAuthenticationConfiguration(mode='local', secure_cookie=False),
            Mock(),
        ).register_routes(self.application)
        self.boundary.validate_routes(self.application)

        async def impersonator() -> dict[str, str]:
            return {}

        self.application.add_api_route(
            '/api/v1/auth/token',
            impersonator,
            methods=['POST'],
        )
        with self.assertRaises(RuntimeError):
            self.boundary.validate_routes(self.application)

    def test_admin_prefix_alone_is_not_an_exemption(self) -> None:
        async def unchecked() -> dict[str, str]:
            return {}

        self.application.add_api_route('/api/v1/admin/users', unchecked)
        with self.assertRaises(RuntimeError):
            self.boundary.validate_routes(self.application)

    def test_rejects_mounts_covering_the_public_api(self) -> None:
        for path in ('/', '/api', '/api/v1', '/api/v1/private'):
            with self.subTest(path=path):
                application = FastAPI()
                application.mount(path, FastAPI())
                with self.assertRaises(RuntimeError):
                    self.boundary.validate_routes(application)

    def test_rejects_websocket_wrappers(self) -> None:
        async def unchecked() -> None:
            pass

        self.application.add_api_websocket_route('/api/v1/live', unchecked)
        with self.assertRaises(RuntimeError):
            self.boundary.validate_routes(self.application)

    def test_rejects_dependency_overrides(self) -> None:
        self.application.dependency_overrides[self.dependency] = lambda: None
        with self.assertRaisesRegex(RuntimeError, 'overrides'):
            self.boundary.validate_routes(self.application)

    def test_registered_dependency_blocks_execution_without_authentication(
        self,
    ) -> None:
        called: list[str] = []

        async def checked() -> dict[str, str]:
            called.append('handler')
            return {}

        self.application.add_api_route(
            '/api/v1/conversations',
            checked,
            dependencies=[Depends(self.dependency)],
        )
        AuthenticationFailureHandler().register(self.application)
        self.boundary.validate_routes(self.application)
        with TestClient(self.application) as client:
            response = client.get('/api/v1/conversations')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(called, [])
