"""MOSAIC-owned process boundary around the ADA backend application."""

from collections.abc import Callable
from typing import Any

from .components.persistence.mosaic_database import MosaicDatabase
from .components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from .models.backend_configuration import BackendConfiguration
from .models.mosaic_database_configuration import MosaicDatabaseConfiguration


class Backend:
    """Create and run the ADA application through an owned stable boundary."""

    @staticmethod
    def create_application(
        *,
        ada_app_factory: Callable[[], Any] | None = None,
        application_configurer: Callable[[Any], None] | None = None,
        database_configuration: MosaicDatabaseConfiguration | None = None,
    ) -> Any:
        """Upgrade MOSAIC storage before creating and configuring ADA's app.

        Imports of the opinionated framework remain lazy so unit tests and
        tooling can inspect MOSAIC without requiring the target ADA runtime.

        Args:
            ada_app_factory: Optional factory override used by isolated tests.
            application_configurer: Optional outer-boundary configuration
                hook.
            database_configuration: Optional validated MOSAIC database
                configuration.

        Returns:
            The configured ADA ASGI application.

        Raises:
            Exception: Propagates database preparation or migration failures.
        """
        if database_configuration is None:
            database_configuration = MosaicDatabaseConfiguration()
        database = MosaicDatabase(database_configuration)
        try:
            MosaicDatabaseMigrator(database).upgrade()
        finally:
            database.dispose()

        if ada_app_factory is None:
            from ada_sdk.api.base_api import create_app

            ada_app_factory = create_app

        application = ada_app_factory()
        if application_configurer is not None:
            application_configurer(application)
        return application

    @staticmethod
    def run(
        *,
        configuration: BackendConfiguration | None = None,
        uvicorn_runner: Callable[..., Any] | None = None,
    ) -> None:
        """Start the backend using validated deployment configuration.

        Args:
            configuration: Optional validated configuration override.
            uvicorn_runner: Optional server runner used by isolated tests.
        """
        if configuration is None:
            configuration = BackendConfiguration()
        if uvicorn_runner is None:
            import uvicorn

            uvicorn_runner = uvicorn.run

        uvicorn_runner(
            Backend.create_application,
            host=configuration.host,
            port=configuration.port,
            factory=True,
        )
