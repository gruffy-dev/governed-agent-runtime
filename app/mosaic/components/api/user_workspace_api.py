from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Response

from ..identity.trusted_request_context_dependency import TrustedRequestContextDependency
from ..persistence.mosaic_database import MosaicDatabase
from ..persistence.workspace_service import WorkspaceService
from ...models.identity.trusted_request_context import TrustedRequestContext
from ...models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot
from ...models.workspace.user_workspace_summary import UserWorkspaceSummary
from ...models.workspace.workspace_skill_summary import WorkspaceSkillSummary


class UserWorkspaceApi:
    def __init__(
        self,
        database: MosaicDatabase,
        context_dependency: TrustedRequestContextDependency,
        catalogue_snapshot: SkillCatalogueSnapshot | None = None,
    ) -> None:
        """
        Bind read-only browser workspace metadata to trusted ownership.

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

        :param application: Public MOSAIC application receiving the GET route.
        """
        router = APIRouter(prefix='/api/v1')

        def get_workspace(
            response: Response,
            context: Annotated[TrustedRequestContext, Depends(self._context_dependency)],
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
        summaries: tuple[WorkspaceSkillSummary, ...] = ()
        if workspace is not None and workspace.skill_ids:
            snapshot = self._get_catalogue()
            assigned = set(workspace.skill_ids)
            summaries = tuple(
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
                if skill.name in assigned
            )
        return UserWorkspaceSummary(
            user_id=context.user_id,
            workspace_id=None if workspace is None else UUID(workspace.workspace_id),
            version=None if workspace is None else workspace.version,
            skills=summaries,
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
