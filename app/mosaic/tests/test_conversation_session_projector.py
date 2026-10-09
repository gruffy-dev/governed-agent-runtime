import unittest
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from pydantic import ValidationError

from mosaic.components.ada.ada_application_error import AdaApplicationError
from mosaic.components.api.conversation_session_projector import ConversationSessionProjector
from mosaic.models.api.conversation_projection_configuration import ConversationProjectionConfiguration


class TestConversationSessionProjector(unittest.TestCase):
    def setUp(self) -> None:
        self.projector = ConversationSessionProjector(
            ConversationProjectionConfiguration(public_agent_name='synthetic-agent')
        )
        self.created_at = datetime.fromtimestamp(1, tz=UTC)
        self.session: dict[str, Any] = {
            'id': str(uuid4()),
            'lastUpdateTime': 30,
            'events': [],
            'state': {'synthetic-internal-state': 'not-public'},
        }

    def _event(
        self, event_id: str, author: str, role: str, timestamp: int, text: str
    ) -> dict[str, Any]:
        return {
            'id': event_id,
            'author': author,
            'timestamp': timestamp,
            'content': {'role': role, 'parts': [{'text': text}]},
        }

    def test_empty_session_uses_authoritative_creation_time(self) -> None:
        result = self.projector.detail(self.session, created_at=self.created_at)
        self.assertEqual(result.created_at, self.created_at)
        self.assertEqual(result.last_activity_at, datetime.fromtimestamp(30, tz=UTC))
        self.assertEqual(result.messages, ())
        self.assertIsNone(result.title)
        self.assertNotIn('state', result.model_dump())

    def test_history_order_and_public_fields(self) -> None:
        self.session['events'] = [
            self._event('answer', 'synthetic-agent', 'model', 20, 'Hello.'),
            self._event('prompt', 'user', 'user', 10, '  First\n prompt  '),
        ]
        result = self.projector.detail(self.session, created_at=self.created_at)
        self.assertEqual(
            [message.message_id for message in result.messages], ['prompt', 'answer']
        )
        self.assertEqual(
            [message.role for message in result.messages], ['user', 'assistant']
        )
        self.assertEqual(result.title, 'First prompt')
        self.assertEqual(result.messages[0].text, '  First\n prompt  ')
        self.assertEqual(
            set(result.messages[1].model_dump()),
            {'message_id', 'role', 'text', 'created_at'},
        )

    def test_thought_partial_branch_internal_author_and_error_are_hidden(self) -> None:
        answer = self._event('answer', 'synthetic-agent', 'model', 20, 'Visible.')
        self.session['events'] = [
            dict(answer, id='partial', partial=True),
            dict(answer, id='branch', branch='synthetic-private-branch'),
            dict(answer, id='internal', author='synthetic-internal-agent'),
            dict(answer, id='error', errorCode='synthetic-error'),
            dict(
                answer,
                id='thought',
                content={
                    'role': 'model',
                    'parts': [{'text': 'synthetic-private-thought', 'thought': True}],
                },
            ),
            answer,
        ]
        result = self.projector.detail(self.session, created_at=self.created_at)
        self.assertEqual(len(result.messages), 1)
        self.assertEqual(result.messages[0].text, 'Visible.')
        self.assertNotIn('synthetic-private', result.model_dump_json())

    def test_tool_events_are_hidden_even_with_text_and_user_role(self) -> None:
        for key in (
            'function_call',
            'functionCall',
            'function_response',
            'functionResponse',
        ):
            for author, role in (('user', 'user'), ('synthetic-agent', 'model')):
                with self.subTest(key=key, author=author):
                    event = self._event(
                        'tool', author, role, 10, 'synthetic-private-tool-text'
                    )
                    event['content']['parts'].append(
                        {
                            key: {
                                'name': 'synthetic-tool',
                                'response': 'synthetic-private-payload',
                            }
                        }
                    )
                    self.session['events'] = [event]
                    self.assertEqual(
                        self.projector.detail(
                            self.session, created_at=self.created_at
                        ).messages,
                        (),
                    )

    def test_mixed_thought_and_text_parts_expose_only_text(self) -> None:
        event = self._event('answer', 'synthetic-agent', 'model', 20, 'Hello ')
        event['content']['parts'] += [
            {'text': 'synthetic-private-thought', 'thought': True},
            {'text': 'world.'},
            {'inlineData': {'data': 'synthetic-binary-placeholder'}},
        ]
        self.session['events'] = [event]
        result = self.projector.detail(self.session, created_at=self.created_at)
        self.assertEqual(result.messages[0].text, 'Hello world.')
        self.assertNotIn('synthetic-private', result.model_dump_json())

    def test_summary_and_title_configuration(self) -> None:
        projector = ConversationSessionProjector(
            ConversationProjectionConfiguration(
                public_agent_name='synthetic-agent', title_maximum_characters=5
            )
        )
        self.session['events'] = [
            self._event('prompt', 'user', 'user', 10, 'Hello world')
        ]
        result = projector.summary(self.session, created_at=self.created_at)
        self.assertEqual(result.title, 'Hello')
        self.assertNotIn('messages', result.model_dump())

    def test_snake_case_activity_time_and_conflicting_aliases(self) -> None:
        self.session['last_update_time'] = self.session.pop('lastUpdateTime')
        self.assertEqual(
            self.projector.detail(
                self.session, created_at=self.created_at
            ).last_activity_at.timestamp(),
            30,
        )
        self.session['lastUpdateTime'] = 31
        with self.assertRaises(AdaApplicationError):
            self.projector.detail(self.session, created_at=self.created_at)

    def test_missing_or_invalid_session_fields_fail_safely(self) -> None:
        for updates in (
            {'id': 'invalid'},
            {'events': None},
            {'events': ['invalid']},
            {'lastUpdateTime': True},
            {'lastUpdateTime': float('nan')},
            {'lastUpdateTime': float('inf')},
            {'lastUpdateTime': -1},
            {'lastUpdateTime': 1e100},
        ):
            with self.subTest(updates=updates), self.assertRaises(AdaApplicationError):
                self.projector.detail(
                    dict(self.session, **updates), created_at=self.created_at
                )
        for key in ('events', 'id', 'lastUpdateTime'):
            record = dict(self.session)
            record.pop(key)
            with self.subTest(key=key), self.assertRaises(AdaApplicationError):
                self.projector.detail(record, created_at=self.created_at)

    def test_invalid_public_message_metadata_and_duplicates(self) -> None:
        event = self._event('answer', 'synthetic-agent', 'model', 20, 'Hello.')
        for changes in (
            {'id': ''},
            {'timestamp': None},
            {'timestamp': False},
            {
                'content': {
                    'role': 'model',
                    'parts': [{'text': {'synthetic-private': 'payload'}}],
                }
            },
        ):
            self.session['events'] = [dict(event, **changes)]
            with (
                self.subTest(changes=changes),
                self.assertRaises(AdaApplicationError) as caught,
            ):
                self.projector.detail(self.session, created_at=self.created_at)
            self.assertNotIn('synthetic-private', str(caught.exception))
        self.session['events'] = [event, event]
        with self.assertRaises(AdaApplicationError):
            self.projector.detail(self.session, created_at=self.created_at)

    def test_naive_creation_time_is_rejected(self) -> None:
        with self.assertRaises(AdaApplicationError):
            self.projector.detail(
                self.session, created_at=self.created_at.replace(tzinfo=None)
            )

    def test_configuration_environment_and_validation(self) -> None:
        with patch.dict(
            'os.environ',
            {
                'MOSAIC_PUBLIC_AGENT_NAME': 'synthetic-agent',
                'MOSAIC_CONVERSATION_TITLE_MAXIMUM_CHARACTERS': '25',
            },
        ):
            configuration = ConversationProjectionConfiguration()
        self.assertEqual(configuration.public_agent_name, 'synthetic-agent')
        self.assertEqual(configuration.title_maximum_characters, 25)
        with self.assertRaises(ValidationError):
            ConversationProjectionConfiguration(title_maximum_characters=0)
