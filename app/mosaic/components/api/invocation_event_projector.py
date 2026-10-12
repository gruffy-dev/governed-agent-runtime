from typing import Any, Literal
from uuid import UUID

from ..ada.ada_application_error import AdaApplicationError
from ...models.api.api_error_response import ApiErrorResponse
from ...models.api.conversation_projection_configuration import ConversationProjectionConfiguration
from ...models.api.invocation_stream_configuration import InvocationStreamConfiguration
from ...models.api.invocation_stream_event import InvocationStreamEvent


class InvocationEventProjector:
    def __init__(
        self,
        conversation_id: UUID,
        invocation_id: UUID,
        correlation_id: UUID,
        projection_configuration: ConversationProjectionConfiguration,
        stream_configuration: InvocationStreamConfiguration,
    ) -> None:
        """
        Bind one invocation's public events to server-owned identities and limits.

        :param conversation_id: Owned public conversation UUID.
        :param invocation_id: Backend-generated public invocation UUID, not the ADA ID.
        :param correlation_id: Backend-generated correlation shared by the stream.
        :param projection_configuration: Exact agent author permitted to supply public text.
        :param stream_configuration: Bounds for retained model-turn text.
        """
        self._conversation_id = conversation_id
        self._invocation_id = invocation_id
        self._correlation_id = correlation_id
        self._author = projection_configuration.public_agent_name
        self._maximum_characters = stream_configuration.maximum_turn_characters
        self._private_invocation_id: str | None = None
        self._partial_text = ''
        self._confirmed_final = False
        self._started = False
        self._terminal = False

    def start(self) -> InvocationStreamEvent:
        """
        Emit exactly one started event before processing private records.

        :return: Public started event without private ADA metadata.

        :raises AdaApplicationError: If the projector was already started.
        """
        if self._started:
            raise AdaApplicationError('Public invocation stream has already started.')
        self._started = True
        return self._event('started')

    def accept(self, record: dict[str, Any]) -> tuple[InvocationStreamEvent, ...]:
        """
        Project private delta text while rejecting errors and mismatched turns.

        Ignore user, branch, thought and tool content. Final aggregate text must
        agree with already emitted deltas; emit only any missing suffix. A valid
        final public model event is necessary before EOF can confirm completion.

        :param record: Complete JSON object from the private SSE decoder.

        :return: Public text delta, safe terminal failure, or no public event.

        :raises AdaApplicationError: If records arrive before start or after termination.
        """
        self._require_active()
        try:
            if any(
                record.get(key)
                for key in (
                    'error',
                    'error_details',
                    'errorCode',
                    'error_code',
                    'errorMessage',
                    'error_message',
                )
            ):
                return (self.fail(),)
            if record.get('interrupted'):
                return (self.fail(),)
            finish_reason = self._alias(record, 'finishReason', 'finish_reason')
            if finish_reason not in (None, 'STOP'):
                return (self.fail(),)
            private_id = self._alias(record, 'invocationId', 'invocation_id')
            if not isinstance(private_id, str) or not private_id:
                raise ValueError('Missing private invocation identity.')
            if self._private_invocation_id is None:
                self._private_invocation_id = private_id
            elif private_id != self._private_invocation_id:
                raise ValueError('Mixed private invocation identities.')
            if record.get('branch') or record.get('author') != self._author:
                return ()
            content = record.get('content')
            if not isinstance(content, dict) or content.get('role') != 'model':
                return ()
            partial = record.get('partial', False)
            if not isinstance(partial, bool):
                raise TypeError('Invalid partial marker.')
            self._confirmed_final = False
            parts = content.get('parts')
            if not isinstance(parts, list) or any(
                not isinstance(part, dict) for part in parts
            ):
                raise ValueError('Invalid model content parts.')
            if any(
                any(
                    part.get(key)
                    for key in (
                        'functionCall',
                        'function_call',
                        'functionResponse',
                        'function_response',
                    )
                )
                for part in parts
            ):
                self._confirmed_final = False
                if not partial:
                    self._partial_text = ''
                return ()
            texts = [
                part['text']
                for part in parts
                if 'text' in part and not part.get('thought')
            ]
            if any(not isinstance(text, str) for text in texts):
                raise ValueError('Invalid public model text.')
            text = ''.join(texts)
            if not text:
                return ()
            if len(text) > self._maximum_characters:
                raise ValueError('Model turn exceeded its limit.')
            if partial:
                if len(self._partial_text) + len(text) > self._maximum_characters:
                    raise ValueError('Streamed model turn exceeded its limit.')
                self._partial_text += text
                return (self._event('text_delta', text=text),)
            if not text.startswith(self._partial_text):
                raise ValueError('Final model text disagreed with streamed deltas.')
            suffix = text[len(self._partial_text) :]
            self._partial_text = ''
            self._confirmed_final = True
            return () if not suffix else (self._event('text_delta', text=suffix),)
        except (TypeError, ValueError):
            return (self.fail(),)

    def finish(self) -> InvocationStreamEvent:
        """
        Confirm success only after a valid final model event and clean decoder EOF.

        Call only after the private decoder and transport finish successfully.
        An error record already emits failed and must stop stream processing.

        :return: Completed event, or safe failure for unconfirmed completion.

        :raises AdaApplicationError: If the stream has not started or is terminal.
        """
        self._require_active()
        if not self._confirmed_final or self._partial_text:
            return self.fail()
        self._terminal = True
        return self._event('completed')

    def fail(self) -> InvocationStreamEvent:
        """
        Emit one safe failure without copying upstream error fields or text.

        :return: Terminal failed event with the public stream's correlation ID.

        :raises AdaApplicationError: If the stream has not started or is terminal.
        """
        self._require_active()
        self._terminal = True
        self._partial_text = ''
        return self._event(
            'failed',
            error=ApiErrorResponse(
                detail='Invocation failed',
                error_code='invocation_failed',
                action='Refresh the conversation and check its status before retrying.',
                correlation_id=self._correlation_id,
            ),
        )

    @staticmethod
    def encode(event: InvocationStreamEvent) -> bytes:
        """
        Frame a validated public event without allowing text to inject SSE fields.

        :param event: MOSAIC-owned event containing only public protocol fields.

        :return: UTF-8 named SSE event with JSON-escaped text and a blank delimiter.
        """
        return f'event: {event.event}\ndata: {event.model_dump_json()}\n\n'.encode()

    def _require_active(self) -> None:
        """
        Require exactly one started stream that has not emitted a terminal event.

        :raises AdaApplicationError: If the projector cannot accept more events.
        """
        if not self._started or self._terminal:
            raise AdaApplicationError('Public invocation stream is not active.')

    def _event(
        self,
        kind: Literal['started', 'text_delta', 'completed', 'failed'],
        *,
        text: str | None = None,
        error: ApiErrorResponse | None = None,
    ) -> InvocationStreamEvent:
        """
        Construct a public event exclusively from backend-owned identity and payload.

        :param kind: Selected public SSE event name.
        :param text: Optional allowlisted incremental assistant text.
        :param error: Optional generic correlated failure envelope.

        :return: Validated public protocol event.
        """
        return InvocationStreamEvent(
            event=kind,
            conversation_id=self._conversation_id,
            invocation_id=self._invocation_id,
            correlation_id=self._correlation_id,
            text=text,
            error=error,
        )

    @staticmethod
    def _alias(record: dict[str, Any], camel: str, snake: str) -> object:
        """
        Read a documented wire field without accepting contradictory aliases.

        :param record: Private event object.
        :param camel: JSON alias used on the wire.
        :param snake: Python field name accepted by synthetic or alternate serializers.

        :return: Field value, or None when absent.

        :raises ValueError: If both aliases disagree.
        """
        if camel in record and snake in record and record[camel] != record[snake]:
            raise ValueError('Private event aliases disagree.')
        return record.get(camel, record.get(snake))
