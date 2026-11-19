import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from mosaic import migrations
from mosaic.components.persistence.conversation_job_repository import ConversationJobRepository
from mosaic.components.persistence.conversation_metadata_repository import ConversationMetadataRepository
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.models.identity.trusted_request_context import TrustedRequestContext
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestConversationMetadataRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.configuration = MosaicDatabaseConfiguration(
            database_path=Path(self.directory.name) / 'mosaic.db'
        )
        self.database = MosaicDatabase(self.configuration)
        self.addCleanup(self.database.dispose)
        MosaicDatabaseMigrator(self.database).upgrade()
        self.context = TrustedRequestContext(
            app_name='synthetic-app', user_id='synthetic-user'
        )
        self.conversation_id = uuid4()
        self.created_at = datetime(
            2026, 1, 1, 12, 30, tzinfo=timezone(timedelta(hours=2))
        )
        with self.database.create_session() as session, session.begin():
            repository = UserAccessRepository(session)
            repository.add_user(self.context.user_id, datetime.now(UTC))
            repository.add_user('another-synthetic-user', datetime.now(UTC))

    def test_job_reservation_is_transactional_and_owner_scoped(self) -> None:
        with self.database.create_session() as session, session.begin():
            ConversationMetadataRepository(session).add(
                self.context, self.conversation_id, self.created_at
            )

        with self.database.create_session() as session:
            abandoned_id = ConversationJobRepository(session).reserve(
                self.context, self.conversation_id, 'Check a synthetic target.'
            )
            self.assertIsNotNone(abandoned_id)
            session.rollback()

        foreign = TrustedRequestContext(
            app_name=self.context.app_name, user_id='another-synthetic-user'
        )
        with self.database.create_session() as session, session.begin():
            repository = ConversationJobRepository(session)
            self.assertIsNone(repository.get(self.context, abandoned_id))
            self.assertIsNone(repository.reserve(foreign, self.conversation_id, 'Foreign request.'))
            job_id = repository.reserve(self.context, self.conversation_id, 'Check a synthetic target.')
            self.assertIsNotNone(job_id)

        with self.database.create_session() as session, session.begin():
            repository = ConversationJobRepository(session)
            job = repository.get(self.context, job_id)
            self.assertEqual(job.status, 'queued')
            self.assertEqual(job.request_text, 'Check a synthetic target.')
            self.assertIsNone(repository.get(foreign, job_id))
            self.assertIsNone(repository.reserve(self.context, self.conversation_id, 'Duplicate attempt.'))

    def test_running_job_reserves_conversation_until_stop_is_confirmed(self) -> None:
        with self.database.create_session() as session, session.begin():
            ConversationMetadataRepository(session).add(
                self.context, self.conversation_id, self.created_at
            )
            repository = ConversationJobRepository(session)
            job_id = repository.reserve(self.context, self.conversation_id, 'Read a synthetic status.')

        with self.database.create_session() as session, session.begin():
            repository = ConversationJobRepository(session)
            self.assertTrue(repository.claim(self.context, job_id))

        with self.database.create_session() as session, session.begin():
            repository = ConversationJobRepository(session)
            self.assertFalse(repository.claim(self.context, job_id))
            self.assertTrue(repository.request_stop(self.context, job_id))
            self.assertEqual(repository.get(self.context, job_id).status, 'stopping')
            self.assertIsNone(repository.reserve(self.context, self.conversation_id, 'Too early.'))
            self.assertFalse(repository.finish(
                self.context, job_id, 'succeeded', can_continue=True, result_text='Late answer.',
            ))

        with self.database.create_session() as session, session.begin():
            repository = ConversationJobRepository(session)
            self.assertTrue(repository.finish(self.context, job_id, 'cancelled', can_continue=True))
            self.assertEqual(repository.get(self.context, job_id).status, 'cancelled')
            self.assertIsNone(repository.get(self.context, job_id).result_text)
            self.assertIsNotNone(repository.reserve(self.context, self.conversation_id, 'Follow-up.'))
            self.assertFalse(repository.finish(self.context, job_id, 'cancelled', can_continue=True))
            self.assertIsNone(repository.reserve(self.context, self.conversation_id, 'Still busy.'))

    def test_schema_contains_metadata_only_and_owner_index(self) -> None:
        inspector = inspect(self.database.engine)
        self.assertEqual(
            {
                column['name']
                for column in inspector.get_columns('conversation_metadata')
            },
            {'conversation_id', 'app_name', 'user_id', 'created_at', 'invocation_in_progress', 'is_interrupted'},
        )
        self.assertEqual(
            inspector.get_pk_constraint('conversation_metadata')['constrained_columns'],
            ['conversation_id'],
        )
        self.assertEqual(
            inspector.get_indexes('conversation_metadata')[0]['column_names'],
            ['app_name', 'user_id'],
        )
        self.assertEqual(
            inspector.get_foreign_keys('conversation_metadata')[0]['referred_table'],
            'users',
        )

    def test_original_creation_time_survives_database_restart_in_utc(self) -> None:
        with self.database.create_session() as session, session.begin():
            ConversationMetadataRepository(session).add(
                self.context, self.conversation_id, self.created_at
            )
        self.database.dispose()
        restarted = MosaicDatabase(self.configuration)
        try:
            with restarted.create_session() as session:
                created_at = ConversationMetadataRepository(session).get_created_at(
                    self.context, self.conversation_id
                )
                self.assertEqual(created_at, self.created_at.astimezone(UTC))
                self.assertEqual(created_at.tzinfo, UTC)
        finally:
            restarted.dispose()

    def test_foreign_and_missing_ids_return_identical_absence(self) -> None:
        with self.database.create_session() as session, session.begin():
            repository = ConversationMetadataRepository(session)
            repository.add(self.context, self.conversation_id, self.created_at)
            for context in (
                TrustedRequestContext(
                    app_name='synthetic-app', user_id='another-synthetic-user'
                ),
                TrustedRequestContext(app_name='another-app', user_id='synthetic-user'),
            ):
                self.assertIsNone(
                    repository.get_created_at(context, self.conversation_id)
                )
            self.assertIsNone(repository.get_created_at(self.context, uuid4()))

    def test_duplicate_id_cannot_replace_owner_or_original_timestamp(self) -> None:
        with self.database.create_session() as session, session.begin():
            ConversationMetadataRepository(session).add(
                self.context, self.conversation_id, self.created_at
            )
        with (
            self.assertRaises(IntegrityError),
            self.database.create_session() as session,
            session.begin(),
        ):
            ConversationMetadataRepository(session).add(
                TrustedRequestContext(
                    app_name='synthetic-app', user_id='another-synthetic-user'
                ),
                self.conversation_id,
                self.created_at + timedelta(days=1),
            )
        with self.database.create_session() as session:
            self.assertEqual(
                ConversationMetadataRepository(session).get_created_at(
                    self.context, self.conversation_id
                ),
                self.created_at,
            )

    def test_invalid_id_naive_timestamp_and_missing_user_are_rejected(self) -> None:
        with self.database.create_session() as session:
            repository = ConversationMetadataRepository(session)
            with self.assertRaises(TypeError):
                repository.add(self.context, 'unvalidated-id', self.created_at)
            with self.assertRaises(TypeError):
                repository.get_created_at(self.context, 'unvalidated-id')
            with self.assertRaises(ValueError):
                repository.add(
                    self.context,
                    self.conversation_id,
                    self.created_at.replace(tzinfo=None),
                )
            with self.assertRaises(ValueError):
                repository.add(
                    TrustedRequestContext(
                        app_name='synthetic-app', user_id='missing-user'
                    ),
                    self.conversation_id,
                    self.created_at,
                )

    def test_reservation_is_conditional_and_interruption_is_permanent(self) -> None:
        with self.database.create_session() as session, session.begin():
            repository = ConversationMetadataRepository(session)
            repository.add(self.context, self.conversation_id, self.created_at)
            self.assertEqual(repository.get_availability(self.context, self.conversation_id), (True, False))
            self.assertTrue(repository.begin_invocation(self.context, self.conversation_id))
        with self.database.create_session() as session, session.begin():
            repository = ConversationMetadataRepository(session)
            self.assertFalse(repository.begin_invocation(self.context, self.conversation_id))
            self.assertEqual(repository.get_availability(self.context, self.conversation_id), (False, False))
            repository.finish_invocation(self.context, self.conversation_id, is_interrupted=True)
            self.assertEqual(repository.get_availability(self.context, self.conversation_id), (False, True))
            self.assertFalse(repository.begin_invocation(self.context, self.conversation_id))
            repository.finish_invocation(self.context, self.conversation_id, is_interrupted=False)
            self.assertEqual(repository.get_availability(self.context, self.conversation_id), (False, True))

    def test_foreign_owner_cannot_reserve_or_finalise(self) -> None:
        foreign = TrustedRequestContext(app_name=self.context.app_name, user_id='another-synthetic-user')
        with self.database.create_session() as session, session.begin():
            repository = ConversationMetadataRepository(session)
            repository.add(self.context, self.conversation_id, self.created_at)
            self.assertIsNone(repository.get_availability(foreign, self.conversation_id))
            self.assertFalse(repository.begin_invocation(foreign, self.conversation_id))
            self.assertTrue(repository.begin_invocation(self.context, self.conversation_id))
            repository.finish_invocation(foreign, self.conversation_id, is_interrupted=False)
            self.assertEqual(repository.get_availability(self.context, self.conversation_id), (False, False))
            repository.finish_invocation(self.context, self.conversation_id, is_interrupted=False)
            self.assertEqual(repository.get_availability(self.context, self.conversation_id), (True, False))

    def test_existing_conversation_upgrade_preserves_metadata_and_boolean_defaults(self) -> None:
        with self.database.create_session() as session, session.begin():
            ConversationMetadataRepository(session).add(self.context, self.conversation_id, self.created_at)
        configuration = Config()
        configuration.set_main_option('script_location', str(Path(migrations.__file__).parent))
        with self.database.engine.begin() as connection:
            configuration.attributes['connection'] = connection
            command.downgrade(configuration, '0004_conversation_metadata')
        self.assertNotIn('is_interrupted', {column['name'] for column in inspect(self.database.engine).get_columns('conversation_metadata')})
        MosaicDatabaseMigrator(self.database).upgrade()
        with self.database.create_session() as session:
            repository = ConversationMetadataRepository(session)
            self.assertEqual(repository.get_created_at(self.context, self.conversation_id), self.created_at.astimezone(UTC))
            self.assertEqual(repository.get_availability(self.context, self.conversation_id), (True, False))

    def test_unfinalised_reservation_survives_restart_without_being_reclaimed(self) -> None:
        with self.database.create_session() as session, session.begin():
            repository = ConversationMetadataRepository(session)
            repository.add(self.context, self.conversation_id, self.created_at)
            self.assertTrue(repository.begin_invocation(self.context, self.conversation_id))
        self.database.dispose()
        restarted = MosaicDatabase(self.configuration)
        try:
            with restarted.create_session() as session, session.begin():
                repository = ConversationMetadataRepository(session)
                self.assertEqual(repository.get_availability(self.context, self.conversation_id), (False, False))
                self.assertFalse(repository.begin_invocation(self.context, self.conversation_id))
        finally:
            restarted.dispose()

    def test_caller_rollback_does_not_persist_metadata(self) -> None:
        with self.database.create_session() as session:
            ConversationMetadataRepository(session).add(
                self.context, self.conversation_id, self.created_at
            )
            session.rollback()
        with self.database.create_session() as session:
            self.assertIsNone(
                ConversationMetadataRepository(session).get_created_at(
                    self.context, self.conversation_id
                )
            )

    def test_upgrade_from_existing_schema_preserves_users_and_tokens(self) -> None:
        old_configuration = MosaicDatabaseConfiguration(
            database_path=Path(self.directory.name) / 'existing' / 'mosaic.db'
        )
        old_database = MosaicDatabase(old_configuration)
        try:
            configuration = Config()
            configuration.set_main_option(
                'script_location', str(Path(migrations.__file__).parent)
            )
            with old_database.engine.begin() as connection:
                configuration.attributes['connection'] = connection
                command.upgrade(configuration, '0003_workspace_skills')
            with old_database.create_session() as session, session.begin():
                repository = UserAccessRepository(session)
                repository.add_user('existing-synthetic-user', datetime.now(UTC))
                repository.add_access_token(
                    str(uuid4()),
                    'existing-synthetic-user',
                    'synthetic-test-token',
                    datetime.now(UTC),
                )
            MosaicDatabaseMigrator(old_database).upgrade()
            with old_database.create_session() as session:
                user = UserAccessRepository(session).resolve_enabled_user(
                    'synthetic-test-token'
                )
                self.assertEqual(user.user_id, 'existing-synthetic-user')
            self.assertIn(
                'conversation_metadata', inspect(old_database.engine).get_table_names()
            )
        finally:
            old_database.dispose()
