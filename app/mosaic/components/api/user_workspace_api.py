from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response

from ..identity.trusted_request_context_dependency import TrustedRequestContextDependency
from ..persistence.mosaic_database import MosaicDatabase
from ..persistence.stale_workspace_version_error import StaleWorkspaceVersionError
from ..persistence.workspace_service import WorkspaceService
from ...models.identity.trusted_request_context import TrustedRequestContext
from ...models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot
from ...models.workspace.user_workspace_summary import UserWorkspaceSummary
from ...models.workspace.workspace_skill_selection import WorkspaceSkillSelection
from ...models.workspace.workspace_skill_summary import WorkspaceSkillSummary
from ...models.workspace_skill_set import WorkspaceSkillSet


class UserWorkspaceApi:
    def __init__(
        self,
        database: MosaicDatabase,
        context_dependency: TrustedRequestContextDependency,
        catalogue_snapshot: SkillCatalogueSnapshot | None = None,
    ) -> None:
        """
        Bind browser workspace management to trusted ownership.

        :param database: Backend-owned identity and workspace database.
        :param context_dependency: Backend-owned authenticated identity dependency.
        :param catalogue_snapshot: Optional immutable catalogue supplied at composition.
        """
        self._database = database
        self._context_dependency = context_dependency
        self._catalogue_snapshot = catalogue_snapshot

    def register_routes(self, application: FastAPI) -> None:
        """
        Register the signed-in user's workspace without caller identity selectors.

        :param application: Public MOSAIC application receiving the workspace routes.
        """
        router = APIRouter(prefix='/api/v1')

        def get_workspace(
            response: Response,
            context: Annotated[
                TrustedRequestContext, Depends(self._context_dependency)
            ],
        ) -> UserWorkspaceSummary:
            """
            Return current assigned Skill metadata for the authenticated owner.

            Assignment edits apply to subsequent Goals. This response must not be
            interpreted as changing the immutable snapshot of an active Goal.

            :param response: Response receiving a private-data caching prohibition.
            :param context: Server-derived user and application identity.

            :return: Read-only owner and assigned Skill metadata, never credentials.
            """
            response.headers['Cache-Control'] = 'no-store'
            return self._get_workspace(context)

        router.add_api_route(
            '/workspace',
            get_workspace,
            methods=['GET'],
            response_model=UserWorkspaceSummary,
        )

        @router.get('/skills')
        def list_skills(
            response: Response,
            context: Annotated[
                TrustedRequestContext, Depends(self._context_dependency)
            ],
        ) -> tuple[WorkspaceSkillSummary, ...]:
            """
            List display metadata for published Skills available to signed-in users.

            :param response: Response receiving a private-data caching prohibition.
            :param context: Required trusted authentication context.

            :return: Published Skill display metadata.
            """
            response.headers['Cache-Control'] = 'no-store'
            return self._summarise_skills(self._get_catalogue())

        @router.post('/workspace/skills')
        def save_skills(
            selection: WorkspaceSkillSelection,
            response: Response,
            context: Annotated[
                TrustedRequestContext, Depends(self._context_dependency)
            ],
        ) -> UserWorkspaceSummary:
            """
            Save a complete Skill selection for the authenticated user's workspace.

            :param selection: Selected IDs and the version read before editing.
            :param response: Response receiving a private-data caching prohibition.
            :param context: Trusted workspace owner identity.

            :return: Saved workspace selection and its new version.

            :raises HTTPException: If the selection is unavailable or the version is stale.
            """
            response.headers['Cache-Control'] = 'no-store'
            snapshot = self._get_catalogue() if selection.skill_ids else None
            headers = {'Cache-Control': 'no-store'}
            if snapshot is not None and not set(selection.skill_ids).issubset(
                skill.name for skill in snapshot.skills
            ):
                raise HTTPException(400, 'Invalid Skill selection', headers=headers)
            try:
                with self._database.create_session() as session, session.begin():
                    workspace = WorkspaceService(session).replace_skill_ids(
                        context.user_id,
                        selection.expected_version,
                        selection.skill_ids,
                        datetime.now(UTC),
                    )
            except StaleWorkspaceVersionError as error:
                raise HTTPException(
                    409, 'Workspace selection changed', headers=headers
                ) from error
            except ValueError as error:
                raise HTTPException(
                    404, 'Workspace not found', headers=headers
                ) from error
            return self._summarise_workspace(context.user_id, workspace, snapshot)

        application.include_router(router)

    def _get_workspace(self, context: TrustedRequestContext) -> UserWorkspaceSummary:
        """
        Project only owned assignments that remain in the executable catalogue.

        Missing or empty workspaces produce an empty list without importing the
        agent. Unknown or withdrawn references and unrelated groups are omitted.
        Instructions, schemas, capability declarations and provider data stay private.

        :param context: Validated owner; request parameters cannot override it.

        :return: Current workspace summary suitable for the read-only GUI panel.

        :raises Exception: If storage or catalogue loading fails; the public failure
            handler sanitises the error without returning internal exception text.
        """
        with self._database.create_session() as session:
            workspace = WorkspaceService(session).get_for_user(context.user_id)
        snapshot = (
            self._get_catalogue()
            if workspace is not None and workspace.skill_ids
            else None
        )
        return self._summarise_workspace(context.user_id, workspace, snapshot)

    def _summarise_workspace(
        self,
        user_id: str,
        workspace: WorkspaceSkillSet | None,
        snapshot: SkillCatalogueSnapshot | None,
    ) -> UserWorkspaceSummary:
        """
        Present a workspace using display metadata for its published Skills.

        :param user_id: Authenticated workspace owner.
        :param workspace: Current or newly saved workspace.
        :param snapshot: Published catalogue, when the workspace has selections.

        :return: Safe workspace summary.
        """
        return UserWorkspaceSummary(
            user_id=user_id,
            workspace_id=None if workspace is None else UUID(workspace.workspace_id),
            version=None if workspace is None else workspace.version,
            skills=()
            if workspace is None or snapshot is None
            else self._summarise_skills(snapshot, set(workspace.skill_ids)),
        )

    def _summarise_skills(
        self,
        snapshot: SkillCatalogueSnapshot,
        selected: set[str] | None = None,
    ) -> tuple[WorkspaceSkillSummary, ...]:
        """
        Build the display projection shared by the catalogue and workspace routes.

        :param snapshot: Published Skill catalogue.
        :param selected: Optional filter for the workspace's selected IDs.

        :return: Sorted display metadata without executable Skill content.
        """
        return tuple(
            WorkspaceSkillSummary(
                skill_id=skill.name,
                display_name=skill.name.replace('-', ' ').capitalize(),
                description=skill.description,
                kind=skill.kind,
                groups=tuple(
                    sorted(
                        group.group_id
                        for group in snapshot.groups
                        if skill.name in group.skill_ids
                    )
                ),
            )
            for skill in sorted(snapshot.skills, key=lambda item: item.name)
            if selected is None or skill.name in selected
        )

    def _get_catalogue(self) -> SkillCatalogueSnapshot:
        """
        Reuse the normal agent's immutable catalogue without another synchronisation.

        Keep the import lazy so empty workspaces and isolated backend tests do not
        require ADA or model configuration merely to inspect signed-in identity.

        :return: Explicitly supplied or normal agent catalogue snapshot.

        :raises Exception: If the normal agent cannot initialise its catalogue.
        """
        if self._catalogue_snapshot is not None:
            return self._catalogue_snapshot
        from ...agent import skill_catalogue_snapshot

        return skill_catalogue_snapshot
