from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import StreamingResponse
import anyio

from .ada_streaming_response import AdaStreamingResponse
from .conversation_api_audit import ConversationApiAudit
from .conversation_not_found_error import ConversationNotFoundError
from .conversation_service import ConversationService
from .conversation_session_projector import ConversationSessionProjector
from ..ada.ada_session_api import AdaSessionApi
from ..ada.ada_invocation_api import AdaInvocationApi
from ..ada.ada_application_error import AdaApplicationError
from ..identity.trusted_request_context_dependency import TrustedRequestContextDependency
from ..persistence.mosaic_database import MosaicDatabase
from ...models.api.conversation_detail import ConversationDetail
from ...models.api.conversation_job_detail import ConversationJobDetail
from ...models.api.conversation_list_response import ConversationListResponse
from ...models.api.conversation_projection_configuration import ConversationProjectionConfiguration
from ...models.api.create_conversation_request import CreateConversationRequest
from ...models.api.submit_message_request import SubmitMessageRequest
from ...models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration
from ...models.identity.trusted_request_context import TrustedRequestContext


class ConversationApi:
    def __init__(
        self,
        database: MosaicDatabase,
        context_dependency: TrustedRequestContextDependency,
        projection_configuration: ConversationProjectionConfiguration,
        adapter_configuration: AdaApplicationAdapterConfiguration,
    ) -> None:
        """
        Bind conversation wrappers to shared trusted identity and public projection.

        :param database: MOSAIC-owned conversation metadata database.
        :param context_dependency: Backend-owned resolver required by every handler.
        :param projection_configuration: Configured public agent and title limits.
        :param adapter_configuration: Existing private transport and event bounds.
        """
        self._database = database
        self._context_dependency = context_dependency
        self._projector = ConversationSessionProjector(projection_configuration)
        self._audit = ConversationApiAudit()
        self._adapter_configuration = adapter_configuration
        self._public_agent_name = projection_configuration.public_agent_name

    def register_routes(self, application: FastAPI) -> None:
        """
        Register conversation and streaming handlers with mandatory trusted context.

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

        async def submit_message(
            conversation_id: UUID,
            body: SubmitMessageRequest,
            request: Request,
            context: Annotated[
                TrustedRequestContext, Depends(self._context_dependency)
            ],
        ) -> AdaStreamingResponse:
            """
            Stream an owned conversation's answer using ADK data events.

            :param conversation_id: Validated conversation routing reference.
            :param body: Strict text-only request with no identity or state claims.
            :param request: Request carrying the private server transport.
            :param context: Dependency-derived application and user identity.

            :return: Incremental response whose disconnect closes private execution.
            """
            service = self._service(request)
            await service.begin_invocation(context, conversation_id)
            stream = AdaInvocationApi(request.app.state.ada_transport).stream(
                context, conversation_id, body
            )
            try:
                response = await AdaStreamingResponse.create(
                    stream,
                    self._adapter_configuration.maximum_response_bytes,
                    self._public_agent_name,
                    partial(service.finish_invocation, context, conversation_id),
                )
            except BaseException as error:
                with anyio.CancelScope(shield=True):
                    await service.finish_invocation(context, conversation_id, False)
                if isinstance(error, AdaApplicationError) and error.status_code == 404:
                    raise ConversationNotFoundError() from None
                raise
            response.headers['X-Correlation-ID'] = str(self._audit.completed(context, 'submit', 200))
            return response

        @router.post('/{conversation_id}/jobs', status_code=202)
        async def submit_job(
            conversation_id: UUID, body: SubmitMessageRequest, request: Request, response: Response,
            context: Annotated[TrustedRequestContext, Depends(self._context_dependency)],
            submission_key: Annotated[UUID | None, Header(alias='Idempotency-Key')] = None,
        ) -> ConversationJobDetail:
            """
            Reserve the conversation and return the job before execution completes.
            """
            response.headers['Cache-Control'] = 'no-store'
            return await request.app.state.conversation_jobs.submit(
                context, conversation_id, body, request.app.state.ada_transport,
                self._adapter_configuration.maximum_response_bytes, self._public_agent_name,
                submission_key,
            )

        @router.get('/jobs/{job_id}')
        async def get_job(
            job_id: UUID, request: Request, response: Response,
            context: Annotated[TrustedRequestContext, Depends(self._context_dependency)],
        ) -> ConversationJobDetail:
            """
            Return the owned job status and any saved result.
            """
            response.headers['Cache-Control'] = 'no-store'
            return await request.app.state.conversation_jobs.get(context, job_id)

        @router.get('/jobs/{job_id}/events')
        async def job_events(
            job_id: UUID, request: Request,
            context: Annotated[TrustedRequestContext, Depends(self._context_dependency)],
            after: Annotated[int, Query(ge=0)] = 0,
        ) -> StreamingResponse:
            """
            Replay and stream public events by sequence number.
            """
            jobs = request.app.state.conversation_jobs
            await jobs.get(context, job_id)
            return StreamingResponse(
                jobs.events(context, job_id, after), media_type='text/event-stream',
                headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'},
            )

        @router.post('/jobs/{job_id}/stop')
        async def stop_job(
            job_id: UUID, request: Request, response: Response,
            context: Annotated[TrustedRequestContext, Depends(self._context_dependency)],
        ) -> ConversationJobDetail:
            """
            Request explicit cancellation of an owned job.
            """
            response.headers['Cache-Control'] = 'no-store'
            return await request.app.state.conversation_jobs.stop(context, job_id)

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
        router.add_api_route(
            '/{conversation_id}/messages',
            submit_message,
            methods=['POST'],
            response_class=AdaStreamingResponse,
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
