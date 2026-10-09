import math
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from ..ada.ada_application_error import AdaApplicationError
from ...models.api.conversation_detail import ConversationDetail
from ...models.api.conversation_message import ConversationMessage
from ...models.api.conversation_projection_configuration import ConversationProjectionConfiguration
from ...models.api.conversation_summary import ConversationSummary


class ConversationSessionProjector:
    def __init__(self, configuration: ConversationProjectionConfiguration) -> None:
        """
        Configure an explicit allowlist for public session-history projection.

        Ownership must already have been verified by the trusted session adapter.
        No raw SDK dictionary is returned to public clients.

        :param configuration: Public agent author and title-length configuration.
        """
        self._configuration = configuration

    def detail(
        self, session: dict[str, Any], *, created_at: datetime
    ) -> ConversationDetail:
        """
        Map an owned ADA session to public conversation metadata and text.

        ADA does not provide a creation timestamp. The caller must supply the
        authoritative recorded value, not infer it from last activity or history.

        :param session: Ownership-validated ADA session including complete events.
        :param created_at: Backend-recorded, timezone-aware conversation creation time.

        :return: Public text-only history ordered by persisted event time.

        :raises AdaApplicationError: If required session or public event data is invalid.
        """
        try:
            conversation_id = UUID(session['id'])
            timestamps = [
                session[key]
                for key in ('last_update_time', 'lastUpdateTime')
                if key in session
            ]
            if not timestamps or any(value != timestamps[0] for value in timestamps):
                raise ValueError('Missing or conflicting activity timestamp.')
            last_activity_at = self._timestamp(timestamps[0])
            events = session['events']
            if not isinstance(events, list):
                raise TypeError('Missing complete event history.')
            messages: list[ConversationMessage] = []
            for event in events:
                if not isinstance(event, dict):
                    raise TypeError('Invalid persisted event.')
                message = self._message(event)
                if message is not None:
                    messages.append(message)
            messages.sort(key=lambda message: message.created_at)
            if len({message.message_id for message in messages}) != len(messages):
                raise ValueError('Duplicate public event ID.')
            first_prompt = next(
                (message.text for message in messages if message.role == 'user'), None
            )
            title = (
                None
                if first_prompt is None
                else ' '.join(first_prompt.split())[
                    : self._configuration.title_maximum_characters
                ]
            )
            return ConversationDetail(
                conversation_id=conversation_id,
                title=title,
                created_at=created_at,
                last_activity_at=last_activity_at,
                messages=tuple(messages),
            )
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            raise AdaApplicationError(
                'Private session could not be mapped to public conversation data.'
            ) from None

    def summary(
        self, session: dict[str, Any], *, created_at: datetime
    ) -> ConversationSummary:
        """
        Map a complete owned session to public summary fields only.

        Collection records lacking history must be hydrated before deriving a title.

        :param session: Ownership-validated ADA session including complete events.
        :param created_at: Backend-recorded, timezone-aware conversation creation time.

        :return: Public summary without message history or internal SDK fields.

        :raises AdaApplicationError: If public conversation data cannot be derived safely.
        """
        detail = self.detail(session, created_at=created_at)
        return ConversationSummary.model_validate(
            detail.model_dump(exclude={'messages'})
        )

    def _message(self, event: dict[str, Any]) -> ConversationMessage | None:
        """
        Select original user text or completed public-agent text from one event.

        Tool events, thought parts, partials, branch output, other agent output
        and error events are omitted. Metadata and non-text parts are never copied.

        :param event: Persisted internal ADA event.

        :return: Public message, or None when the event contains no public text.

        :raises ValueError: If a selected public message has invalid metadata or content.
        :raises TypeError: If a selected public message contains non-string text.
        """
        if (
            event.get('partial')
            or event.get('branch')
            or any(event.get(key) for key in ('error', 'error_code', 'errorCode'))
        ):
            return None
        content = event.get('content')
        if not isinstance(content, dict):
            return None
        author = event.get('author')
        role = content.get('role')
        if author == 'user' and role == 'user':
            public_role = 'user'
        elif author == self._configuration.public_agent_name and role == 'model':
            public_role = 'assistant'
        else:
            return None
        parts = content.get('parts')
        if not isinstance(parts, list) or any(
            not isinstance(part, dict) for part in parts
        ):
            raise ValueError('Invalid message parts.')
        if any(
            any(
                part.get(key)
                for key in (
                    'function_call',
                    'functionCall',
                    'function_response',
                    'functionResponse',
                )
            )
            for part in parts
        ):
            return None
        texts: list[str] = []
        for part in parts:
            if part.get('thought') or 'text' not in part:
                continue
            if not isinstance(part['text'], str):
                raise TypeError('Invalid public text.')
            texts.append(part['text'])
        text = ''.join(texts)
        if not text.strip():
            return None
        message_id = event.get('id')
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError('Missing public event ID.')
        return ConversationMessage(
            message_id=message_id,
            role=public_role,
            text=text,
            created_at=self._timestamp(event.get('timestamp')),
        )

    @staticmethod
    def _timestamp(value: object) -> datetime:
        """
        Convert a finite nonnegative SDK Unix timestamp to timezone-aware UTC.

        :param value: Timestamp from a persisted session or selected public event.

        :return: Timezone-aware UTC timestamp.

        :raises ValueError: If the timestamp is not a finite nonnegative number.
        :raises OverflowError: If the timestamp exceeds the supported date range.
        :raises OSError: If the platform cannot represent the timestamp.
        """
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError('Invalid persisted timestamp.')
        return datetime.fromtimestamp(value, tz=UTC)
