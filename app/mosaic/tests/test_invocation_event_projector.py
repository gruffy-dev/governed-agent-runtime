import json
import unittest
from typing import Any
from uuid import uuid4

from mosaic.components.ada.ada_application_error import AdaApplicationError
from mosaic.components.ada.ada_sse_event_decoder import AdaSseEventDecoder
from mosaic.components.api.invocation_event_projector import InvocationEventProjector
from mosaic.models.api.conversation_projection_configuration import ConversationProjectionConfiguration
from mosaic.models.api.invocation_stream_configuration import InvocationStreamConfiguration


class TestInvocationEventProjector(unittest.TestCase):
    def setUp(self) -> None:
        self.conversation_id = uuid4()
        self.invocation_id = uuid4()
        self.correlation_id = uuid4()
        self.projector = self._projector()
        self.started = self.projector.start()

    def _projector(self, maximum_characters: int = 1024) -> InvocationEventProjector:
        return InvocationEventProjector(
            self.conversation_id,
            self.invocation_id,
            self.correlation_id,
            ConversationProjectionConfiguration(public_agent_name='synthetic-agent'),
            InvocationStreamConfiguration(maximum_turn_characters=maximum_characters),
        )

    def _record(
        self, text: str, *, partial: bool = False, **fields: Any
    ) -> dict[str, Any]:
        return {
            'invocationId': 'synthetic-private-invocation',
            'id': str(uuid4()),
            'author': 'synthetic-agent',
            'partial': partial,
            'content': {'role': 'model', 'parts': [{'text': text}]},
            **fields,
        }

    def test_deltas_plus_repeated_final_do_not_duplicate_text(self) -> None:
        events = list(self.projector.accept(self._record('Hello ', partial=True)))
        events += self.projector.accept(self._record('world.', partial=True))
        self.assertEqual(
            self.projector.accept(self._record('Hello world.', finishReason='STOP')), ()
        )
        self.assertEqual(''.join(event.text for event in events), 'Hello world.')
        self.assertEqual(self.projector.finish().event, 'completed')

    def test_final_only_and_missing_suffix_produce_exact_text(self) -> None:
        self.assertEqual(
            self.projector.accept(self._record('Final-only reply'))[0].text,
            'Final-only reply',
        )
        second = self._projector()
        second.start()
        self.assertEqual(
            second.accept(self._record('Hello', partial=True))[0].text, 'Hello'
        )
        self.assertEqual(second.accept(self._record('Hello world'))[0].text, ' world')
        self.assertEqual(second.finish().event, 'completed')

    def test_multiple_model_turns_reset_delta_reconciliation(self) -> None:
        self.projector.accept(self._record('First ', partial=True))
        self.projector.accept(self._record('First turn'))
        self.projector.accept(self._record('Second ', partial=True))
        self.assertEqual(
            self.projector.accept(self._record('Second turn'))[0].text, 'turn'
        )
        self.assertEqual(self.projector.finish().event, 'completed')

    def test_user_other_author_branch_tool_and_thought_text_are_not_exposed(
        self,
    ) -> None:
        for record in (
            self._record('synthetic-private', author='user'),
            self._record('synthetic-private', author='other-agent'),
            self._record('synthetic-private', branch='private-branch'),
            self._record(
                'synthetic-private',
                content={'role': 'user', 'parts': [{'text': 'synthetic-private'}]},
            ),
            self._record(
                'unused',
                content={
                    'role': 'model',
                    'parts': [{'text': 'synthetic-private', 'thought': True}],
                },
            ),
        ):
            self.assertEqual(self.projector.accept(record), ())
        for key in (
            'functionCall',
            'function_call',
            'functionResponse',
            'function_response',
        ):
            record = self._record('synthetic-private')
            record['content']['parts'].append({key: {'name': 'synthetic-private-tool'}})
            self.assertEqual(self.projector.accept(record), ())
        public = self.projector.accept(
            self._record(
                'unused',
                content={
                    'role': 'model',
                    'parts': [
                        {'text': 'Hello '},
                        {'text': 'synthetic-private-thought', 'thought': True},
                        {'text': 'world'},
                    ],
                },
            )
        )[0]
        self.assertEqual(public.text, 'Hello world')
        self.assertNotIn('synthetic-private', public.model_dump_json())

    def test_generator_model_and_finish_reason_failures_are_generic(self) -> None:
        for record in (
            {
                'error': 'synthetic-private-error',
                'error_details': 'synthetic-private-details',
            },
            self._record(
                'synthetic-private',
                errorCode='synthetic-private-error',
                errorMessage='synthetic-private-details',
            ),
            self._record('synthetic-private', error_code='synthetic-private-error'),
            self._record('synthetic-private', finishReason='MAX_TOKENS'),
            self._record('synthetic-private', finish_reason='SAFETY'),
            self._record('synthetic-private', interrupted=True),
        ):
            projector = self._projector()
            projector.start()
            failed = projector.accept(record)[0]
            self.assertEqual(failed.event, 'failed')
            self.assertEqual(failed.error.error_code, 'invocation_failed')
            self.assertEqual(failed.error.correlation_id, failed.correlation_id)
            self.assertNotIn('synthetic-private', failed.model_dump_json())

    def test_eof_without_confirmed_final_is_failure(self) -> None:
        self.assertEqual(self.projector.finish().event, 'failed')
        projector = self._projector()
        projector.start()
        projector.accept(self._record('Incomplete partial', partial=True))
        self.assertEqual(projector.finish().event, 'failed')

    def test_final_followed_by_new_unfinished_turn_does_not_confirm_success(
        self,
    ) -> None:
        self.projector.accept(self._record('Complete first turn'))
        self.projector.accept(self._record('Next partial', partial=True))
        self.assertEqual(self.projector.finish().event, 'failed')

    def test_error_after_valid_final_still_fails(self) -> None:
        self.projector.accept(self._record('A complete reply'))
        self.assertEqual(
            self.projector.accept({'error': 'synthetic-private-error'})[0].event,
            'failed',
        )

    def test_identity_aliases_and_partial_shapes_fail_closed(self) -> None:
        for update in (
            {'invocationId': None},
            {'invocation_id': 'different-private-id'},
            {'partial': 'false'},
            {'finish_reason': 'SAFETY', 'finishReason': 'STOP'},
            {'content': {'role': 'model', 'parts': [{'text': 123}]}},
        ):
            projector = self._projector()
            projector.start()
            self.assertEqual(
                projector.accept(self._record('Hello', **update))[0].event, 'failed'
            )
        self.projector.accept(self._record('Hello', partial=True))
        self.assertEqual(
            self.projector.accept(
                self._record('Hello', invocationId='another-private-id')
            )[0].event,
            'failed',
        )

    def test_final_disagreement_and_text_limits_fail_closed(self) -> None:
        self.projector.accept(self._record('Hello', partial=True))
        self.assertEqual(
            self.projector.accept(self._record('Different text'))[0].event, 'failed'
        )
        for partial in (True, False):
            projector = self._projector(maximum_characters=4)
            projector.start()
            self.assertEqual(
                projector.accept(self._record('Hello', partial=partial))[0].event,
                'failed',
            )
        projector = self._projector(maximum_characters=4)
        projector.start()
        projector.accept(self._record('abc', partial=True))
        self.assertEqual(
            projector.accept(self._record('de', partial=True))[0].event, 'failed'
        )

    def test_start_terminal_and_encoding_use_public_protocol_only(self) -> None:
        self.assertEqual(self.started.event, 'started')
        with self.assertRaises(AdaApplicationError):
            self.projector.start()
        text = 'Hello\n\nevent: injected\ndata: café'
        event = self.projector.accept(self._record(text))[0]
        frame = self.projector.encode(event).decode('utf-8')
        self.assertEqual(frame.count('\n'), 3)
        self.assertTrue(frame.startswith('event: text_delta\ndata: '))
        payload = json.loads(frame.splitlines()[1].removeprefix('data: '))
        self.assertEqual(payload['text'], text)
        self.assertEqual(payload['invocation_id'], str(self.invocation_id))
        self.assertNotIn('synthetic-private-invocation', frame)
        self.projector.finish()
        with self.assertRaises(AdaApplicationError):
            self.projector.finish()
        with self.assertRaises(AdaApplicationError):
            self.projector.accept(self._record('Another reply'))

    def test_fragmented_private_stream_projects_one_public_text_and_terminal(
        self,
    ) -> None:
        decoder = AdaSseEventDecoder(InvocationStreamConfiguration())
        payload = b''.join(
            (f'data: {json.dumps(record)}\n\n'.encode())
            for record in (
                self._record('Hello ', partial=True),
                self._record('world', partial=True),
                self._record('Hello world', finishReason='STOP'),
            )
        )
        projected = [self.started]
        for index in range(0, len(payload), 7):
            for record in decoder.feed(payload[index : index + 7]):
                projected.extend(self.projector.accept(record))
        decoder.finish()
        projected.append(self.projector.finish())
        self.assertEqual(
            [event.event for event in projected],
            ['started', 'text_delta', 'text_delta', 'completed'],
        )
        self.assertEqual(
            ''.join(event.text or '' for event in projected), 'Hello world'
        )
