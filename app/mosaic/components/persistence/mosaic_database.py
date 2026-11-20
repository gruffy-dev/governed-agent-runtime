"""SQLAlchemy engine and session ownership for the MOSAIC database."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from portalocker import AlreadyLocked, Lock
from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ...models.mosaic_database_configuration import MosaicDatabaseConfiguration


class MosaicDatabase:
    """Own the engine and session factory for one MOSAIC SQLite file."""

    def __init__(self, configuration: MosaicDatabaseConfiguration) -> None:
        """Create the engine after preparing its configured storage path.

        Args:
            configuration: Validated SQLite path and durability settings.
        """
        self._configuration = configuration
        database_path = configuration.prepare_database_path()
        self._engine = create_engine(
            URL.create(
                drivername='sqlite+pysqlite',
                database=str(database_path),
            ),
            connect_args={
                'check_same_thread': False,
                'timeout': configuration.busy_timeout_seconds,
            },
        )
        event.listen(
            self._engine,
            'connect',
            self._configure_sqlite_connection,
        )
        self._session_factory = sessionmaker(
            bind=self._engine,
            autoflush=False,
            expire_on_commit=False,
        )

    @property
    def engine(self) -> Engine:
        """Return the owned SQLAlchemy engine.

        Returns:
            Engine connected exclusively to the configured MOSAIC database.
        """
        return self._engine

    def create_session(self) -> Session:
        """Create one unit-of-work session.

        Returns:
            New SQLAlchemy session bound to the MOSAIC engine.
        """
        return self._session_factory()

    @contextmanager
    def exclusive_job_runtime(self) -> Iterator[None]:
        """
        Hold a process lock for the SQLite pilot runtime and its restart cleanup.

        :return: Context that retains ownership until private execution shuts down.

        :raises RuntimeError: If another backend already owns this database.
        """
        path = self._configuration.resolved_database_path
        lock_path = path.with_name(f'{path.name}.jobs.lock')
        lock = Lock(lock_path, mode='a', timeout=0, fail_when_locked=True)
        try:
            lock.acquire()
        except AlreadyLocked:
            raise RuntimeError('Another backend already owns this SQLite job database.') from None
        try:
            yield
        finally:
            lock.release()

    def dispose(self) -> None:
        """Release pooled SQLite connections owned by the engine."""
        self._engine.dispose()

    def _configure_sqlite_connection(
        self,
        database_connection: sqlite3.Connection,
        _connection_record: Any,
    ) -> None:
        """Apply required durability settings to every SQLite connection.

        Args:
            database_connection: Newly opened Python SQLite connection.
            _connection_record: SQLAlchemy connection-pool record.
        """
        cursor = database_connection.cursor()
        try:
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.execute(
                'PRAGMA journal_mode='
                f'{self._configuration.journal_mode}'
            )
            cursor.execute(
                'PRAGMA synchronous='
                f'{self._configuration.synchronous_mode}'
            )
            cursor.execute(
                'PRAGMA busy_timeout='
                f'{self._configuration.busy_timeout_seconds * 1000}'
            )
        finally:
            cursor.close()
