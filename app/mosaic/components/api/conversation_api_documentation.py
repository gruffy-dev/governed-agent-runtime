from typing import Any

from fastapi import APIRouter, Depends, Response

from .conversation_api_contract import ConversationApiContract
from ..identity.trusted_request_context_dependency import TrustedRequestContextDependency


class ConversationApiDocumentation:
    def __init__(
        self,
        contract: ConversationApiContract,
        context_dependency: TrustedRequestContextDependency,
    ) -> None:
        """
        Bind owned API documentation to the trusted identity boundary.

        :param contract: Public conversation API schema generator.
        :param context_dependency: Middleware-derived identity requirement.
        """
        self._contract = contract
        self._context_dependency = context_dependency

    def register_routes(self, application: Any) -> None:
        """
        Publish the isolated contract behind authenticated user access.

        :param application: FastAPI-compatible application receiving routes.
        """
        router = APIRouter(
            prefix='/api/v1',
            dependencies=[Depends(self._context_dependency)],
        )
        router.add_api_route(
            '/openapi.json',
            self.get_contract,
            methods=['GET'],
            include_in_schema=False,
        )
        application.include_router(router)

    def get_contract(self, response: Response) -> dict[str, Any]:
        """
        Return the public contract without raw ADA models or private state.

        :param response: HTTP response receiving no-store cache policy.

        :return: Versioned public conversation OpenAPI contract.
        """
        response.headers['Cache-Control'] = 'no-store'
        return self._contract.build()
