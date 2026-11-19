import re
from typing import Any

from dash import Dash, Input, Output, dcc, html
from dash.development.base_component import Component
from dash_extensions import Mermaid


class TranscriptRenderer:
    @staticmethod
    def register(application: Dash) -> None:
        """
        Register completed-transcript presentation with a browser generation guard.

        :param application: GUI application receiving presentation callbacks.
        """
        application.callback(
            Output('transcript-render-result', 'data'),
            Input('transcript-render-request', 'data'),
            prevent_initial_call=True,
        )(TranscriptRenderer.render)
        application.clientside_callback(
            """
            function(result) {
                window.mosaicTranscript?.(result);
                return window.dash_clientside.no_update;
            }
            """,
            Output('transcript-render-applied', 'data'),
            Input('transcript-render-result', 'data'),
            prevent_initial_call=True,
        )

    @staticmethod
    def render(request: dict[str, Any] | None) -> dict[str, Any] | None:
        """
        Present completed messages while retaining the source of each diagram.

        :param request: Browser generation and completed user/assistant messages.

        :return: Components tagged with the originating browser generation.
        """
        if not request:
            return None
        if type(request.get('sequence')) is not int:
            return None
        children = []
        for index, message in enumerate(request['messages']):
            role = message['role']
            if role not in {'user', 'assistant'}:
                continue
            body = (
                message['text']
                if role == 'user'
                else TranscriptRenderer._parts(
                    message['text'], f"{request['sequence']}-{index}"
                )
            )
            children.append(
                html.Div(
                    [
                        html.Div(
                            'You' if role == 'user' else 'MOSAIC',
                            className='message-label',
                        ),
                        html.Div(body, className='message-body'),
                    ],
                    className=f'message message-{role}',
                )
            )
        return {'sequence': request['sequence'], 'children': children}

    @staticmethod
    def _parts(text: str, prefix: str) -> list[Component]:
        """
        Replace complete Mermaid fences while preserving surrounding Markdown.

        :param text: Unmodified assistant response.
        :param prefix: Identifier unique to this rendered message.

        :return: Markdown and diagram components in their original order.
        """
        lines = text.splitlines(keepends=True)
        children = []
        cursor = start = 0
        while cursor < len(lines):
            opening = re.fullmatch(r' {0,3}(`{3,}|~{3,})([^\r\n]*)\r?\n?', lines[cursor])
            if opening is None:
                cursor += 1
                continue
            fence, language = opening.groups()
            closing_pattern = r' {0,3}' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}[ \t]*\r?\n?'
            closing = next(
                (index for index in range(cursor + 1, len(lines))
                 if re.fullmatch(closing_pattern, lines[index])),
                None,
            )
            if closing is None:
                break
            if language.strip().casefold() == 'mermaid':
                if start < cursor:
                    children.append(TranscriptRenderer._markdown(''.join(lines[start:cursor])))
                source = ''.join(lines[cursor + 1:closing])
                children.append(TranscriptRenderer._diagram(source, f'{prefix}-{cursor}'))
                start = closing + 1
            cursor = closing + 1
        if start < len(lines):
            children.append(TranscriptRenderer._markdown(''.join(lines[start:])))
        return children

    @staticmethod
    def _markdown(text: str) -> dcc.Markdown:
        """
        Render Markdown with the existing chat presentation settings.

        :param text: Markdown text outside rendered Mermaid blocks.

        :return: Markdown component with raw HTML disabled.
        """
        return dcc.Markdown(
            text, dangerously_allow_html=False, link_target='_blank',
            mathjax=False, highlight_config={'theme': 'light'},
        )

    @staticmethod
    def _diagram(source: str, identifier: str) -> html.Div:
        """
        Build a diagram card with native Dash source and clipboard controls.

        :param source: Exact text between the Markdown fence lines.
        :param identifier: Unique identifier for the diagram and copy control.

        :return: Diagram card retaining source even when rendering fails.
        """
        visual = []
        if len(source) <= 50000 and not re.search(r'%%\{|(?m:^\s*(?:---\s*$|click\s))', source):
            visual.append(Mermaid(
                chart=source,
                name=f'mosaic-diagram-{identifier}',
                className='mermaid-visual',
                config={
                    'startOnLoad': False,
                    'securityLevel': 'strict',
                    'suppressErrorRendering': True,
                    'maxTextSize': 50000,
                    'flowchart': {'htmlLabels': False},
                    'theme': 'base',
                    'themeVariables': {
                        'primaryColor': '#e7eaf7',
                        'primaryTextColor': '#16205d',
                        'primaryBorderColor': '#1e2a78',
                        'lineColor': '#1e2a78',
                    },
                },
            ))
        return html.Div(
            [
                *visual,
                html.P(
                    'Diagram unavailable. View or copy the source below.',
                    className='mermaid-fallback',
                ),
                html.Div(
                    [
                        html.Details([
                            html.Summary('Source'),
                            html.Pre(source, className='mermaid-source'),
                        ]),
                        html.Div([
                            html.Span('Copy source'),
                            dcc.Clipboard(
                                id=f'mermaid-copy-{identifier}', content=source,
                                title='Copy Mermaid source', className='mermaid-copy',
                            ),
                        ], className='mermaid-copy-control'),
                    ],
                    className='mermaid-tools',
                ),
            ],
            className='mermaid-card',
            key=identifier,
        )
