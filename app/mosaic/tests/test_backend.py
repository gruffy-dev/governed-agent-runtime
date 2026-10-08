import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mosaic.backend import Backend
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.models.backend_configuration import BackendConfiguration
from mosaic.models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestBackend(unittest.TestCase):
    @patch('mosaic.backend.MosaicDatabaseMigrator')
    @patch('mosaic.backend.MosaicDatabase')
    def test_migration_precedes_ada_app_creation_and_configuration(
        self,
        database_type: Mock,
        migrator_type: Mock,
    ) -> None:
        events: list[str] = []
        application = Mock()
        migration_database = Mock()
        runtime_database = Mock()
        database_type.side_effect = [
            migration_database,
            runtime_database,
        ]
        migrator = migrator_type.return_value
        configuration = MosaicDatabaseConfiguration()

        def upgrade_database() -> None:
            events.append('database_upgraded')

        def dispose_database() -> None:
            events.append('database_disposed')

        def create_ada_application() -> object:
            events.append('ada_app_created')
            return application

        def register_readiness(*_args: object, **_kwargs: object) -> None:
            events.append('readiness_registered')

        def configure_application(created_application: object) -> None:
            self.assertIs(created_application, application)
            events.append('outer_application_configured')

        migrator.upgrade.side_effect = upgrade_database
        migration_database.dispose.side_effect = dispose_database
        application.add_api_route.side_effect = register_readiness
        application.add_middleware.side_effect = (
            lambda *_args, **_kwargs: events.append(
                'authentication_registered'
            )
        )

        result = Backend.create_application(
            ada_app_factory=create_ada_application,
            application_configurer=configure_application,
            database_configuration=configuration,
        )

        self.assertIs(result, application)
        self.assertEqual(database_type.call_count, 2)
        database_type.assert_any_call(configuration)
        migrator_type.assert_called_once_with(migration_database)
        self.assertEqual(
            events,
            [
                'database_upgraded',
                'database_disposed',
                'ada_app_created',
                'readiness_registered',
                'outer_application_configured',
                'authentication_registered',
            ],
        )
        migration_database.dispose.assert_called_once_with()
        runtime_database.dispose.assert_not_called()
        application.add_api_route.assert_called_once_with(
            '/ready',
            Backend._readiness,
            methods=['GET'],
            include_in_schema=False,
        )

    def test_readiness_response_is_stable(self) -> None:
        self.assertEqual(Backend._readiness(), {'status': 'ready'})

    def test_persisted_bearer_token_establishes_trusted_context(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            database_configuration = MosaicDatabaseConfiguration(
                database_path=Path(temporary_directory) / 'mosaic.db'
            )
            backend_databases: list[MosaicDatabase] = []

            def create_backend_database(
                configuration: MosaicDatabaseConfiguration,
            ) -> MosaicDatabase:
                database = MosaicDatabase(configuration)
                backend_databases.append(database)
                return database

            def configure_application(application: FastAPI) -> None:
                async def protected_route(
                    request: Request,
                ) -> dict[str, str]:
                    return {
                        'user_id': (
                            request.state.trusted_user_context.user_id
                        )
                    }

                application.add_api_route(
                    '/protected',
                    protected_route,
                    methods=['GET'],
                )

            with patch(
                'mosaic.backend.MosaicDatabase',
                side_effect=create_backend_database,
            ):
                application = Backend.create_application(
                    ada_app_factory=FastAPI,
                    application_configurer=configure_application,
                    database_configuration=database_configuration,
                )
            database = MosaicDatabase(database_configuration)
            created_at = datetime.now(UTC)
            try:
                with (
                    database.create_session() as session,
                    session.begin(),
                ):
                    repository = UserAccessRepository(session)
                    repository.add_user('authenticated-user', created_at)
                    repository.add_access_token(
                        '00000000-0000-4000-8000-000000000023',
                        'authenticated-user',
                        'persisted-valid-token',
                        created_at,
                    )

                with TestClient(application) as client:
                    missing_response = client.get('/protected')
                    valid_response = client.get(
                        '/protected',
                        headers={
                            'Authorization': (
                                'Bearer persisted-valid-token'
                            )
                        },
                    )
            finally:
                database.dispose()
                for backend_database in backend_databases:
                    backend_database.dispose()

        self.assertEqual(missing_response.status_code, 401)
        self.assertEqual(valid_response.status_code, 200)
        self.assertEqual(
            valid_response.json(),
            {'user_id': 'authenticated-user'},
        )

    @patch('mosaic.backend.MosaicDatabaseMigrator')
    @patch('mosaic.backend.MosaicDatabase')
    def test_migration_failure_prevents_ada_app_creation(
        self,
        database_type: Mock,
        migrator_type: Mock,
    ) -> None:
        ada_app_factory = Mock()
        database = database_type.return_value
        migrator_type.return_value.upgrade.side_effect = RuntimeError(
            'migration failed'
        )

        with self.assertRaisesRegex(RuntimeError, 'migration failed'):
            Backend.create_application(
                ada_app_factory=ada_app_factory,
                database_configuration=MosaicDatabaseConfiguration(),
            )

        ada_app_factory.assert_not_called()
        database.dispose.assert_called_once_with()

    @patch(
        'mosaic.components.identity.pilot_administration_api.'
        'PilotAdministrationApi'
    )
    @patch(
        'mosaic.components.identity.pilot_user_administration_service.'
        'PilotUserAdministrationService'
    )
    @patch('mosaic.backend.MosaicDatabaseMigrator')
    @patch('mosaic.backend.MosaicDatabase')
    def test_enabled_pilot_administration_is_registered(
        self,
        database_type: Mock,
        migrator_type: Mock,
        service_type: Mock,
        api_type: Mock,
    ) -> None:
        application = Mock()
        migration_database = Mock()
        administration_database = Mock()
        database_type.side_effect = [
            migration_database,
            administration_database,
        ]
        database_configuration = MosaicDatabaseConfiguration()
        administration_configuration = PilotAdministrationConfiguration(
            enabled=True,
            administrator_secret=SecretStr('a' * 32),
        )
        catalogue_snapshot = Mock()

        result = Backend.create_application(
            ada_app_factory=lambda: application,
            database_configuration=database_configuration,
            pilot_administration_configuration=(
                administration_configuration
            ),
            skill_catalogue_snapshot=catalogue_snapshot,
        )

        self.assertIs(result, application)
        self.assertEqual(database_type.call_count, 2)
        migrator_type.assert_called_once_with(migration_database)
        migration_database.dispose.assert_called_once_with()
        service_type.assert_called_once_with(
            administration_database,
            catalogue_snapshot,
        )
        api_type.assert_called_once_with(
            administration_configuration,
            service_type.return_value,
        )
        api_type.return_value.register_routes.assert_called_once_with(
            application
        )
        application.add_middleware.assert_called_once()
        administration_database.dispose.assert_not_called()

    def test_enabled_pilot_administration_supports_fastapi_application(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            application = Backend.create_application(
                ada_app_factory=FastAPI,
                database_configuration=MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                ),
                pilot_administration_configuration=(
                    PilotAdministrationConfiguration(
                        enabled=True,
                        administrator_secret=SecretStr('a' * 32),
                    )
                ),
                skill_catalogue_snapshot=Mock(),
            )
            with TestClient(application) as client:
                readiness_response = client.get('/ready')
                protected_response = client.get('/run')
                users_response = client.get('/api/v1/admin/users')
                skills_response = client.get(
                    '/api/v1/admin/workspaces/pilot-user/skills'
                )

        self.assertEqual(readiness_response.status_code, 200)
        self.assertEqual(protected_response.status_code, 401)
        self.assertEqual(users_response.status_code, 403)
        self.assertEqual(skills_response.status_code, 403)

    def test_startup_uses_validated_configuration(self) -> None:
        runner = Mock()
        configuration = BackendConfiguration(
            host='127.0.0.2',
            port=9090,
        )

        Backend.run(
            configuration=configuration,
            uvicorn_runner=runner,
        )

        runner.assert_called_once_with(
            Backend.create_application,
            host='127.0.0.2',
            port=9090,
            factory=True,
        )
