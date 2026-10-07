import unittest
from unittest.mock import Mock, patch

from mosaic.backend import Backend
from mosaic.models.backend_configuration import BackendConfiguration
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
        application = object()
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

        def configure_application(created_application: object) -> None:
            self.assertIs(created_application, application)
            events.append('outer_application_configured')

        migrator.upgrade.side_effect = upgrade_database
        database.dispose.side_effect = dispose_database

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
                'outer_application_configured',
            ],
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
