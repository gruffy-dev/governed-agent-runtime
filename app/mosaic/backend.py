from collections.abc import Callable
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from .components.ada.ada_application_lifecycle import AdaApplicationLifecycle
from .components.ada.ada_asgi_transport import AdaAsgiTransport
from .components.persistence.mosaic_database import MosaicDatabase
from .components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from .models.backend_configuration import BackendConfiguration
from .models.ada.ada_application_adapter_configuration import AdaApplicationAdapterConfiguration
from .models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from .models.identity.pilot_authentication_configuration import PilotAuthenticationConfiguration
from .models.identity.trusted_request_configuration import TrustedRequestConfiguration
from .models.mosaic_database_configuration import MosaicDatabaseConfiguration
from .models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot


class Backend:
    @staticmethod
    def create_application(
        *,
        ada_app_factory: Callable[[], Any] | None = None,
        application_configurer: Callable[[Any], None] | None = None,
        database_configuration: MosaicDatabaseConfiguration | None = None,
        pilot_authentication_configuration: (
            PilotAuthenticationConfiguration | None
        ) = None,
        pilot_administration_configuration: (
            PilotAdministrationConfiguration | None
        ) = None,
        trusted_request_configuration: TrustedRequestConfiguration | None = None,
        skill_catalogue_snapshot: SkillCatalogueSnapshot | None = None,
        ada_adapter_configuration: AdaApplicationAdapterConfiguration | None = None,
    ) -> Any:
        """
        Upgrade storage and create the public MOSAIC application around private ADA.

        Imports of the opinionated framework remain lazy so unit tests and
        tooling can inspect MOSAIC without requiring the target ADA runtime.

        :param ada_app_factory: Optional ADA factory used by isolated tests.
        :param application_configurer: Optional outer-boundary configurator.
        :param database_configuration: Optional MOSAIC database configuration.
        :param pilot_authentication_configuration: Optional pilot browser
            authentication and cookie configuration.
        :param pilot_administration_configuration: Optional temporary pilot
            administration configuration.
        :param trusted_request_configuration: Server-owned application identity
            used by public API dependencies.
        :param skill_catalogue_snapshot: Optional approved catalogue snapshot.
        :param ada_adapter_configuration: Private ASGI lifecycle and transport bounds.

        :return: Public MOSAIC app; generated ADA routes are not mounted.

        :raises Exception: If storage, ADA or route configuration fails.
        """
        if database_configuration is None:
            database_configuration = MosaicDatabaseConfiguration()
        if pilot_authentication_configuration is None:
            pilot_authentication_configuration = PilotAuthenticationConfiguration()
        if pilot_administration_configuration is None:
            pilot_administration_configuration = PilotAdministrationConfiguration()
        if trusted_request_configuration is None:
            trusted_request_configuration = TrustedRequestConfiguration()
        database = MosaicDatabase(database_configuration)
        try:
            MosaicDatabaseMigrator(database).upgrade()
        finally:
            database.dispose()

        if ada_app_factory is None:
            from ada_sdk.api.base_api import create_app

            ada_app_factory = create_app

        private_application = ada_app_factory()
        if ada_adapter_configuration is None:
            ada_adapter_configuration = AdaApplicationAdapterConfiguration()
        lifecycle = AdaApplicationLifecycle(
            private_application, ada_adapter_configuration
        )
        runtime_database = MosaicDatabase(database_configuration)

        @asynccontextmanager
        async def lifespan(public_application: FastAPI) -> AsyncIterator[None]:
            """
            Keep ADA infrastructure running for the public application lifetime.

            :param public_application: Public app receiving server-owned transport state.

            :return: Context governing private startup, shutdown and database cleanup.
            """
            try:
                async with lifecycle.running():
                    public_application.state.ada_transport = AdaAsgiTransport(
                        private_application,
                        ada_adapter_configuration,
                        lifespan_state=lifecycle.state,
                    )
                    try:
                        yield
                    finally:
                        del public_application.state.ada_transport
            finally:
                runtime_database.dispose()

        application = FastAPI(
            lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
        )
        Backend._register_readiness_endpoint(application)
        application.add_api_route(
            '/health', Backend._health, methods=['GET'], include_in_schema=False
        )
        from .components.identity.pilot_authentication_api import PilotAuthenticationApi
        from .components.identity.pilot_authentication_middleware import PilotAuthenticationMiddleware
        from .components.identity.pilot_bearer_authenticator import PilotBearerAuthenticator
        from .components.identity.authentication_failure_handler import AuthenticationFailureHandler
        from .components.identity.trusted_request_context_dependency import TrustedRequestContextDependency
        from .components.api.conversation_api_contract import ConversationApiContract
        from .components.api.conversation_api_documentation import ConversationApiDocumentation

        try:
            if application_configurer is not None:
                application_configurer(application)
            AuthenticationFailureHandler().register(application)
            authenticator = PilotBearerAuthenticator(runtime_database)
            application.add_middleware(
                PilotAuthenticationMiddleware,
                authenticator=authenticator,
                cookie_name=pilot_authentication_configuration.cookie_name,
            )
            PilotAuthenticationApi(
                pilot_authentication_configuration,
                authenticator,
            ).register_routes(application)
            ConversationApiDocumentation(
                ConversationApiContract(pilot_authentication_configuration),
                TrustedRequestContextDependency(trusted_request_configuration),
            ).register_routes(application)
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
    def _health() -> dict[str, str]:
        """
        Report public application liveness without querying private session data.

        :return: Stable liveness response.
        """
        return {'status': 'ok'}

    @staticmethod
    def _register_readiness_endpoint(application: Any) -> None:
        """
        Register the internal readiness probe after successful startup.

        :param application: Public MOSAIC application exposing route registration.
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
