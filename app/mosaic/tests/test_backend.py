"""Tests for the MOSAIC-owned ADA backend process boundary."""

import unittest
from unittest.mock import Mock, patch

from mosaic.backend import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    UVICORN_APPLICATION_FACTORY,
    create_application,
    main,
)


class TestBackend(unittest.TestCase):
    """Verify startup remains thin, ordered and environment driven."""

    def test_outer_configuration_runs_after_ada_app_creation(self) -> None:
        """MOSAIC controls are registered around the completed ADA app."""
        events: list[str] = []
        application = object()

        def create_ada_application() -> object:
            events.append('ada_app_created')
            return application

        def configure_application(created_application: object) -> None:
            self.assertIs(created_application, application)
            events.append('outer_application_configured')

        result = create_application(
            ada_app_factory=create_ada_application,
            application_configurer=configure_application,
        )

        self.assertIs(result, application)
        self.assertEqual(
            events,
            ['ada_app_created', 'outer_application_configured'],
        )

    def test_local_startup_uses_uvicorn_factory_and_default_port(self) -> None:
        """Local execution uses the owned factory without eager ADA imports."""
        runner = Mock()

        with patch.dict('os.environ', {}, clear=True):
            main(uvicorn_runner=runner)

        runner.assert_called_once_with(
            UVICORN_APPLICATION_FACTORY,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            factory=True,
        )

    def test_cloud_run_port_is_forwarded_to_uvicorn(self) -> None:
        """The deployment-provided port replaces the local default."""
        runner = Mock()

        with patch.dict('os.environ', {'PORT': '9090'}, clear=True):
            main(uvicorn_runner=runner)

        runner.assert_called_once_with(
            UVICORN_APPLICATION_FACTORY,
            host=DEFAULT_HOST,
            port=9090,
            factory=True,
        )

    def test_invalid_cloud_run_port_fails_before_server_start(self) -> None:
        """Malformed trusted configuration cannot start a partial service."""
        runner = Mock()

        with (
            patch.dict('os.environ', {'PORT': 'invalid'}, clear=True),
            self.assertRaises(ValueError),
        ):
            main(uvicorn_runner=runner)

        runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
