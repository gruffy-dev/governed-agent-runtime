import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from .conversation_job_event_record import ConversationJobEventRecord
from .conversation_job_record import ConversationJobRecord
from .conversation_job_repository import ConversationJobRepository
from .mosaic_database import MosaicDatabase


class MosaicDatabaseMaintenance:
    replay_retention = timedelta(hours=1)
    job_retention = timedelta(days=7)
    interval = timedelta(hours=1)
    batch_size = 500

    def __init__(self, database: MosaicDatabase) -> None:
        """
        Bind periodic maintenance to the MOSAIC database.

        :param database: Runtime-owned database to maintain.
        """
        self._database = database

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        """
        Run maintenance before serving requests, then hourly until shutdown.

        :return: Context that waits for outstanding maintenance on exit.
        """
        shutdown = asyncio.Event()
        await self._clean(shutdown)
        periodic = asyncio.create_task(self._periodically(shutdown))
        try:
            yield
        finally:
            shutdown.set()
            await periodic

    @classmethod
    def replay_has_expired(cls, job: ConversationJobRecord, now: datetime) -> bool:
        """
        Check the same replay cutoff used during deletion.

        :param job: Owner-validated job record.
        :param now: Current UTC time.

        :return: True when the replay window has closed for a finished job.
        """
        finished = job.updated_at
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=UTC)
        return job.status not in ConversationJobRepository.active_statuses and finished <= now - cls.replay_retention

    async def _periodically(self, shutdown: asyncio.Event) -> None:
        """
        Repeat database maintenance while serving requests.

        :param shutdown: Signal to stop before the next batch.
        """
        while not shutdown.is_set():
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=self.interval.total_seconds())
            except TimeoutError:
                try:
                    await self._clean(shutdown)
                except SQLAlchemyError:
                    logging.getLogger(__name__).warning('MOSAIC database maintenance failed')

    async def _clean(self, shutdown: asyncio.Event) -> None:
        """
        Apply all retention rules using short, committable batches.

        :param shutdown: Signal to stop before the next batch.
        """
        now = datetime.now(UTC)
        while not shutdown.is_set():
            if not await run_in_threadpool(self._purge_batch, now):
                break

    def _purge_batch(self, now: datetime) -> bool:
        """
        Delete one batch of expired data across the MOSAIC tables.

        :param now: Fixed UTC cutoff reference for the maintenance pass.

        :return: Whether this batch removed rows.
        """
        jobs = ConversationJobRecord
        events = ConversationJobEventRecord
        finished = jobs.status.not_in(ConversationJobRepository.active_statuses)
        expired_events = (
            select(events.job_id, events.sequence)
            .join(jobs, events.job_id == jobs.job_id)
            .where(finished, jobs.updated_at <= now - self.replay_retention)
            .limit(self.batch_size)
        )
        expired_jobs = (
            select(jobs.job_id)
            .where(
                finished,
                jobs.updated_at <= now - self.job_retention,
                ~select(events.job_id).where(events.job_id == jobs.job_id).exists(),
            )
            .limit(self.batch_size)
        )
        with self._database.create_session() as session, session.begin():
            removed_events = session.execute(
                delete(events).where(tuple_(events.job_id, events.sequence).in_(expired_events))
                .execution_options(synchronize_session=False)
            )
            removed_jobs = session.execute(
                delete(jobs).where(jobs.job_id.in_(expired_jobs)).execution_options(synchronize_session=False)
            )
            return removed_events.rowcount > 0 or removed_jobs.rowcount > 0
