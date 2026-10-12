from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from .conversation_metadata_record import ConversationMetadataRecord
from .user_record import UserRecord
from ...models.identity.trusted_request_context import TrustedRequestContext


class ConversationMetadataRepository:
    def __init__(self, session: Session) -> None:
        """
        Bind metadata to a caller-owned transaction without storing session data.

        :param session: SQLAlchemy session whose commit and rollback the caller owns.
        """
        self._session = session

    def add(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
        created_at: datetime,
    ) -> None:
        """
        Record the original creation timestamp for one owned ADA conversation.

        No update or upsert is provided: a duplicate ID must not change ownership
        or creation time. The caller supplies the backend-recorded timestamp,
        never an inferred ADA activity timestamp or a browser-provided field.

        :param context: Trusted application and user identity.
        :param conversation_id: Server-generated UUID used by the ADA session.
        :param created_at: Backend-recorded timezone-aware creation timestamp.

        :raises TypeError: If the routing reference is not a UUID.
        :raises ValueError: If the timestamp or owning user is invalid.
        :raises IntegrityError: If the conversation UUID is already recorded.
        """
        self._validate_id(conversation_id)
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            raise ValueError('Conversation creation time must include a timezone.')
        if self._session.get(UserRecord, context.user_id) is None:
            raise ValueError('Conversation metadata requires an existing user.')
        self._session.add(
            ConversationMetadataRecord(
                conversation_id=str(conversation_id),
                app_name=context.app_name,
                user_id=context.user_id,
                created_at=created_at.astimezone(UTC),
            )
        )
        self._session.flush()

    def get_created_at(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
    ) -> datetime | None:
        """
        Read creation time only within the trusted application and user scope.

        A missing or foreign UUID returns the same absence result. SQLite
        returns naive stored datetimes; writes are normalized to UTC, so attach
        UTC on read without inferring any conversation timestamp from history.

        :param context: Trusted application and user identity.
        :param conversation_id: Validated conversation routing UUID.

        :return: Original creation time in UTC, or None when unavailable.

        :raises TypeError: If the routing reference is not a UUID.
        """
        self._validate_id(conversation_id)
        created_at = self._session.scalar(
            select(ConversationMetadataRecord.created_at).where(
                ConversationMetadataRecord.conversation_id == str(conversation_id),
                ConversationMetadataRecord.app_name == context.app_name,
                ConversationMetadataRecord.user_id == context.user_id,
            )
        )
        if created_at is None:
            return None
        if created_at.tzinfo is None:
            return created_at.replace(tzinfo=UTC)
        return created_at.astimezone(UTC)

    @staticmethod
    def _validate_id(conversation_id: UUID) -> None:
        """
        Reject unvalidated routing references before database access.

        :param conversation_id: Conversation reference to check.

        :raises TypeError: If the reference is not a validated UUID.
        """
        if not isinstance(conversation_id, UUID):
            raise TypeError('Conversation metadata requires a validated UUID.')
