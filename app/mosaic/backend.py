"""MOSAIC-owned process boundary around the ADA backend application."""

from collections.abc import Callable
from typing import Any

from .utilities.environment_configuration_reader import (
    EnvironmentConfigurationReader,
)

DEFAULT_HOST = '0.0.0.0'
DEFAULT_PORT = 8000
UVICORN_APPLICATION_FACTORY = 'mosaic.backend:create_application'

ApplicationFactory = Callable[[], Any]
ApplicationConfigurer = Callable[[Any], None]


def configure_outer_application(application: Any) -> None:
    """Register MOSAIC-owned outer controls after ADA creates its app.

    Authentication middleware and ``/api/v1`` routers will be registered at
    this boundary by their owning stories. Keeping this hook separate avoids
    modifying ADA or depending on its internal application-stack classes.

    Args:
        application: Application returned by ADA's public app factory.
    """


def create_application(
    *,
    ada_app_factory: ApplicationFactory | None = None,
    application_configurer: ApplicationConfigurer | None = None,
) -> Any:
    """Create ADA's application before applying MOSAIC-owned outer controls.

    Imports of the opinionated framework remain lazy so unit tests and tooling
    can inspect MOSAIC without requiring the target ADA runtime.

    Args:
        ada_app_factory: Optional factory override used by isolated tests.
        application_configurer: Optional outer-boundary configuration hook.

    Returns:
        The configured ADA ASGI application.
    """
    if ada_app_factory is None:
        from ada_sdk.api.base_api import create_app

        ada_app_factory = create_app
    if application_configurer is None:
        application_configurer = configure_outer_application

    application = ada_app_factory()
    application_configurer(application)
    return application


def main(*, uvicorn_runner: Callable[..., Any] | None = None) -> None:
    """Start the backend using Cloud Run's port or a local default."""
    if uvicorn_runner is None:
        import uvicorn

        uvicorn_runner = uvicorn.run

    port = EnvironmentConfigurationReader.read_positive_integer(
        'PORT',
        DEFAULT_PORT,
    )
    uvicorn_runner(
        UVICORN_APPLICATION_FACTORY,
        host=DEFAULT_HOST,
        port=port,
        factory=True,
    )


if __name__ == '__main__':
    main()
