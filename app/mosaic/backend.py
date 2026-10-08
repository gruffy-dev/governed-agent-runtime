from collections.abc import Callable
from typing import Any

from .components.persistence.mosaic_database import MosaicDatabase
from .components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from .models.backend_configuration import BackendConfiguration
from .models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from .models.mosaic_database_configuration import MosaicDatabaseConfiguration
from .models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot


class Backend:
    @staticmethod
    def create_application(
        *,
        ada_app_factory: Callable[[], Any] | None = None,
        application_configurer: Callable[[Any], None] | None = None,
        database_configuration: MosaicDatabaseConfiguration | None = None,
        pilot_administration_configuration: (
            PilotAdministrationConfiguration | None
        ) = None,
        skill_catalogue_snapshot: SkillCatalogueSnapshot | None = None,
    ) -> Any:
        """
        Upgrade storage before creating and configuring the ADA application.

        Imports of the opinionated framework remain lazy so unit tests and
        tooling can inspect MOSAIC without requiring the target ADA runtime.

        :param ada_app_factory: Optional ADA factory used by isolated tests.
        :param application_configurer: Optional outer-boundary configurator.
        :param database_configuration: Optional MOSAIC database configuration.
        :param pilot_administration_configuration: Optional temporary pilot
            administration configuration.
        :param skill_catalogue_snapshot: Optional approved catalogue snapshot.

        :return: Configured ADA ASGI application.

        :raises Exception: If storage, ADA or route configuration fails.
        """
        if database_configuration is None:
            database_configuration = MosaicDatabaseConfiguration()
        if pilot_administration_configuration is None:
            pilot_administration_configuration = (
                PilotAdministrationConfiguration()
            )
        database = MosaicDatabase(database_configuration)
        try:
            MosaicDatabaseMigrator(database).upgrade()
        finally:
            database.dispose()

        if ada_app_factory is None:
            from ada_sdk.api.base_api import create_app

            ada_app_factory = create_app

        application = ada_app_factory()
        Backend._register_readiness_endpoint(application)
        if application_configurer is not None:
            application_configurer(application)
        from .components.identity.bearer_authentication_middleware import BearerAuthenticationMiddleware
        from .components.identity.pilot_bearer_authenticator import PilotBearerAuthenticator

        runtime_database = MosaicDatabase(database_configuration)
        try:
            application.add_middleware(
                BearerAuthenticationMiddleware,
                authenticator=PilotBearerAuthenticator(runtime_database),
            )
            if not pilot_administration_configuration.enabled:
                return application

            from .components.identity.pilot_administration_api import PilotAdministrationApi
            from .components.identity.pilot_user_administration_service import PilotUserAdministrationService

            if skill_catalogue_snapshot is None:
                from .agent import skill_catalogue_snapshot as loaded_snapshot

                skill_catalogue_snapshot = loaded_snapshot
            administration_service = PilotUserAdministrationService(
                runtime_database,
                skill_catalogue_snapshot,
            )
            PilotAdministrationApi(
                pilot_administration_configuration,
                administration_service,
            ).register_routes(application)
        except Exception:
            runtime_database.dispose()
            raise
        return application

    @staticmethod
    def _register_readiness_endpoint(application: Any) -> None:
        """
        Register the internal readiness probe after successful startup.

        :param application: ADA ASGI application exposing route registration.
        """
        application.add_api_route(
            '/ready',
            Backend._readiness,
            methods=['GET'],
            include_in_schema=False,
        )

    @staticmethod
    def _readiness() -> dict[str, str]:
        """
        Return the readiness state of the successfully created process.

        :return: Stable readiness response for the deployment probe.
        """
        return {'status': 'ready'}

    @staticmethod
    def run(
        *,
        configuration: BackendConfiguration | None = None,
        uvicorn_runner: Callable[..., Any] | None = None,
    ) -> None:
        """
        Start the backend using validated deployment configuration.

        :param configuration: Optional validated configuration override.
        :param uvicorn_runner: Optional server runner used by isolated tests.
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
