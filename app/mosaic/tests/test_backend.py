import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from mosaic.backend import Backend
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
        database = database_type.return_value
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
        database.dispose.side_effect = dispose_database
        application.add_api_route.side_effect = register_readiness

        result = Backend.create_application(
            ada_app_factory=create_ada_application,
            application_configurer=configure_application,
            database_configuration=configuration,
        )

        self.assertIs(result, application)
        database_type.assert_called_once_with(configuration)
        migrator_type.assert_called_once_with(database)
        self.assertEqual(
            events,
            [
                'database_upgraded',
                'database_disposed',
                'ada_app_created',
                'readiness_registered',
                'outer_application_configured',
            ],
        )
        application.add_api_route.assert_called_once_with(
            '/ready',
            Backend._readiness,
            methods=['GET'],
            include_in_schema=False,
        )

    def test_readiness_response_is_stable(self) -> None:
        self.assertEqual(Backend._readiness(), {'status': 'ready'})

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
                users_response = client.get('/api/v1/admin/users')
                skills_response = client.get(
                    '/api/v1/admin/workspaces/pilot-user/skills'
                )

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
