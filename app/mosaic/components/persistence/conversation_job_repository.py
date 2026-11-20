from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from ...models.api.conversation_job_summary import ConversationJobSummary
from ...models.identity.trusted_request_context import TrustedRequestContext
from .conversation_job_record import ConversationJobRecord
from .conversation_metadata_record import ConversationMetadataRecord
from .conversation_metadata_repository import ConversationMetadataRepository


class ConversationJobRepository:
    def __init__(self, session: Session) -> None:
        """
        Bind job storage to a caller-owned database transaction.

        :param session: Session used for both job storage and conversation reservations.
        """
        self._session = session

    def reserve(
        self, context: TrustedRequestContext, conversation_id: UUID, request_text: str,
        submission_key: UUID | None = None,
    ) -> UUID | None:
        """
        Reserve a conversation and queue a job in the same transaction.

        :param context: Trusted conversation owner.
        :param conversation_id: Conversation receiving the job.
        :param request_text: Validated user message to execute.
        :param submission_key: Client key scoped to the owned conversation.

        :return: New job ID, or None if the conversation could not be reserved.
        """
        if not ConversationMetadataRepository(self._session).begin_invocation(
            context, conversation_id,
        ):
            return None

        job_id = uuid4()
        now = datetime.now(UTC)
        self._session.add(ConversationJobRecord(
            job_id=str(job_id), conversation_id=str(conversation_id),
            request_text=request_text, submission_key=str(submission_key) if submission_key else None,
            status='queued',
            created_at=now, updated_at=now,
        ))
        return job_id

    def get(self, context: TrustedRequestContext, job_id: UUID) -> ConversationJobRecord | None:
        """
        Fetch a job only within the authenticated conversation owner's scope.

        :param context: Trusted application and user identity.
        :param job_id: Job identifier supplied by the client.

        :return: Owned job record, or None if absent or owned by someone else.
        """
        return self._session.scalars(
            self._owned_jobs(context).where(ConversationJobRecord.job_id == str(job_id))
        ).one_or_none()

    def get_by_submission_key(
        self, context: TrustedRequestContext, conversation_id: UUID, submission_key: UUID,
    ) -> ConversationJobRecord | None:
        """
        Resolve an earlier request under the same conversation and owner.

        :param context: Trusted application and user identity.
        :param conversation_id: Owned conversation scope.
        :param submission_key: Key from the original submission.

        :return: Matching job, if present.
        """
        return self._session.scalars(
            self._owned_jobs(context).where(
                ConversationJobRecord.conversation_id == str(conversation_id),
                ConversationJobRecord.submission_key == str(submission_key),
            )
        ).one_or_none()

    def _owned_jobs(self, context: TrustedRequestContext) -> Select[tuple[ConversationJobRecord]]:
        """
        Scope a job query to the authenticated owner.

        :param context: Trusted application and user identity.

        :return: Select statement for owned job records.
        """
        return (
            select(ConversationJobRecord)
            .join(
                ConversationMetadataRecord,
                ConversationJobRecord.conversation_id == ConversationMetadataRecord.conversation_id,
            )
            .where(
                ConversationMetadataRecord.app_name == context.app_name,
                ConversationMetadataRecord.user_id == context.user_id,
            )
        )

    def abandoned_jobs(self) -> list[tuple[TrustedRequestContext, UUID, UUID, str]]:
        """
        Find unfinished jobs after acquiring exclusive pilot runtime ownership.

        :return: Owner, job ID, conversation ID and current status for recovery.
        """
        rows = self._session.execute(
            select(
                ConversationMetadataRecord.app_name, ConversationMetadataRecord.user_id,
                ConversationJobRecord.job_id, ConversationJobRecord.conversation_id, ConversationJobRecord.status,
            )
            .join(ConversationMetadataRecord, ConversationJobRecord.conversation_id == ConversationMetadataRecord.conversation_id)
            .where(ConversationJobRecord.status.in_(('queued', 'running', 'stopping')))
        )
        return [
            (TrustedRequestContext(app_name=row.app_name, user_id=row.user_id), UUID(row.job_id), UUID(row.conversation_id), row.status)
            for row in rows
        ]

    def fail_abandoned(self, context: TrustedRequestContext, job_id: UUID, *, can_continue: bool) -> None:
        """
        Record an abandoned job as failed and clear its conversation reservation.

        :param context: Stored owner of the abandoned job.
        :param job_id: Job left behind by the former runtime.
        :param can_continue: Whether the private session is ready for a follow-up.
        """
        conversation_id = self._transition(context, job_id, ('queued', 'running', 'stopping'), 'failed')
        if conversation_id is not None:
            ConversationMetadataRepository(self._session).finish_invocation(
                context, conversation_id, is_interrupted=not can_continue,
            )

    def get_conversation_status(
        self, context: TrustedRequestContext, conversation_id: UUID,
    ) -> tuple[bool, bool, ConversationJobSummary | None] | None:
        """
        Read availability and latest job together for an owned conversation.

        :param context: Trusted application and user identity.
        :param conversation_id: Conversation identifier supplied by the client.

        :return: Continuation flag, interruption flag and optional job summary,
            or None for a missing or foreign conversation.
        """
        row = self._session.execute(
            select(
                ConversationMetadataRecord.invocation_in_progress,
                ConversationMetadataRecord.is_interrupted,
                ConversationJobRecord.job_id,
                ConversationJobRecord.status,
            )
            .select_from(ConversationMetadataRecord)
            .outerjoin(
                ConversationJobRecord,
                ConversationJobRecord.conversation_id == ConversationMetadataRecord.conversation_id,
            )
            .where(
                ConversationMetadataRecord.conversation_id == str(conversation_id),
                ConversationMetadataRecord.app_name == context.app_name,
                ConversationMetadataRecord.user_id == context.user_id,
            )
            .order_by(ConversationJobRecord.created_at.desc(), ConversationJobRecord.job_id.desc())
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        latest_job = None if row.job_id is None else ConversationJobSummary.model_validate(row)
        return (
            not row.invocation_in_progress and not row.is_interrupted,
            row.is_interrupted,
            latest_job,
        )

    def claim(self, context: TrustedRequestContext, job_id: UUID) -> bool:
        """
        Acquire a queued job for execution with a conditional database update.

        :param context: Trusted conversation owner.
        :param job_id: Job to claim.

        :return: True if this transaction claimed the job.
        """
        return self._transition(context, job_id, ('queued',), 'running') is not None

    def request_stop(self, context: TrustedRequestContext, job_id: UUID) -> bool:
        """
        Cancel queued work or signal the worker to stop active execution.

        :param context: Trusted conversation owner.
        :param job_id: Job the owner requested to stop.

        :return: True if cancellation was requested or already in effect.
        """
        conversation_id = self._transition(context, job_id, ('queued',), 'cancelled')
        if conversation_id is not None:
            ConversationMetadataRepository(self._session).finish_invocation(
                context, conversation_id, is_interrupted=False,
            )
            return True

        if self._transition(context, job_id, ('running',), 'stopping') is not None:
            return True

        job = self.get(context, job_id)
        return job is not None and job.status in ('stopping', 'cancelled')

    def finish(
        self,
        context: TrustedRequestContext,
        job_id: UUID,
        status: Literal['succeeded', 'awaiting_clarification', 'failed', 'cancelled'],
        *,
        can_continue: bool,
        result_text: str | None = None,
    ) -> bool:
        """
        Store the outcome and release the reservation after upstream execution ends.

        :param context: Trusted owner passed to the worker that claimed this job.
        :param job_id: Identifier of the claimed job.
        :param status: Outcome reported by the worker after closing the stream.
        :param can_continue: Whether the upstream session is safe to use again.
        :param result_text: Public final answer or clarification question, if available.

        :return: True if this transaction accepted the outcome.
        """
        expected = ('stopping',) if status == 'cancelled' else ('running',)
        conversation_id = self._transition(context, job_id, expected, status, result_text)
        if conversation_id is None:
            return False

        ConversationMetadataRepository(self._session).finish_invocation(
            context, conversation_id, is_interrupted=not can_continue,
        )
        return True

    def _transition(
        self,
        context: TrustedRequestContext,
        job_id: UUID,
        expected: tuple[str, ...],
        status: str,
        result_text: str | None = None,
    ) -> UUID | None:
        """
        Change an owned job only when its stored status still matches.

        :param context: Trusted conversation owner.
        :param job_id: Job to update.
        :param expected: Current statuses that allow this transition.
        :param status: Status to publish.
        :param result_text: Public response to store with the status.

        :return: Reserved conversation ID when the update succeeds.
        """
        owned = select(ConversationMetadataRecord.conversation_id).where(
            ConversationMetadataRecord.app_name == context.app_name,
            ConversationMetadataRecord.user_id == context.user_id,
        )
        conversation_id = self._session.execute(
            update(ConversationJobRecord)
            .where(
                ConversationJobRecord.job_id == str(job_id),
                ConversationJobRecord.conversation_id.in_(owned),
                ConversationJobRecord.status.in_(expected),
            )
            .values(status=status, result_text=result_text, updated_at=datetime.now(UTC))
            .returning(ConversationJobRecord.conversation_id)
        ).scalar_one_or_none()
        return UUID(conversation_id) if conversation_id is not None else None
