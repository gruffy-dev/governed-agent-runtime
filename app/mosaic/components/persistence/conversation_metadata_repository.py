from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
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
        returns naive stored datetimes; writes are normalised to UTC, so attach
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

    def get_availability(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
    ) -> tuple[bool, bool] | None:
        """
        Read continuation permission and interruption within the trusted owner scope.

        :param context: Trusted application and user identity.
        :param conversation_id: Validated conversation routing UUID.

        :return: Tuple of can_continue and is_interrupted, or None for missing/foreign metadata.
        """
        self._validate_id(conversation_id)
        flags = self._session.execute(
            select(
                ConversationMetadataRecord.invocation_in_progress,
                ConversationMetadataRecord.is_interrupted,
            ).where(
                ConversationMetadataRecord.conversation_id == str(conversation_id),
                ConversationMetadataRecord.app_name == context.app_name,
                ConversationMetadataRecord.user_id == context.user_id,
            )
        ).one_or_none()
        if flags is None:
            return None
        return (
            not flags.invocation_in_progress and not flags.is_interrupted,
            flags.is_interrupted,
        )

    def begin_invocation(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
    ) -> bool:
        """
        Atomically reserve an available owned conversation before private dispatch.

        Do not reclaim an existing reservation, including after a process crash.

        :param context: Trusted application and user identity.
        :param conversation_id: Validated conversation routing UUID.

        :return: True only when this transaction acquired the reservation.
        """
        self._validate_id(conversation_id)
        result = self._session.execute(
            update(ConversationMetadataRecord)
            .where(
                ConversationMetadataRecord.conversation_id == str(conversation_id),
                ConversationMetadataRecord.app_name == context.app_name,
                ConversationMetadataRecord.user_id == context.user_id,
                ConversationMetadataRecord.invocation_in_progress.is_(False),
                ConversationMetadataRecord.is_interrupted.is_(False),
            )
            .values(invocation_in_progress=True)
        )
        return result.rowcount == 1

    def finish_invocation(
        self,
        context: TrustedRequestContext,
        conversation_id: UUID,
        *,
        is_interrupted: bool,
    ) -> None:
        """
        Finalise the caller's reservation after private execution has stopped.

        An interrupted conversation cannot be made available by later completion.
        The caller must invoke this exactly once per acquired reservation.

        :param context: Trusted application and user identity.
        :param conversation_id: Validated conversation routing UUID.
        :param is_interrupted: True unless normal durable completion was confirmed.
        """
        self._validate_id(conversation_id)
        self._session.execute(
            update(ConversationMetadataRecord)
            .where(
                ConversationMetadataRecord.conversation_id == str(conversation_id),
                ConversationMetadataRecord.app_name == context.app_name,
                ConversationMetadataRecord.user_id == context.user_id,
                ConversationMetadataRecord.invocation_in_progress.is_(True),
                ConversationMetadataRecord.is_interrupted.is_(False),
            )
            .values(invocation_in_progress=False, is_interrupted=is_interrupted)
        )

    @staticmethod
    def _validate_id(conversation_id: UUID) -> None:
        """
        Reject unvalidated routing references before database access.

        :param conversation_id: Conversation reference to check.

        :raises TypeError: If the reference is not a validated UUID.
        """
        if not isinstance(conversation_id, UUID):
            raise TypeError('Conversation metadata requires a validated UUID.')
