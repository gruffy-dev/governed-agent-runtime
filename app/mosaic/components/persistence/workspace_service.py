from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ...models.workspace_skill_set import WorkspaceSkillSet
from .stale_workspace_version_error import StaleWorkspaceVersionError
from .user_record import UserRecord
from .workspace_record import WorkspaceRecord
from .workspace_skill_record import WorkspaceSkillRecord


class WorkspaceService:
    def __init__(self, session: Session) -> None:
        """
        Bind workspace operations to one caller-owned transaction.

        :param session: SQLAlchemy session controlled by the calling service.
        """
        self._session = session

    def create_for_user(
        self,
        user_id: str,
        created_at: datetime,
    ) -> WorkspaceSkillSet:
        """
        Create one empty versioned workspace for an existing user.

        :param user_id: Immutable identifier of the workspace owner.
        :param created_at: Time at which the workspace is created.

        :return: Newly created empty workspace Skill set.

        :raises ValueError: If the user is missing or already has a workspace.
        """
        if self._session.get(UserRecord, user_id) is None:
            raise ValueError('Workspace owner does not exist.')
        if self.get_for_user(user_id) is not None:
            raise ValueError('User already has a workspace.')

        workspace = WorkspaceRecord(
            workspace_id=str(uuid4()),
            user_id=user_id,
            version=1,
            created_at=created_at,
            updated_at=created_at,
        )
        self._session.add(workspace)
        self._session.flush()
        return WorkspaceSkillSet(
            workspace_id=workspace.workspace_id,
            user_id=workspace.user_id,
            version=workspace.version,
            skill_ids=(),
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )

    def get_for_user(self, user_id: str) -> WorkspaceSkillSet | None:
        """
        Read one user's current versioned atomic Skill set.

        :param user_id: Immutable identifier of the workspace owner.

        :return: Current workspace Skill set, or ``None`` when absent.
        """
        workspace = self._session.scalar(
            select(WorkspaceRecord).where(
                WorkspaceRecord.user_id == user_id
            )
        )
        if workspace is None:
            return None

        skill_ids = tuple(
            self._session.scalars(
                select(WorkspaceSkillRecord.skill_id)
                .where(
                    WorkspaceSkillRecord.workspace_id
                    == workspace.workspace_id
                )
                .order_by(WorkspaceSkillRecord.skill_id)
            )
        )
        return WorkspaceSkillSet(
            workspace_id=workspace.workspace_id,
            user_id=workspace.user_id,
            version=workspace.version,
            skill_ids=skill_ids,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )

    def replace_skill_ids(
        self,
        user_id: str,
        expected_version: int,
        skill_ids: tuple[str, ...],
        updated_at: datetime,
    ) -> WorkspaceSkillSet:
        """
        Atomically replace one workspace's complete atomic Skill set.

        :param user_id: Immutable identifier of the workspace owner.
        :param expected_version: Workspace version read by the caller.
        :param skill_ids: Complete replacement set of atomic Skill identifiers.
        :param updated_at: Time at which the replacement is applied.

        :return: Updated workspace Skill set with its incremented version.

        :raises ValueError: If the workspace, version, or Skill IDs are invalid.
        :raises StaleWorkspaceVersionError: If the workspace version changed.
        """
        if expected_version < 1:
            raise ValueError('expected_version must be positive.')
        if any(
            not skill_id or len(skill_id) > 255
            for skill_id in skill_ids
        ):
            raise ValueError('Skill IDs must contain 1-255 characters.')
        if len(skill_ids) != len(set(skill_ids)):
            raise ValueError('Skill IDs must not contain duplicates.')

        workspace_id = self._session.scalar(
            select(WorkspaceRecord.workspace_id).where(
                WorkspaceRecord.user_id == user_id
            )
        )
        if workspace_id is None:
            raise ValueError('Workspace does not exist.')

        result = self._session.execute(
            update(WorkspaceRecord)
            .where(
                WorkspaceRecord.workspace_id == workspace_id,
                WorkspaceRecord.version == expected_version,
            )
            .values(
                version=expected_version + 1,
                updated_at=updated_at,
            )
        )
        if result.rowcount != 1:
            raise StaleWorkspaceVersionError(
                'Workspace version is stale.'
            )

        self._session.execute(
            delete(WorkspaceSkillRecord).where(
                WorkspaceSkillRecord.workspace_id == workspace_id
            )
        )
        self._session.add_all(
            WorkspaceSkillRecord(
                workspace_id=workspace_id,
                skill_id=skill_id,
            )
            for skill_id in sorted(skill_ids)
        )
        self._session.flush()
        updated_workspace = self.get_for_user(user_id)
        if updated_workspace is None:
            raise RuntimeError('Updated workspace is unavailable.')
        return updated_workspace
