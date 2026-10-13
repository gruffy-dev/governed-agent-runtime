from datetime import UTC, datetime
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from .conversation_not_found_error import ConversationNotFoundError
from .conversation_session_projector import ConversationSessionProjector
from .conversation_unavailable_error import ConversationUnavailableError
from ..ada.ada_application_error import AdaApplicationError
from ..ada.ada_session_api import AdaSessionApi
from ..orchestration.orchestration_transition_controller import OrchestrationTransitionController
from ..persistence.conversation_metadata_repository import ConversationMetadataRepository
from ..persistence.mosaic_database import MosaicDatabase
from ...models.api.conversation_detail import ConversationDetail
from ...models.api.conversation_list_response import ConversationListResponse
from ...models.api.conversation_summary import ConversationSummary
from ...models.identity.trusted_request_context import TrustedRequestContext


class ConversationService:
    def __init__(
        self,
        database: MosaicDatabase,
        sessions: AdaSessionApi,
        projector: ConversationSessionProjector,
    ) -> None:
        """
        Combine owned metadata with ADA sessions without copying their history.

        :param database: MOSAIC metadata database.
        :param sessions: Trusted private ADA session adapter.
        :param projector: Public text-only session projection boundary.
        """
        self._database = database
        self._sessions = sessions
        self._projector = projector

    async def create(self, context: TrustedRequestContext) -> ConversationDetail:
        """
        Create an ADA session and publish it only after metadata is committed.

        The two databases do not share a transaction. If projection or metadata
        persistence fails, the ADA-only session is not publicly accessible.

        :param context: Server-derived application and user identity.

        :return: Empty public conversation with authoritative creation time.

        :raises AdaApplicationError: If ADA or public projection fails.
        :raises SQLAlchemyError: If metadata cannot be committed.
        """
        created_at = datetime.now(UTC)
        created = await self._sessions.create(context)
        conversation_id = UUID(created['id'])
        complete = await self._sessions.get(context, conversation_id)
        detail = self._projector.detail(complete, created_at=created_at)
        await run_in_threadpool(
            self._record_creation, context, conversation_id, created_at
        )
        return detail

    async def get(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
    ) -> ConversationDetail:
        """
        Read complete public history within both trusted ownership boundaries.

        :param context: Server-derived application and user identity.
        :param conversation_id: Opaque validated routing UUID.

        :return: Public conversation detail without ADA state or tool payloads.

        :raises ConversationNotFoundError: If metadata or owned ADA session is absent.
        :raises AdaApplicationError: If ADA or projection fails.
        :raises SQLAlchemyError: If metadata cannot be read.
        """
        created_at = await run_in_threadpool(
            self._creation_time, context, conversation_id
        )
        if created_at is None:
            raise ConversationNotFoundError()
        try:
            complete = await self._sessions.get(context, conversation_id)
        except AdaApplicationError as error:
            if error.status_code == 404:
                raise ConversationNotFoundError() from None
            raise
        detail = self._projector.detail(complete, created_at=created_at)
        flags = await run_in_threadpool(self._availability, context, conversation_id)
        if flags is None:
            raise ConversationNotFoundError()
        return detail.model_copy(
            update={'can_continue': flags[0], 'is_interrupted': flags[1]}
        )

    async def begin_invocation(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
    ) -> None:
        """
        Reserve an owned conversation or reject it before any private execution.

        :param context: Server-derived application and user identity.
        :param conversation_id: Validated conversation routing reference.

        :raises ConversationNotFoundError: If owned metadata is absent.
        :raises ConversationUnavailableError: If reserved or interrupted.
        """
        await run_in_threadpool(self._begin_invocation, context, conversation_id)

    async def finish_invocation(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
        normal_eof: bool,
    ) -> None:
        """
        Retain history and mark stopped work unavailable unless completion is saved.

        Call exactly once, only after private stream closure has completed. Do not
        alter ADA state or infer liveness from its persisted planning phase.

        :param context: Server-derived application and user identity.
        :param conversation_id: Conversation reserved by this response.
        :param normal_eof: Whether the entire private stream ended without error.
        """
        completed = False
        if normal_eof:
            try:
                session = await self._sessions.get(context, conversation_id)
                state = session.get('state', {}).get(
                    OrchestrationTransitionController().state_key, {}
                )
                completed = state.get('phase') in (
                    'completed',
                    'awaiting_clarification',
                )
            except (AdaApplicationError, AttributeError, TypeError):
                completed = False
        await run_in_threadpool(
            self._finish_invocation, context, conversation_id, not completed
        )

    async def list(self, context: TrustedRequestContext) -> ConversationListResponse:
        """
        Hydrate owned public conversations and order them by latest activity.

        Skip ADA-only sessions without MOSAIC metadata and sessions deleted
        between listing and retrieval. Do not infer timestamps for legacy data.

        :param context: Server-derived application and user identity.

        :return: Public summaries in descending activity order with stable UUID ties.

        :raises AdaApplicationError: If ADA or projection fails.
        :raises SQLAlchemyError: If metadata cannot be read.
        """
        summaries: list[ConversationSummary] = []
        for session in await self._sessions.list(context):
            try:
                conversation_id = UUID(session['id'])
            except ValueError:
                continue
            try:
                detail = await self.get(context, conversation_id)
            except ConversationNotFoundError:
                continue
            summaries.append(
                ConversationSummary.model_validate(
                    detail.model_dump(exclude={'messages'})
                )
            )
        return ConversationListResponse(
            conversations=tuple(
                sorted(
                    summaries,
                    key=lambda item: (
                        -item.last_activity_at.timestamp(),
                        str(item.conversation_id),
                    ),
                )
            )
        )

    def _record_creation(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
        created_at: datetime,
    ) -> None:
        """
        Commit metadata in a short worker-thread transaction after ADA returns.

        :param context: Trusted owner of the new conversation.
        :param conversation_id: UUID generated by the private session adapter.
        :param created_at: Backend-recorded original creation time.
        """
        with self._database.create_session() as session, session.begin():
            ConversationMetadataRepository(session).add(
                context, conversation_id, created_at
            )

    def _availability(
        self, context: TrustedRequestContext, conversation_id: UUID
    ) -> tuple[bool, bool] | None:
        """
        Read owned availability without exposing reservation or SDK internals.

        :param context: Trusted conversation owner.
        :param conversation_id: Validated routing reference.

        :return: Continuation and interruption flags, or None for absent metadata.
        """
        with self._database.create_session() as session:
            return ConversationMetadataRepository(session).get_availability(
                context, conversation_id
            )

    def _begin_invocation(
        self, context: TrustedRequestContext, conversation_id: UUID
    ) -> None:
        """
        Commit a conditional database reservation in a short worker transaction.

        :param context: Trusted conversation owner.
        :param conversation_id: Validated routing reference.

        :raises ConversationNotFoundError: If owned metadata is absent.
        :raises ConversationUnavailableError: If the reservation cannot be acquired.
        """
        with self._database.create_session() as session, session.begin():
            repository = ConversationMetadataRepository(session)
            if not repository.begin_invocation(context, conversation_id):
                flags = repository.get_availability(context, conversation_id)
                if flags is None:
                    raise ConversationNotFoundError()
                raise ConversationUnavailableError(is_interrupted=flags[1])

    def _finish_invocation(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
        is_interrupted: bool,
    ) -> None:
        """
        Persist availability without modifying or deleting historical messages.

        :param context: Trusted conversation owner.
        :param conversation_id: Routing reference reserved by the calling response.
        :param is_interrupted: Whether the stopped invocation prevents continuation.
        """
        with self._database.create_session() as session, session.begin():
            ConversationMetadataRepository(session).finish_invocation(
                context, conversation_id, is_interrupted=is_interrupted
            )

    def _creation_time(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
    ) -> datetime | None:
        """
        Read owned creation metadata without holding a transaction across ADA I/O.

        :param context: Trusted owner used for metadata lookup.
        :param conversation_id: UUID routing reference.

        :return: UTC creation timestamp, or None for missing or foreign metadata.
        """
        with self._database.create_session() as session:
            return ConversationMetadataRepository(session).get_created_at(
                context, conversation_id
            )
