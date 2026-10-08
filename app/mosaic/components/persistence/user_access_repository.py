import hashlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .access_token_record import AccessTokenRecord
from .user_record import UserRecord


class UserAccessRepository:
    def __init__(self, session: Session) -> None:
        """
        Bind user and token operations to one caller-owned transaction.

        :param session: SQLAlchemy session controlled by the calling service.
        """
        self._session = session

    def add_user(
        self,
        user_id: str,
        created_at: datetime,
    ) -> UserRecord:
        """
        Add one enabled user with an immutable identifier.

        :param user_id: Unique user identifier owned by MOSAIC.
        :param created_at: Time at which the user is created.

        :return: Newly persisted user record.

        :raises IntegrityError: If the user identifier already exists.
        """
        user = UserRecord(
            user_id=user_id,
            is_enabled=True,
            created_at=created_at,
            disabled_at=None,
        )
        self._session.add(user)
        self._session.flush()
        return user

    def add_access_token(
        self,
        token_id: str,
        user_id: str,
        plaintext_token: str,
        created_at: datetime,
    ) -> AccessTokenRecord:
        """
        Hash and add one enabled access token for an enabled user.

        :param token_id: Application-generated UUID string for the token row.
        :param user_id: Identifier of the token-owning user.
        :param plaintext_token: Opaque token retained only for this operation.
        :param created_at: Time at which the token is created.

        :return: Newly persisted token record containing only its SHA-256 hash.

        :raises ValueError: If the owning user is missing or disabled.
        :raises IntegrityError: If the token ID or hash already exists.
        """
        user = self._session.get(UserRecord, user_id)
        if user is None or not user.is_enabled:
            raise ValueError('Access tokens require an enabled user.')

        token = AccessTokenRecord(
            token_id=token_id,
            user_id=user_id,
            token_hash=self._hash_token(plaintext_token),
            is_enabled=True,
            created_at=created_at,
            disabled_at=None,
            rotated_at=None,
        )
        self._session.add(token)
        self._session.flush()
        return token

    def resolve_enabled_user(
        self,
        plaintext_token: str,
    ) -> UserRecord | None:
        """
        Resolve an enabled user through an enabled access token.

        :param plaintext_token: Opaque caller credential to hash for lookup.

        :return: Enabled user record, or ``None`` when access is unavailable.
        """
        statement = (
            select(UserRecord)
            .join(
                AccessTokenRecord,
                AccessTokenRecord.user_id == UserRecord.user_id,
            )
            .where(
                AccessTokenRecord.token_hash
                == self._hash_token(plaintext_token),
                AccessTokenRecord.is_enabled.is_(True),
                UserRecord.is_enabled.is_(True),
            )
        )
        return self._session.scalar(statement)

    def list_users(self) -> tuple[UserRecord, ...]:
        """
        List users in stable identifier order without token material.

        :return: User records ordered by immutable user identifier.
        """
        return tuple(
            self._session.scalars(
                select(UserRecord).order_by(UserRecord.user_id)
            )
        )

    def disable_user(
        self,
        user_id: str,
        disabled_at: datetime,
    ) -> bool:
        """
        Disable an enabled user without changing its immutable identifier.

        :param user_id: Identifier of the user to disable.
        :param disabled_at: Time at which access is disabled.

        :return: Whether an enabled user was found and disabled.
        """
        user = self._session.get(UserRecord, user_id)
        if user is None or not user.is_enabled:
            return False

        user.is_enabled = False
        user.disabled_at = disabled_at
        self._session.flush()
        return True

    def disable_access_token(
        self,
        token_id: str,
        disabled_at: datetime,
    ) -> bool:
        """
        Disable one enabled token without changing other user tokens.

        :param token_id: Identifier of the token to disable.
        :param disabled_at: Time at which access is disabled.

        :return: Whether an enabled token was found and disabled.
        """
        token = self._session.get(AccessTokenRecord, token_id)
        if token is None or not token.is_enabled:
            return False

        token.is_enabled = False
        token.disabled_at = disabled_at
        self._session.flush()
        return True

    @staticmethod
    def _hash_token(plaintext_token: str) -> str:
        """
        Create the deterministic SHA-256 digest used for token lookup.

        :param plaintext_token: Opaque token to hash without retaining it.

        :return: Lowercase hexadecimal SHA-256 digest.
        """
        return hashlib.sha256(
            plaintext_token.encode('utf-8')
        ).hexdigest()
