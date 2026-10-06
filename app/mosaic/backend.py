"""MOSAIC-owned process boundary around the ADA backend application."""

from collections.abc import Callable
from typing import Any

from .models.backend_configuration import BackendConfiguration


class Backend:
    """Create and run the ADA application through an owned stable boundary."""

    @staticmethod
    def create_application(
        *,
        ada_app_factory: Callable[[], Any] | None = None,
        application_configurer: Callable[[Any], None] | None = None,
    ) -> Any:
        """Create ADA's app before applying MOSAIC-owned outer controls.

        Imports of the opinionated framework remain lazy so unit tests and
        tooling can inspect MOSAIC without requiring the target ADA runtime.

        Args:
            ada_app_factory: Optional factory override used by isolated tests.
            application_configurer: Optional outer-boundary configuration
                hook.

        Returns:
            The configured ADA ASGI application.
        """
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
