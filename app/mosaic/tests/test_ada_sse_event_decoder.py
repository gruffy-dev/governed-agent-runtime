import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from mosaic.components.ada.ada_application_error import AdaApplicationError
from mosaic.components.ada.ada_sse_event_decoder import AdaSseEventDecoder
from mosaic.models.api.invocation_stream_configuration import InvocationStreamConfiguration


class TestAdaSseEventDecoder(unittest.TestCase):
    def test_fragmented_unicode_and_multiple_events(self) -> None:
        records = [{'text': 'Synthetic café'}, {'text': 'Synthetic reply'}]
        payload = ''.join(
            f'data: {json.dumps(record, ensure_ascii=False)}\n\n' for record in records
        ).encode('utf-8')
        decoder = AdaSseEventDecoder(InvocationStreamConfiguration())
        result = []
        for value in payload:
            result.extend(decoder.feed(bytes([value])))
        decoder.finish()
        self.assertEqual(result, records)

    def test_lf_crlf_cr_and_multiline_data(self) -> None:
        for ending in ('\n', '\r\n', '\r'):
            with self.subTest(ending=repr(ending)):
                decoder = AdaSseEventDecoder(InvocationStreamConfiguration())
                payload = ending.join(
                    [
                        ': synthetic comment',
                        'event: private',
                        'id: private-id',
                        'retry: 100',
                        'data: {',
                        'data: "value": "synthetic"}',
                        '',
                        '',
                    ]
                ).encode('utf-8')
                result = []
                for value in payload:
                    result.extend(decoder.feed(bytes([value])))
                decoder.finish()
                self.assertEqual(result, [{'value': 'synthetic'}])

    def test_comment_and_empty_frames_do_not_produce_records(self) -> None:
        decoder = AdaSseEventDecoder(InvocationStreamConfiguration())
        self.assertEqual(list(decoder.feed(b': keepalive\n\n\n\n')), [])
        decoder.finish()

    def test_truncated_frame_is_not_accepted_at_eof(self) -> None:
        for payload in (
            b'data: {"value": 1}',
            b'data: {"value": 1}\n',
            b'data: {"value":',
        ):
            with self.subTest(payload=payload):
                decoder = AdaSseEventDecoder(InvocationStreamConfiguration())
                self.assertEqual(list(decoder.feed(payload)), [])
                with self.assertRaises(AdaApplicationError):
                    decoder.finish()

    def test_invalid_json_utf8_shape_and_nonfinite_numbers_fail_safely(self) -> None:
        for payload in (
            b'data: synthetic-private-secret\n\n',
            b'data: []\n\n',
            b'data: null\n\n',
            b'data: {"value": NaN}\n\n',
            b'data: {"value": Infinity}\n\n',
            b'data: \xff\n\n',
            b'data: {"value": "\\ud800"}\n\n',
        ):
            with self.subTest(payload=payload):
                decoder = AdaSseEventDecoder(InvocationStreamConfiguration())
                with self.assertRaises(AdaApplicationError) as caught:
                    list(decoder.feed(payload))
                self.assertNotIn('synthetic-private-secret', str(caught.exception))
                with self.assertRaises(AdaApplicationError):
                    list(decoder.feed(b'data: {}\n\n'))

    def test_frame_limit_includes_ignored_fields_and_fragmented_data(self) -> None:
        for payload in (
            b'data: {"value":"' + b'x' * 40,
            b': ' + b'x' * 40,
            b'event: ' + b'x' * 40,
        ):
            with self.subTest(payload=payload):
                decoder = AdaSseEventDecoder(
                    InvocationStreamConfiguration(maximum_event_bytes=32)
                )
                with self.assertRaises(AdaApplicationError):
                    for value in payload:
                        list(decoder.feed(bytes([value])))

    def test_limit_applies_per_frame_not_per_transport_chunk(self) -> None:
        decoder = AdaSseEventDecoder(
            InvocationStreamConfiguration(maximum_event_bytes=16)
        )
        self.assertEqual(list(decoder.feed(b'data: {}\n\n' * 10)), [{}] * 10)
        decoder.finish()

    def test_closed_decoder_rejects_more_input(self) -> None:
        decoder = AdaSseEventDecoder(InvocationStreamConfiguration())
        decoder.finish()
        with self.assertRaises(AdaApplicationError):
            list(decoder.feed(b'data: {}\n\n'))

    def test_configuration_is_externalised_and_validated(self) -> None:
        with patch.dict(
            'os.environ',
            {
                'MOSAIC_INVOCATION_MAXIMUM_EVENT_BYTES': '64',
                'MOSAIC_INVOCATION_MAXIMUM_TURN_CHARACTERS': '128',
            },
        ):
            configuration = InvocationStreamConfiguration()
        self.assertEqual(configuration.maximum_event_bytes, 64)
        self.assertEqual(configuration.maximum_turn_characters, 128)
        with self.assertRaises(ValidationError):
            InvocationStreamConfiguration(maximum_event_bytes=0)
