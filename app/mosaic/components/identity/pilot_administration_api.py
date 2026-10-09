from hmac import compare_digest
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Response
from sqlalchemy.exc import IntegrityError

from .authentication_error import AuthenticationError
from .pilot_user_administration_service import PilotUserAdministrationService
from ..persistence.stale_workspace_version_error import StaleWorkspaceVersionError
from ...models.identity.pilot_administration_configuration import PilotAdministrationConfiguration
from ...models.identity.pilot_user_creation_request import PilotUserCreationRequest
from ...models.identity.pilot_user_provisioning_response import PilotUserProvisioningResponse
from ...models.identity.pilot_user_summary import PilotUserSummary
from ...models.identity.pilot_workspace_skill_update_request import PilotWorkspaceSkillUpdateRequest
from ...models.identity.pilot_workspace_skill_update_result import PilotWorkspaceSkillUpdateResult
from ...models.workspace_skill_set import WorkspaceSkillSet


class PilotAdministrationApi:
    def __init__(
        self,
        configuration: PilotAdministrationConfiguration,
        service: PilotUserAdministrationService,
    ) -> None:
        """
        Bind temporary protected routes to pilot administration behaviour.

        :param configuration: Route enablement and administrator secret.
        :param service: Pilot user administration transaction boundary.
        """
        self._configuration = configuration
        self._service = service

    def register_routes(self, application: Any) -> None:
        """
        Register hidden pilot routes only when explicitly enabled.

        :param application: FastAPI-compatible application receiving routes.
        """
        if not self._configuration.enabled:
            return

        router = APIRouter(
            prefix='/api/v1/admin',
            dependencies=[Depends(self._authenticate)],
        )
        router.add_api_route(
            '/users',
            self.create_user,
            methods=['POST'],
            response_model=PilotUserProvisioningResponse,
            status_code=201,
            include_in_schema=False,
        )
        router.add_api_route(
            '/users',
            self.list_users,
            methods=['GET'],
            response_model=list[PilotUserSummary],
            include_in_schema=False,
        )
        router.add_api_route(
            '/users/{user_id}/disable',
            self.disable_user,
            methods=['POST'],
            status_code=204,
            include_in_schema=False,
        )
        router.add_api_route(
            '/workspaces/{user_id}/skills',
            self.show_workspace_skills,
            methods=['GET'],
            response_model=WorkspaceSkillSet,
            include_in_schema=False,
        )
        router.add_api_route(
            '/workspaces/{user_id}/skills',
            self.set_workspace_skills,
            methods=['PUT'],
            response_model=PilotWorkspaceSkillUpdateResult,
            include_in_schema=False,
        )
        application.include_router(router)

    def create_user(
        self,
        request: PilotUserCreationRequest,
        response: Response,
    ) -> PilotUserProvisioningResponse:
        """
        Provision one pilot user and expose its plaintext token once.

        :param request: Validated immutable user identifier.
        :param response: HTTP response receiving no-store cache policy.

        :return: Provisioned user, workspace and one-time token.

        :raises HTTPException: If the user identifier already exists.
        """
        try:
            credential = self._service.create_user(request.user_id)
        except IntegrityError as error:
            raise HTTPException(
                status_code=409,
                detail='Conflict',
            ) from error
        response.headers['Cache-Control'] = 'no-store'
        return PilotUserProvisioningResponse(
            user_id=credential.user_id,
            token_id=credential.token_id,
            plaintext_token=(
                credential.plaintext_token.get_secret_value()
            ),
            workspace_id=credential.workspace_id,
            created_at=credential.created_at,
        )

    def list_users(self) -> tuple[PilotUserSummary, ...]:
        """
        Return safe pilot user summaries without token material.

        :return: Pilot users ordered by immutable user identifier.
        """
        return self._service.list_users()

    def disable_user(
        self,
        user_id: Annotated[
            str,
            Path(
                min_length=1,
                max_length=255,
                pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]*$',
            ),
        ],
    ) -> Response:
        """
        Disable one pilot user and all of its current access tokens.

        :param user_id: Immutable identifier of the pilot user to disable.

        :return: Empty successful response after the user is disabled.

        :raises HTTPException: If no enabled user has the identifier.
        """
        if not self._service.disable_user(user_id):
            raise HTTPException(
                status_code=404,
                detail='Not found',
            )
        return Response(status_code=204)

    def show_workspace_skills(
        self,
        user_id: Annotated[
            str,
            Path(
                min_length=1,
                max_length=255,
                pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]*$',
            ),
        ],
    ) -> WorkspaceSkillSet:
        """
        Return one pilot user's current atomic workspace Skill assignment.

        :param user_id: Immutable identifier of the workspace owner.

        :return: Current versioned workspace Skill set.

        :raises HTTPException: If the workspace does not exist.
        """
        workspace = self._service.get_workspace_skills(user_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail='Not found')
        return workspace

    def set_workspace_skills(
        self,
        user_id: Annotated[
            str,
            Path(
                min_length=1,
                max_length=255,
                pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]*$',
            ),
        ],
        request: PilotWorkspaceSkillUpdateRequest,
    ) -> PilotWorkspaceSkillUpdateResult:
        """
        Resolve and optionally apply one complete atomic Skill assignment.

        :param user_id: Immutable identifier of the workspace owner.
        :param request: Skills, groups, clear and dry-run selection.

        :return: Expanded atomic Skill assignment and application state.

        :raises HTTPException: If validation or workspace update fails.
        """
        try:
            return self._service.update_workspace_skills(
                user_id,
                request,
            )
        except LookupError as error:
            raise HTTPException(
                status_code=404,
                detail='Not found',
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail='Invalid Skill selection',
            ) from error
        except StaleWorkspaceVersionError as error:
            raise HTTPException(
                status_code=409,
                detail='Conflict',
            ) from error

    def _authenticate(
        self,
        authorization: Annotated[
            str | None,
            Header(alias='Authorization'),
        ] = None,
    ) -> None:
        """
        Require the dedicated administrator bearer secret.

        :param authorization: Caller-supplied Authorization header.

        :raises AuthenticationError: If the bearer credential is absent or invalid.
        """
        configured_secret = self._configuration.administrator_secret
        if configured_secret is None or authorization is None:
            raise AuthenticationError(status_code=403)

        scheme, separator, supplied_secret = authorization.partition(' ')
        expected_secret = configured_secret.get_secret_value()
        if (
            separator != ' '
            or scheme.lower() != 'bearer'
            or not compare_digest(supplied_secret, expected_secret)
        ):
            raise AuthenticationError(status_code=403)
