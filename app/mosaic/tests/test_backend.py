import unittest
from unittest.mock import Mock

from mosaic.backend import Backend
from mosaic.models.backend_configuration import BackendConfiguration


class TestBackend(unittest.TestCase):
    def test_outer_configuration_runs_after_ada_app_creation(self) -> None:
        events: list[str] = []
        application = object()

        def create_ada_application() -> object:
            events.append('ada_app_created')
            return application

        def configure_application(created_application: object) -> None:
            self.assertIs(created_application, application)
            events.append('outer_application_configured')

        result = Backend.create_application(
            ada_app_factory=create_ada_application,
            application_configurer=configure_application,
        )

        self.assertIs(result, application)
        self.assertEqual(
            events,
            ['ada_app_created', 'outer_application_configured'],
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
