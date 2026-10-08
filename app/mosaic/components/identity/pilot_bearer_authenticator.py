from ..persistence.mosaic_database import MosaicDatabase
from ..persistence.user_access_repository import UserAccessRepository
from ...models.identity.trusted_user_context import TrustedUserContext


class PilotBearerAuthenticator:
    def __init__(self, database: MosaicDatabase) -> None:
        """
        Bind temporary pilot bearer authentication to MOSAIC storage.

        :param database: MOSAIC database containing hashed access tokens.
        """
        self._database = database

    def authenticate(
        self,
        plaintext_token: str,
    ) -> TrustedUserContext | None:
        """
        Resolve one enabled pilot user from an opaque bearer token.

        :param plaintext_token: Caller credential retained only for lookup.

        :return: Immutable trusted user context, or ``None`` when invalid.
        """
        with self._database.create_session() as session:
            user = UserAccessRepository(session).resolve_enabled_user(
                plaintext_token
            )
            if user is None:
                return None
            return TrustedUserContext(user_id=user.user_id)
