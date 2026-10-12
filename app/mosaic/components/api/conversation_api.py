from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Request, Response

from .conversation_api_audit import ConversationApiAudit
from .conversation_service import ConversationService
from .conversation_session_projector import ConversationSessionProjector
from ..ada.ada_session_api import AdaSessionApi
from ..identity.trusted_request_context_dependency import TrustedRequestContextDependency
from ..persistence.mosaic_database import MosaicDatabase
from ...models.api.conversation_detail import ConversationDetail
from ...models.api.conversation_list_response import ConversationListResponse
from ...models.api.conversation_projection_configuration import ConversationProjectionConfiguration
from ...models.api.create_conversation_request import CreateConversationRequest
from ...models.identity.trusted_request_context import TrustedRequestContext


class ConversationApi:
    def __init__(
        self,
        database: MosaicDatabase,
        context_dependency: TrustedRequestContextDependency,
        projection_configuration: ConversationProjectionConfiguration,
    ) -> None:
        """
        Bind conversation wrappers to shared trusted identity and public projection.

        :param database: MOSAIC-owned conversation metadata database.
        :param context_dependency: Backend-owned resolver required by every handler.
        :param projection_configuration: Configured public agent and title limits.
        """
        self._database = database
        self._context_dependency = context_dependency
        self._projector = ConversationSessionProjector(projection_configuration)
        self._audit = ConversationApiAudit()

    def register_routes(self, application: FastAPI) -> None:
        """
        Register create, list and get handlers with mandatory trusted context.

        :param application: Public MOSAIC application receiving owned routes.
        """
        router = APIRouter(prefix='/api/v1/conversations')

        async def create(
            body: CreateConversationRequest,
            request: Request,
            response: Response,
            context: Annotated[
                TrustedRequestContext, Depends(self._context_dependency)
            ],
        ) -> ConversationDetail:
            """
            Create an empty conversation without client identity or state.

            :param body: Strict empty public creation request.
            :param request: Request carrying the private server transport.
            :param response: Response receiving a no-store policy.
            :param context: Dependency-derived application and user identity.

            :return: New owned conversation with a server-generated UUID.
            """
            response.headers['Cache-Control'] = 'no-store'
            detail = await self._service(request).create(context)
            response.headers['X-Correlation-ID'] = str(self._audit.completed(context, 'create', 201))
            return detail

        async def list_conversations(
            request: Request,
            response: Response,
            context: Annotated[
                TrustedRequestContext, Depends(self._context_dependency)
            ],
        ) -> ConversationListResponse:
            """
            List only conversations in the trusted application and user scope.

            :param request: Request carrying the private server transport.
            :param response: Response receiving a no-store policy.
            :param context: Dependency-derived application and user identity.

            :return: Public summaries ordered by latest activity first.
            """
            response.headers['Cache-Control'] = 'no-store'
            conversations = await self._service(request).list(context)
            response.headers['X-Correlation-ID'] = str(self._audit.completed(context, 'list', 200))
            return conversations

        async def get(
            conversation_id: UUID,
            request: Request,
            response: Response,
            context: Annotated[
                TrustedRequestContext, Depends(self._context_dependency)
            ],
        ) -> ConversationDetail:
            """
            Retrieve owned public history using a UUID that conveys no ownership.

            :param conversation_id: Validated conversation routing reference.
            :param request: Request carrying the private server transport.
            :param response: Response receiving a no-store policy.
            :param context: Dependency-derived application and user identity.

            :return: Public text-only conversation history.
            """
            response.headers['Cache-Control'] = 'no-store'
            detail = await self._service(request).get(context, conversation_id)
            response.headers['X-Correlation-ID'] = str(self._audit.completed(context, 'get', 200))
            return detail

        router.add_api_route(
            '',
            create,
            methods=['POST'],
            status_code=201,
            response_model=ConversationDetail,
        )
        router.add_api_route(
            '',
            list_conversations,
            methods=['GET'],
            response_model=ConversationListResponse,
        )
        router.add_api_route(
            '/{conversation_id}',
            get,
            methods=['GET'],
            response_model=ConversationDetail,
        )
        application.include_router(router)

    def _service(self, request: Request) -> ConversationService:
        """
        Bind each request to the transport owned by the running backend lifespan.

        :param request: Request whose application owns the private ADA transport.

        :return: Conversation service sharing server-owned storage and projection.
        """
        return ConversationService(
            self._database,
            AdaSessionApi(request.app.state.ada_transport),
            self._projector,
        )
