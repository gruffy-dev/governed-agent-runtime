import unittest
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from mosaic.models.api.api_error_response import ApiErrorResponse
from mosaic.models.api.conversation_detail import ConversationDetail
from mosaic.models.api.conversation_message import ConversationMessage
from mosaic.models.api.create_conversation_request import CreateConversationRequest
from mosaic.models.api.invocation_status import InvocationStatus
from mosaic.models.api.invocation_stream_event import InvocationStreamEvent
from mosaic.models.api.submit_message_request import SubmitMessageRequest


class TestConversationApiModels(unittest.TestCase):
    def test_requests_reject_caller_owned_identity_and_state(self) -> None:
        for field in (
            'user_id',
            'app_name',
            'workspace_id',
            'state',
            'skill_ids',
            'conversation_id',
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError):
                    CreateConversationRequest.model_validate({field: 'claimed-value'})
                with self.assertRaises(ValidationError):
                    SubmitMessageRequest.model_validate(
                        {'text': 'A question', field: 'claimed-value'}
                    )
        self.assertEqual(CreateConversationRequest().model_dump(), {})

    def test_message_validation_preserves_text_and_rejects_blank(self) -> None:
        self.assertEqual(
            SubmitMessageRequest(text='  A question\n').text, '  A question\n'
        )
        for text in ('', ' \n\t'):
            with self.subTest(text=text), self.assertRaises(ValidationError):
                SubmitMessageRequest(text=text)

    def test_history_contains_only_public_messages_with_aware_timestamps(self) -> None:
        now = datetime.now(UTC)
        message = ConversationMessage(
            message_id='synthetic-message',
            role='assistant',
            text='A public response',
            created_at=now,
        )
        conversation = ConversationDetail(
            conversation_id=uuid4(),
            title='A question',
            created_at=now,
            last_activity_at=now,
            messages=(message,),
        )
        self.assertEqual(
            conversation.model_dump(mode='json')['messages'][0]['text'],
            'A public response',
        )
        with self.assertRaises(ValidationError):
            ConversationMessage(
                message_id='synthetic-tool-message',
                role='tool',
                text='internal',
                created_at=now,
            )
        with self.assertRaises(ValidationError):
            ConversationMessage(
                message_id='synthetic-message',
                role='user',
                text='A question',
                created_at=now.replace(tzinfo=None),
            )
        with self.assertRaises(ValidationError):
            conversation.title = 'Another title'

    def test_idle_and_active_status_have_consistent_identifiers(self) -> None:
        conversation_id = uuid4()
        InvocationStatus(
            conversation_id=conversation_id, invocation_id=None, status='idle'
        )
        for status in ('working', 'completed', 'failed', 'cancelled', 'interrupted'):
            with self.subTest(status=status):
                InvocationStatus(
                    conversation_id=conversation_id,
                    invocation_id=uuid4(),
                    status=status,
                )
                with self.assertRaises(ValidationError):
                    InvocationStatus(
                        conversation_id=conversation_id,
                        invocation_id=None,
                        status=status,
                    )
        with self.assertRaises(ValidationError):
            InvocationStatus(
                conversation_id=conversation_id, invocation_id=uuid4(), status='idle'
            )

    def test_stream_events_enforce_payload_and_correlation_rules(self) -> None:
        identity = {
            'conversation_id': uuid4(),
            'invocation_id': uuid4(),
            'correlation_id': uuid4(),
        }
        for event in ('started', 'completed', 'cancelled'):
            with self.subTest(event=event):
                InvocationStreamEvent(event=event, **identity)
                with self.assertRaises(ValidationError):
                    InvocationStreamEvent(
                        event=event, text='unexpected text', **identity
                    )
        InvocationStreamEvent(event='text_delta', text='  ', **identity)
        with self.assertRaises(ValidationError):
            InvocationStreamEvent(event='text_delta', **identity)
        with self.assertRaises(ValidationError):
            InvocationStreamEvent(event='failed', **identity)
        error = ApiErrorResponse(
            detail='Invocation failed.',
            error_code='invocation_failed',
            action='Check invocation status before submitting another message.',
            correlation_id=identity['correlation_id'],
        )
        InvocationStreamEvent(event='failed', error=error, **identity)
        with self.assertRaises(ValidationError):
            InvocationStreamEvent(event='completed', error=error, **identity)
        with self.assertRaises(ValidationError):
            InvocationStreamEvent(
                event='failed',
                error=error.model_copy(update={'correlation_id': uuid4()}),
                **identity,
            )
