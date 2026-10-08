from datetime import UTC, datetime
from secrets import token_urlsafe
from threading import Lock
from uuid import uuid4

from ..persistence.mosaic_database import MosaicDatabase
from ..persistence.user_access_repository import UserAccessRepository
from ..persistence.workspace_service import WorkspaceService
from ...models.identity.pilot_user_credential import PilotUserCredential
from ...models.identity.pilot_user_summary import PilotUserSummary


class PilotUserAdministrationService:
    def __init__(self, database: MosaicDatabase) -> None:
        """
        Bind temporary pilot administration to one MOSAIC database.

        :param database: MOSAIC database used for identity and workspace data.
        """
        self._database = database
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
