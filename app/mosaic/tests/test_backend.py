import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from mosaic.models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestBackend(unittest.TestCase):
    @patch('mosaic.backend.MosaicDatabaseMigrator')
    @patch('mosaic.backend.MosaicDatabase')
    def test_unchecked_public_wrapper_fails_composition_and_disposes_database(
        self,
        database_type: Mock,
        migrator_type: Mock,
    ) -> None:
        migration_database = Mock()
        runtime_database = Mock()
        database_type.side_effect = [migration_database, runtime_database]

        def configure(application: FastAPI) -> None:
            async def unchecked() -> dict[str, str]:
                return {}

            application.add_api_route('/api/v1/unchecked', unchecked)

        with self.assertRaisesRegex(RuntimeError, 'trusted identity dependency'):
            Backend.create_application(
                ada_app_factory=FastAPI,
                application_configurer=configure,
                pilot_administration_configuration=PilotAdministrationConfiguration(
                    enabled=False
                ),
            )
        runtime_database.dispose.assert_called_once_with()

    def test_routes_added_after_composition_are_checked_before_ada_startup(
        self,
    ) -> None:
        started: list[bool] = []

        @asynccontextmanager
        async def private_lifespan(application: FastAPI) -> AsyncIterator[None]:
            started.append(True)
            yield

        with TemporaryDirectory() as directory:
            application = Backend.create_application(
                ada_app_factory=lambda: FastAPI(lifespan=private_lifespan),
                database_configuration=MosaicDatabaseConfiguration(
                    database_path=Path(directory) / 'mosaic.db'
                ),
                pilot_administration_configuration=PilotAdministrationConfiguration(
                    enabled=False
                ),
            )

            async def unchecked() -> dict[str, str]:
                return {}

            application.add_api_route('/api/v1/unchecked', unchecked)
            with (
                self.assertRaisesRegex(RuntimeError, 'trusted identity dependency'),
                TestClient(application),
            ):
                self.fail('Unchecked wrapper must prevent startup.')
        self.assertEqual(started, [])

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

        def configure_application(created_application: object) -> None:
            self.assertIsInstance(created_application, FastAPI)
            self.assertIsNot(created_application, application)
            events.append('outer_application_configured')

        migrator.upgrade.side_effect = upgrade_database
        migration_database.dispose.side_effect = dispose_database

        result = Backend.create_application(
            ada_app_factory=create_ada_application,
            application_configurer=configure_application,
            database_configuration=configuration,
        )

        self.assertIsNot(result, application)
        self.assertEqual(database_type.call_count, 2)
        database_type.assert_any_call(configuration)
        migrator_type.assert_called_once_with(migration_database)
        self.assertEqual(
            events,
            [
                'database_upgraded',
                'database_disposed',
                'ada_app_created',
                'outer_application_configured',
            ],
        )
        migration_database.dispose.assert_called_once_with()
        runtime_database.dispose.assert_not_called()
        application.add_api_route.assert_not_called()
        application.add_middleware.assert_not_called()
        self.assertIn(
            '/ready', [getattr(route, 'path', None) for route in result.routes]
        )
        self.assertIn(
            '/health', [getattr(route, 'path', None) for route in result.routes]
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
                    return {'user_id': (request.state.trusted_user_context.user_id)}

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
                    pilot_authentication_configuration=(
                        PilotAuthenticationConfiguration(
                            mode='local',
                            secure_cookie=False,
                        )
                    ),
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
                        headers={'Authorization': ('Bearer persisted-valid-token')},
                    )
                    sign_in_response = client.post(
                        '/api/v1/auth/token',
                        json={'token': 'persisted-valid-token'},
                    )
                    cookie_response = client.get('/protected')
                    contract_response = client.get('/api/v1/openapi.json')
                    with (
                        database.create_session() as session,
                        session.begin(),
                    ):
                        UserAccessRepository(session).disable_user(
                            'authenticated-user',
                            created_at,
                        )
                    disabled_cookie_response = client.get('/protected')
                    logout_response = client.post('/api/v1/auth/logout')
                    after_logout_response = client.get('/protected')
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
        self.assertEqual(sign_in_response.status_code, 204)
        self.assertNotIn('Secure', sign_in_response.headers['Set-Cookie'])
        self.assertEqual(cookie_response.status_code, 200)
        self.assertEqual(contract_response.status_code, 200)
        self.assertEqual(contract_response.json()['info']['version'], '1.0.0')
        self.assertNotIn('/protected', contract_response.json()['paths'])
        self.assertEqual(
            cookie_response.json(),
            {'user_id': 'authenticated-user'},
        )
        self.assertEqual(disabled_cookie_response.status_code, 401)
        self.assertEqual(logout_response.status_code, 204)
        self.assertEqual(after_logout_response.status_code, 401)
        for response in (
            missing_response,
            disabled_cookie_response,
            after_logout_response,
        ):
            self.assertEqual(response.json()['error_code'], 'unauthorized')
            self.assertEqual(
                response.json()['correlation_id'],
                response.headers['X-Correlation-ID'],
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

    @patch('mosaic.components.identity.pilot_administration_api.PilotAdministrationApi')
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
            pilot_administration_configuration=(administration_configuration),
            skill_catalogue_snapshot=catalogue_snapshot,
        )

        self.assertIsNot(result, application)
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
        api_type.return_value.register_routes.assert_called_once_with(result)
        administration_database.dispose.assert_not_called()

    @patch('mosaic.backend.MosaicDatabaseMigrator')
    @patch('mosaic.backend.MosaicDatabase')
    def test_private_routes_are_unmounted_and_lifecycle_owns_resources(
        self,
        database_type: Mock,
        migrator_type: Mock,
    ) -> None:
        events: list[str] = []

        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            events.append('startup')
            try:
                yield
            finally:
                events.append('shutdown')

        private_application = FastAPI(lifespan=lifespan)

        @private_application.get('/apps/synthetic/users/another-user/sessions')
        async def sessions() -> list[object]:
            return []

        application = Backend.create_application(
            ada_app_factory=lambda: private_application
        )
        with patch(
            'mosaic.components.identity.pilot_bearer_authenticator.PilotBearerAuthenticator.authenticate',
        ) as authenticate:
            from mosaic.models.identity.trusted_user_context import TrustedUserContext

            authenticate.return_value = TrustedUserContext(user_id='synthetic-user')
            with TestClient(application) as client:
                self.assertEqual(events, ['startup'])
                self.assertTrue(hasattr(application.state, 'ada_transport'))
                self.assertEqual(client.get('/health').json(), {'status': 'ok'})
                self.assertEqual(client.get('/ready').json(), {'status': 'ready'})
                for path in (
                    '/apps/synthetic/users/another-user/sessions',
                    '/docs',
                    '/openapi.json',
                    '/run_sse',
                ):
                    response = client.get(
                        path, headers={'Authorization': 'Bearer synthetic-token'}
                    )
                    self.assertEqual(response.status_code, 404)
        self.assertEqual(events, ['startup', 'shutdown'])
        self.assertFalse(hasattr(application.state, 'ada_transport'))
        self.assertEqual(database_type.return_value.dispose.call_count, 2)

    @patch('mosaic.backend.MosaicDatabaseMigrator')
    @patch('mosaic.backend.MosaicDatabase')
    def test_private_startup_failure_closes_runtime_database(
        self,
        database_type: Mock,
        migrator_type: Mock,
    ) -> None:
        @asynccontextmanager
        async def lifespan(app: FastAPI) -> AsyncIterator[None]:
            raise RuntimeError('synthetic-private-diagnostic')
            yield

        from mosaic.components.ada.ada_application_error import AdaApplicationError

        application = Backend.create_application(
            ada_app_factory=lambda: FastAPI(lifespan=lifespan)
        )
        with self.assertRaises(AdaApplicationError) as caught, TestClient(application):
            self.fail('Failed startup should prevent serving requests')
        self.assertNotIn('synthetic-private-diagnostic', str(caught.exception))
        self.assertEqual(database_type.return_value.dispose.call_count, 2)

    def test_enabled_pilot_administration_supports_fastapi_application(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            application = Backend.create_application(
                ada_app_factory=FastAPI,
                database_configuration=MosaicDatabaseConfiguration(
                    database_path=(Path(temporary_directory) / 'mosaic.db')
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
        for response in (users_response, skills_response):
            self.assertEqual(response.json()['error_code'], 'forbidden')
            self.assertEqual(
                response.json()['correlation_id'],
                response.headers['X-Correlation-ID'],
            )

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
