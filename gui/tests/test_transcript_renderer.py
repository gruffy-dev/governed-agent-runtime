import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
        self.assertIsInstance(parts[1].children[0].children, Mermaid)
        self.assertEqual(parts[1].children[0].children.chart, source)
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

    def test_unlabelled_diagrams_retain_exact_source(self) -> None:
        for declaration in (
            'flowchart TD', 'graph LR;', 'sequenceDiagram', 'classDiagram',
            'stateDiagram', 'stateDiagram-v2', 'erDiagram',
        ):
            for fence in ('```', '~~~~'):
                with self.subTest(declaration=declaration, fence=fence):
                    source = '\r\n%% Diagram comment\r\n' + declaration + '\r\n  A --> B\r\n'
                    parts = TranscriptRenderer._parts(f'{fence}\r\n{source}{fence}\r\n', 'unlabelled')
                    diagram = parts[0].children[0].children
                    self.assertIsInstance(diagram, Mermaid)
                    self.assertEqual(diagram.chart, source)
                    self.assertEqual(parts[0].children[-1].children[1].children[1].content, source)

    def test_ambiguous_and_explicitly_labelled_code_is_not_inferred(self) -> None:
        for text in (
            '```python\nflowchart LR\nA --> B\n```',
            '```json\n{"diagram": "sequenceDiagram"}\n```',
            '```\nflowchart is a useful concept\n```',
            '```\ngraph\nA --> B\n```',
            '```\nsequenceDiagramExample\n```',
            '```\nSome explanation\nflowchart LR\nA --> B\n```',
            '```\nflowchart LR\nA --> B',
            'flowchart LR\nA --> B',
        ):
            with self.subTest(text=text):
                parts = TranscriptRenderer._parts(text, 'ordinary')
                self.assertEqual(len(parts), 1)
                self.assertIsInstance(parts[0], dcc.Markdown)
                self.assertEqual(parts[0].children, text)

    def test_unlabelled_diagrams_keep_configuration_safeguards(self) -> None:
        source = '%%{init: {"securityLevel":"loose"}}%%\nflowchart LR\nA --> B\n'
        card = TranscriptRenderer._parts('```\n' + source + '```', 'unsafe')[0]
        self.assertEqual(len(card.children), 2)
        self.assertEqual(card.children[-1].children[1].children[1].content, source)

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

    def test_relative_zoom_exceeds_previous_ceiling_and_fit_resets_scale(self) -> None:
        style = None
        with patch('mosaic_gui.transcript_renderer.ctx', SimpleNamespace(
            triggered_id={'type': 'mermaid-zoom-in', 'index': 'one'},
        )):
            for clicks in range(1, 13):
                style = TranscriptRenderer.zoom_style(clicks, 0, 0, style)
        self.assertGreater(style['--mermaid-zoom'], 8)
        with patch('mosaic_gui.transcript_renderer.ctx', SimpleNamespace(
            triggered_id={'type': 'mermaid-zoom-out', 'index': 'one'},
        )):
            for clicks in range(1, 13):
                style = TranscriptRenderer.zoom_style(12, clicks, 0, style)
            self.assertAlmostEqual(style['--mermaid-zoom'], 1)
            self.assertAlmostEqual(TranscriptRenderer.zoom_style(12, 13, 0, style)['--mermaid-zoom'], 0.8)
        with patch('mosaic_gui.transcript_renderer.ctx', SimpleNamespace(
            triggered_id={'type': 'mermaid-zoom-fit', 'index': 'one'},
        )):
            self.assertEqual(TranscriptRenderer.zoom_style(12, 0, 1, {'--mermaid-zoom': 15}), {'--mermaid-zoom': 1})

    def test_each_diagram_has_independent_zoom_controls(self) -> None:
        cards = [TranscriptRenderer._diagram('flowchart LR\nA --> B', name) for name in ('one', 'two')]
        for card in cards:
            viewport = card.children[0]
            buttons = card.children[1].children
            self.assertEqual([button.children for button in buttons], ['−', '+', 'Fit'])
            self.assertEqual(buttons[0].to_plotly_json()['props']['aria-label'], 'Zoom out')
            self.assertEqual(buttons[1].to_plotly_json()['props']['aria-label'], 'Zoom in')
            self.assertEqual(buttons[0].title, 'Zoom out')
            self.assertEqual(buttons[1].title, 'Zoom in')
            self.assertEqual({button.id['index'] for button in buttons}, {viewport.id['index']})
            self.assertEqual({button.id['type'] for button in buttons}, {
                'mermaid-zoom-in', 'mermaid-zoom-out', 'mermaid-zoom-fit',
            })
        self.assertNotEqual(cards[0].children[0].id, cards[1].children[0].id)

    def test_unsafe_configuration_and_oversized_diagrams_retain_source(self) -> None:
        for source in (
            '%%{init: {"securityLevel":"loose"}}%%\nflowchart LR\nA --> B\n',
            '---\nconfig:\n  securityLevel: loose\n---\nflowchart LR\nA --> B\n',
            'flowchart LR\nA --> B\nclick A "https://example.com"\n',
            'a' * 50001,
        ):
            with self.subTest(source=source[:40]):
                card = TranscriptRenderer._diagram(source, '3-1')
                self.assertEqual(len(card.children), 2)
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
        component = component['props']['children']
        self.assertEqual(component['namespace'], 'dash_extensions')
        self.assertEqual(component['props']['config']['securityLevel'], 'strict')
        page = client.get('/').text
        self.assertIn('/_dash-component-suites/dash_extensions/', page)
        for name in ('dash_extensions.js', 'async-Mermaid.js', 'async-null.js'):
            self.assertEqual(client.get('/_dash-component-suites/dash_extensions/' + name).status_code, 200)
