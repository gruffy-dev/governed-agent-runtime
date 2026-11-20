import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing, suppress
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from ...models.api.conversation_job_detail import ConversationJobDetail
from ...models.api.submit_message_request import SubmitMessageRequest
from ...models.identity.trusted_request_context import TrustedRequestContext
from ..ada.ada_asgi_transport import AdaAsgiTransport
from ..ada.ada_invocation_api import AdaInvocationApi
from ..ada.ada_session_api import AdaSessionApi
from ..orchestration.orchestration_transition_controller import OrchestrationTransitionController
from ..persistence.conversation_job_event_record import ConversationJobEventRecord
from ..persistence.conversation_job_repository import ConversationJobRepository
from ..persistence.conversation_metadata_repository import ConversationMetadataRepository
from ..persistence.mosaic_database import MosaicDatabase
from .ada_streaming_response import AdaStreamingResponse
from .conversation_not_found_error import ConversationNotFoundError
from .conversation_unavailable_error import ConversationUnavailableError
from .job_submission_conflict_error import JobSubmissionConflictError


class ConversationJobService:
    def __init__(self, database: MosaicDatabase) -> None:
        """
        Track local execution tasks and share their results through the database.

        :param database: MOSAIC-owned database containing jobs and stream events.
        """
        self._database = database
        self._tasks: set[asyncio.Task[None]] = set()
        self._closing = False

    async def submit(
        self, context: TrustedRequestContext, conversation_id: UUID, message: SubmitMessageRequest,
        transport: AdaAsgiTransport, maximum_event_bytes: int, public_agent_name: str,
        submission_key: UUID | None = None,
    ) -> ConversationJobDetail:
        """
        Commit a job and start execution independently of the submitting request.

        :param context: Authenticated conversation owner.
        :param conversation_id: Conversation receiving the message.
        :param message: Validated user message.
        :param transport: Lifespan-owned private transport.
        :param maximum_event_bytes: Maximum private event size.
        :param public_agent_name: Agent whose output is public.
        :param submission_key: Optional key reused when retrying a submission.

        :return: Acknowledgement for the committed job.
        """
        detail, created = await run_in_threadpool(
            self._reserve, context, conversation_id, message.text, submission_key,
        )
        if created:
            task = asyncio.create_task(self._run(
                context, detail.job_id, conversation_id, message, transport, maximum_event_bytes, public_agent_name,
            ))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return detail

    async def close(self) -> None:
        """
        Stop and join local execution tasks before the private transport shuts down.
        """
        self._closing = True
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def recover_abandoned(self, transport: AdaAsgiTransport) -> None:
        """
        Fail old unfinished jobs before the exclusive pilot runtime accepts traffic.

        :param transport: Started private transport used to verify or repair sessions.
        """
        for context, job_id, conversation_id, status in await run_in_threadpool(self._abandoned):
            can_continue = status == 'queued' or await self._recover_stopped_session(context, conversation_id, transport)
            await run_in_threadpool(self._fail_abandoned, context, job_id, can_continue)

    def _abandoned(self) -> list[tuple[TrustedRequestContext, UUID, UUID, str]]:
        """
        Read unfinished jobs with their trusted ownership context.

        :return: Unfinished jobs persisted by the former runtime.
        """
        with self._database.create_session() as session:
            return ConversationJobRepository(session).abandoned_jobs()

    def _fail_abandoned(self, context: TrustedRequestContext, job_id: UUID, can_continue: bool) -> None:
        """
        Record the recovered job and release or interrupt its conversation.

        :param context: Trusted conversation owner.
        :param job_id: Abandoned job identifier.
        :param can_continue: Whether the private state permits a follow-up.
        """
        with self._database.create_session() as session, session.begin():
            ConversationJobRepository(session).fail_abandoned(context, job_id, can_continue=can_continue)

    async def get(self, context: TrustedRequestContext, job_id: UUID) -> ConversationJobDetail:
        """
        Read an owned job and its saved outcome.

        :param context: Authenticated job owner.
        :param job_id: Job identifier.

        :return: Current job status and result.
        """
        return await run_in_threadpool(self._get, context, job_id, False)

    async def stop(self, context: TrustedRequestContext, job_id: UUID) -> ConversationJobDetail:
        """
        Request explicit cancellation without releasing a running reservation.

        :param context: Authenticated job owner.
        :param job_id: Job identifier.

        :return: Current job status, including a terminal outcome if it won the race.
        """
        return await run_in_threadpool(self._get, context, job_id, True)

    async def events(self, context: TrustedRequestContext, job_id: UUID, after: int) -> AsyncIterator[bytes]:
        """
        Replay public events and follow new events without owning execution.

        :param context: Authenticated job owner.
        :param job_id: Job identifier.
        :param after: Last event sequence received by the caller.

        :return: SSE frames with stable IDs for replay.
        """
        while True:
            job, events = await run_in_threadpool(self._read_events, context, job_id, after)
            for sequence, frame in events:
                yield f'id: {sequence}\n'.encode() + frame
                after = sequence
            if len(events) == 64:
                continue
            if job.status not in ('queued', 'running', 'stopping'):
                return
            await asyncio.sleep(0.25)

    def _reserve(
        self, context: TrustedRequestContext, conversation_id: UUID, text: str, submission_key: UUID | None,
    ) -> tuple[ConversationJobDetail, bool]:
        """
        Reserve the conversation and create a pollable job.
        """
        try:
            with self._database.create_session() as session, session.begin():
                repository = ConversationJobRepository(session)
                existing = self._existing_submission(repository, context, conversation_id, text, submission_key)
                if existing is not None:
                    return existing, False
                job_id = repository.reserve(context, conversation_id, text, submission_key)
                if job_id is not None:
                    return ConversationJobDetail(
                        job_id=job_id, conversation_id=conversation_id, status='queued', result_text=None,
                    ), True
                existing = self._existing_submission(repository, context, conversation_id, text, submission_key)
                if existing is not None:
                    return existing, False
                availability = ConversationMetadataRepository(session).get_availability(context, conversation_id)
                if availability is None:
                    raise ConversationNotFoundError()
                raise ConversationUnavailableError(is_interrupted=availability[1])
        except IntegrityError:
            with self._database.create_session() as session:
                existing = self._existing_submission(
                    ConversationJobRepository(session), context, conversation_id, text, submission_key,
                )
            if existing is None:
                raise
            return existing, False

    @staticmethod
    def _existing_submission(
        repository: ConversationJobRepository, context: TrustedRequestContext,
        conversation_id: UUID, text: str, submission_key: UUID | None,
    ) -> ConversationJobDetail | None:
        """
        Read the original outcome of a retry and reject reuse with changed text.

        :param repository: Job repository for the current transaction.
        :param context: Authenticated owner.
        :param conversation_id: Owned conversation.
        :param text: Exact validated message for the retry.
        :param submission_key: Optional client-supplied UUID.

        :return: Existing job if the submission key was already used.

        :raises JobSubmissionConflictError: If the key was used with different text.
        """
        if submission_key is None:
            return None
        existing = repository.get_by_submission_key(context, conversation_id, submission_key)
        if existing is None:
            return None
        if existing.request_text != text:
            raise JobSubmissionConflictError()
        return ConversationJobDetail.model_validate(existing)

    def _get(self, context: TrustedRequestContext, job_id: UUID, stop: bool) -> ConversationJobDetail:
        """
        Optionally request cancellation and return the committed status.
        """
        with self._database.create_session() as session, session.begin():
            repository = ConversationJobRepository(session)
            if stop:
                repository.request_stop(context, job_id)
            job = repository.get(context, job_id)
            if job is None:
                raise ConversationNotFoundError()
            return ConversationJobDetail.model_validate(job)

    def _read_events(self, context: TrustedRequestContext, job_id: UUID, after: int) -> tuple[ConversationJobDetail, list[tuple[int, bytes]]]:
        """
        Get one bounded page of frames in sequence order.
        """
        with self._database.create_session() as session:
            job = ConversationJobRepository(session).get(context, job_id)
            if job is None:
                raise ConversationNotFoundError()
            events = session.execute(
                select(ConversationJobEventRecord.sequence, ConversationJobEventRecord.frame)
                .where(ConversationJobEventRecord.job_id == str(job_id), ConversationJobEventRecord.sequence > after)
                .order_by(ConversationJobEventRecord.sequence)
                .limit(64)
            )
            return ConversationJobDetail.model_validate(job), [(sequence, frame) for sequence, frame in events]

    def _claim(self, context: TrustedRequestContext, job_id: UUID) -> bool:
        """
        Acquire a queued job once.
        """
        with self._database.create_session() as session, session.begin():
            return ConversationJobRepository(session).claim(context, job_id)

    def _save_event(self, job_id: UUID, sequence: int, frame: bytes) -> None:
        """
        Persist a redacted SSE frame for replay by other connections.
        """
        with self._database.create_session() as session, session.begin():
            session.add(ConversationJobEventRecord(job_id=str(job_id), sequence=sequence, frame=frame))

    async def _run(
        self, context: TrustedRequestContext, job_id: UUID, conversation_id: UUID,
        message: SubmitMessageRequest, transport: AdaAsgiTransport,
        maximum_event_bytes: int, public_agent_name: str,
    ) -> None:
        """
        Run the private stream until it closes or the owner explicitly stops it.
        """
        if not await run_in_threadpool(self._claim, context, job_id):
            return
        execution = asyncio.create_task(self._consume(
            context, job_id, conversation_id, message, transport, maximum_event_bytes, public_agent_name,
        ))
        phase = None
        result = None
        try:
            while not execution.done():
                await asyncio.wait((execution,), timeout=0.25)
                if not execution.done() and (await self.get(context, job_id)).status == 'stopping':
                    execution.cancel()
                    break
            with suppress(asyncio.CancelledError):
                phase, result = await asyncio.shield(execution)
        finally:
            if not execution.done():
                execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            if not self._closing:
                await self._finalise(context, job_id, conversation_id, transport, phase, result)

    async def _finalise(
        self, context: TrustedRequestContext, job_id: UUID, conversation_id: UUID,
        transport: AdaAsgiTransport, phase: str | None, result: str | None,
    ) -> None:
        """
        Publish completion or recover a stopped job after its private stream closes.
        """
        job = await self.get(context, job_id)
        if job.status != 'stopping':
            can_continue = await self._can_continue(context, conversation_id, transport)
            status = {
                'completed': 'succeeded',
                'awaiting_clarification': 'awaiting_clarification',
            }.get(phase, 'failed')
            finished = await run_in_threadpool(self._finish, context, job_id, status, result, can_continue)
            needs_recovery = not finished and (await self.get(context, job_id)).status == 'stopping'
        else:
            needs_recovery = True
        if needs_recovery:
            can_continue = await self._recover_stopped_session(context, conversation_id, transport)
            await run_in_threadpool(self._finish, context, job_id, 'cancelled', None, can_continue)

    async def _recover_stopped_session(
        self, context: TrustedRequestContext, conversation_id: UUID, transport: AdaAsgiTransport,
    ) -> bool:
        """
        Recover the owned session before publishing cancellation and releasing it.
        """
        try:
            await AdaSessionApi(transport).complete_stopped_goal(context, conversation_id)
        except Exception:  # noqa: BLE001 - keep the conversation reserved until failure is recorded.
            logging.getLogger(__name__).warning('Stopped conversation could not be recovered')
            return False
        return True

    async def _can_continue(
        self, context: TrustedRequestContext, conversation_id: UUID, transport: AdaAsgiTransport,
    ) -> bool:
        """
        Verify the closed private invocation left no active goal blocking follow-ups.
        """
        try:
            session = await AdaSessionApi(transport).get(context, conversation_id)
            state = session.get('state', {}).get(OrchestrationTransitionController().state_key)
            return state is None or state.get('phase') in ('completed', 'awaiting_clarification')
        except Exception:  # noqa: BLE001 - an uncertain private state stays unavailable.
            return False

    def _finish(
        self, context: TrustedRequestContext, job_id: UUID,
        status: Literal['succeeded', 'awaiting_clarification', 'failed', 'cancelled'],
        result: str | None, can_continue: bool,
    ) -> bool:
        """
        Commit the job outcome and release or quarantine its conversation.
        """
        with self._database.create_session() as session, session.begin():
            return ConversationJobRepository(session).finish(
                context, job_id, status, can_continue=can_continue,
                result_text=result if status != 'failed' else None,
            )

    async def _consume(
        self, context: TrustedRequestContext, job_id: UUID, conversation_id: UUID,
        message: SubmitMessageRequest, transport: AdaAsgiTransport,
        maximum_event_bytes: int, public_agent_name: str,
    ) -> tuple[str | None, str | None]:
        """
        Persist only public events and use ADA's saved phase to confirm completion.
        """
        complete = False

        async def record_completion(normal_eof: bool) -> None:
            nonlocal complete
            complete = normal_eof

        try:
            response = await AdaStreamingResponse.create(
                AdaInvocationApi(transport).stream(context, conversation_id, message),
                maximum_event_bytes, public_agent_name, record_completion,
            )
            last_answer = None
            sequence = 0
            async with aclosing(response.public_events()) as events:
                async for frame in events:
                    sequence += 1
                    await run_in_threadpool(self._save_event, job_id, sequence, frame)
                    record = json.loads(frame.removeprefix(b'data: '))
                    content = record.get('content', {})
                    if content.get('role') == 'model' and record.get('partial') is not True:
                        answer = ''.join(part.get('text', '') for part in content['parts'])
                        if answer:
                            last_answer = answer

            if complete:
                session = await AdaSessionApi(transport).get(context, conversation_id)
                state = session.get('state', {}).get(OrchestrationTransitionController().state_key, {})
                return state.get('phase'), last_answer
        except Exception:  # noqa: BLE001 - upstream diagnostics stay private.
            logging.getLogger(__name__).warning('Conversation job execution failed', extra={'job_id': str(job_id)})
        return None, None
