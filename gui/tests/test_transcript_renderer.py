import unittest

from dash import dcc
from dash_extensions import Mermaid
from mosaic_gui.gui_application import GuiApplication
from mosaic_gui.gui_configuration import GuiConfiguration
from mosaic_gui.transcript_renderer import TranscriptRenderer


class TestTranscriptRenderer(unittest.TestCase):
    def test_diagram_retains_exact_source_and_surrounding_markdown(self) -> None:
        source = 'flowchart LR\r\n  A[Request] --> B[Response]\r\n'
        parts = TranscriptRenderer._parts(
            '# Result\r\n\r\n```mermaid\r\n' + source + '```\r\n\r\nNext steps.',
            '1-0',
        )
        self.assertEqual(len(parts), 3)
        self.assertIsInstance(parts[0], dcc.Markdown)
        self.assertEqual(parts[0].children, '# Result\r\n\r\n')
        self.assertIsInstance(parts[1].children[0], Mermaid)
        self.assertEqual(parts[1].children[0].chart, source)
        self.assertEqual(parts[1].children[-1].children[0].children[1].children, source)
        self.assertEqual(parts[1].children[-1].children[1].children[1].content, source)
        self.assertEqual(parts[2].children, '\r\nNext steps.')

    def test_incomplete_fences_and_other_code_blocks_remain_markdown(self) -> None:
        for text in (
            '```mermaid\nflowchart LR\nA --> B',
            '````markdown\n```mermaid\nA --> B\n```\n````\n',
            '```python\nprint("mermaid")\n```\n',
        ):
            with self.subTest(text=text):
                parts = TranscriptRenderer._parts(text, '1-0')
                self.assertEqual(len(parts), 1)
                self.assertIsInstance(parts[0], dcc.Markdown)
                self.assertEqual(parts[0].children, text)
                self.assertFalse(parts[0].dangerously_allow_html)

    def test_multiple_diagrams_have_independent_copy_controls(self) -> None:
        parts = TranscriptRenderer._parts(
            '~~~mermaid\nflowchart LR\nA --> B\n~~~\n'
            '```mermaid\nsequenceDiagram\nA->>B: Hello\n```\n',
            '5-2',
        )
        self.assertEqual(len(parts), 2)
        copies = [part.children[-1].children[1].children[1] for part in parts]
        self.assertNotEqual(copies[0].id, copies[1].id)
        self.assertIn('flowchart', copies[0].content)
        self.assertIn('sequenceDiagram', copies[1].content)

    def test_unsafe_configuration_and_oversized_diagrams_retain_source(self) -> None:
        for source in (
            '%%{init: {"securityLevel":"loose"}}%%\nflowchart LR\nA --> B\n',
            '---\nconfig:\n  securityLevel: loose\n---\nflowchart LR\nA --> B\n',
            'flowchart LR\nA --> B\nclick A "https://example.com"\n',
            'a' * 50001,
        ):
            with self.subTest(source=source[:40]):
                card = TranscriptRenderer._diagram(source, '3-1')
                self.assertFalse(any(isinstance(child, Mermaid) for child in card.children))
                self.assertEqual(card.children[-1].children[1].children[1].content, source)

    def test_user_text_is_literal_and_render_results_retain_generation(self) -> None:
        text = '```mermaid\nflowchart LR\nA --> B\n```\n'
        result = TranscriptRenderer.render({
            'sequence': 17,
            'messages': [
                {'role': 'user', 'text': text},
                {'role': 'assistant', 'text': text},
            ],
        })
        self.assertEqual(result['sequence'], 17)
        self.assertEqual(result['children'][0].children[1].children, text)
        self.assertEqual(result['children'][0].children[0].children, 'You')
        self.assertEqual(result['children'][1].children[0].children, 'MOSAIC')

    def test_dash_callback_serves_components_from_local_assets(self) -> None:
        application = GuiApplication.create_application(GuiConfiguration())
        client = application.server.test_client()
        response = client.post('/_dash-update-component', json={
            'output': 'transcript-render-result.data',
            'outputs': {'id': 'transcript-render-result', 'property': 'data'},
            'inputs': [{'id': 'transcript-render-request', 'property': 'data', 'value': {
                'sequence': 7,
                'messages': [{'role': 'assistant', 'text': '```mermaid\nflowchart LR\nA --> B\n```'}],
            }}],
            'state': [], 'changedPropIds': ['transcript-render-request.data'],
        })
        self.assertEqual(response.status_code, 200)
        result = response.get_json()['response']['transcript-render-result']['data']
        self.assertEqual(result['sequence'], 7)
        component = result['children'][0]['props']['children'][1]['props']['children'][0]['props']['children'][0]
        self.assertEqual(component['namespace'], 'dash_extensions')
        self.assertEqual(component['props']['config']['securityLevel'], 'strict')
        page = client.get('/').text
        self.assertIn('/_dash-component-suites/dash_extensions/', page)
        for name in ('dash_extensions.js', 'async-Mermaid.js', 'async-null.js'):
            self.assertEqual(client.get('/_dash-component-suites/dash_extensions/' + name).status_code, 200)
