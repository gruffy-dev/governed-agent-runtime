from datetime import UTC, datetime
from secrets import token_urlsafe
from threading import Lock
from uuid import uuid4

from ..persistence.mosaic_database import MosaicDatabase
from ..persistence.user_access_repository import UserAccessRepository
from ..persistence.workspace_service import WorkspaceService
from ...models.identity.pilot_user_credential import PilotUserCredential
from ...models.identity.pilot_user_summary import PilotUserSummary
from ...models.identity.pilot_workspace_skill_update_request import PilotWorkspaceSkillUpdateRequest
from ...models.identity.pilot_workspace_skill_update_result import PilotWorkspaceSkillUpdateResult
from ...models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot
from ...models.workspace_skill_set import WorkspaceSkillSet


class PilotUserAdministrationService:
    def __init__(
        self,
        database: MosaicDatabase,
        catalogue_snapshot: SkillCatalogueSnapshot | None = None,
    ) -> None:
        """
        Bind temporary pilot administration to one MOSAIC database.

        :param database: MOSAIC database used for identity and workspace data.
        :param catalogue_snapshot: Approved Skills and current groups.
        """
        self._database = database
        self._catalogue_snapshot = catalogue_snapshot
        self._write_lock = Lock()

    def create_user(self, user_id: str) -> PilotUserCredential:
        """
        Create a user, hashed token and empty workspace atomically.

        :param user_id: Immutable identifier for the new pilot user.

        :return: Provisioned identity with its one-time plaintext token.

        :raises IntegrityError: If the user identifier already exists.
        """
        created_at = datetime.now(UTC)
        with (
            self._write_lock,
            self._database.create_session() as session,
            session.begin(),
        ):
            user_repository = UserAccessRepository(session)
            workspace_service = WorkspaceService(session)
            user_repository.add_user(user_id, created_at)
            plaintext_token = f'mosaic_r1_{token_urlsafe(32)}'
            token_id = str(uuid4())
            user_repository.add_access_token(
                token_id,
                user_id,
                plaintext_token,
                created_at,
            )
            workspace = workspace_service.create_for_user(
                user_id,
                created_at,
            )

        return PilotUserCredential(
            user_id=user_id,
            token_id=token_id,
            plaintext_token=plaintext_token,
            workspace_id=workspace.workspace_id,
            created_at=created_at,
        )

    def list_users(self) -> tuple[PilotUserSummary, ...]:
        """
        List pilot users without returning token identifiers or material.

        :return: Safe user summaries ordered by immutable user identifier.
        """
        with self._database.create_session() as session:
            repository = UserAccessRepository(session)
            return tuple(
                PilotUserSummary(
                    user_id=user.user_id,
                    is_enabled=user.is_enabled,
                    created_at=user.created_at,
                    disabled_at=user.disabled_at,
                )
                for user in repository.list_users()
            )

    def disable_user(self, user_id: str) -> bool:
        """
        Disable one pilot user so its token no longer resolves.

        :param user_id: Immutable identifier of the user to disable.

        :return: Whether an enabled user was found and disabled.
        """
        with (
            self._write_lock,
            self._database.create_session() as session,
            session.begin(),
        ):
            return UserAccessRepository(session).disable_user(
                user_id,
                datetime.now(UTC),
            )

    def get_workspace_skills(
        self,
        user_id: str,
    ) -> WorkspaceSkillSet | None:
        """
        Return one pilot user's current atomic workspace Skill set.

        :param user_id: Immutable identifier of the workspace owner.

        :return: Current workspace Skill set, or ``None`` when absent.
        """
        with self._database.create_session() as session:
            return WorkspaceService(session).get_for_user(user_id)

    def update_workspace_skills(
        self,
        user_id: str,
        request: PilotWorkspaceSkillUpdateRequest,
    ) -> PilotWorkspaceSkillUpdateResult:
        """
        Resolve approved Skills and atomically replace one workspace set.

        :param user_id: Immutable identifier of the workspace owner.
        :param request: Atomic Skills, groups, clear and dry-run selection.

        :return: Resolved atomic assignment and whether it was applied.

        :raises LookupError: If the user's workspace does not exist.
        :raises RuntimeError: If no approved catalogue snapshot is available.
        :raises ValueError: If a Skill or group is not currently approved.
        """
        skill_ids = self._resolve_skill_ids(request)
        with (
            self._write_lock,
            self._database.create_session() as session,
            session.begin(),
        ):
            workspace_service = WorkspaceService(session)
            workspace = workspace_service.get_for_user(user_id)
            if workspace is None:
                raise LookupError('Workspace does not exist.')
            if request.dry_run:
                return self._create_workspace_skill_update_result(
                    workspace,
                    request,
                    skill_ids,
                    applied=False,
                )
            updated_workspace = workspace_service.replace_skill_ids(
                user_id,
                workspace.version,
                skill_ids,
                datetime.now(UTC),
            )
            return self._create_workspace_skill_update_result(
                updated_workspace,
                request,
                skill_ids,
                applied=True,
            )

    def _resolve_skill_ids(
        self,
        request: PilotWorkspaceSkillUpdateRequest,
    ) -> tuple[str, ...]:
        """
        Validate and expand requested identifiers against the loaded snapshot.

        :param request: Atomic Skills and current groups to resolve.

        :return: Sorted unique atomic Skill identifiers.

        :raises RuntimeError: If no approved catalogue snapshot is available.
        :raises ValueError: If a Skill or group is not currently approved.
        """
        if request.clear:
            return ()
        if self._catalogue_snapshot is None:
            raise RuntimeError('Approved Skill catalogue is unavailable.')

        available_skill_ids = {
            skill.name for skill in self._catalogue_snapshot.skills
        }
        unknown_skill_ids = set(request.skill_ids) - available_skill_ids
        if unknown_skill_ids:
            raise ValueError('One or more Skills are not approved.')

        groups_by_id = {
            group.group_id: group.skill_ids
            for group in self._catalogue_snapshot.groups
        }
        unknown_group_ids = set(request.group_ids) - groups_by_id.keys()
        if unknown_group_ids:
            raise ValueError('One or more Skill groups are not approved.')

        resolved_skill_ids = set(request.skill_ids)
        for group_id in request.group_ids:
            resolved_skill_ids.update(groups_by_id[group_id])
        return tuple(sorted(resolved_skill_ids))

    @staticmethod
    def _create_workspace_skill_update_result(
        workspace: WorkspaceSkillSet,
        request: PilotWorkspaceSkillUpdateRequest,
        skill_ids: tuple[str, ...],
        applied: bool,
    ) -> PilotWorkspaceSkillUpdateResult:
        """
        Build the safe response for an applied or dry-run assignment.

        :param workspace: Current or newly updated workspace state.
        :param request: Selection containing any expanded group identifiers.
        :param skill_ids: Sorted atomic assignment after group expansion.
        :param applied: Whether the assignment was committed.

        :return: Stable pilot workspace Skill update result.
        """
        return PilotWorkspaceSkillUpdateResult(
            workspace_id=workspace.workspace_id,
            user_id=workspace.user_id,
            version=workspace.version,
            skill_ids=skill_ids,
            group_ids=tuple(sorted(request.group_ids)),
            applied=applied,
            updated_at=workspace.updated_at,
        )
