import re
from typing import Any

from dash import MATCH, Dash, Input, Output, State, ctx, dcc, html
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
        application.callback(
            Output({'type': 'mermaid-viewport', 'index': MATCH}, 'style'),
            Input({'type': 'mermaid-zoom-in', 'index': MATCH}, 'n_clicks'),
            Input({'type': 'mermaid-zoom-out', 'index': MATCH}, 'n_clicks'),
            Input({'type': 'mermaid-zoom-fit', 'index': MATCH}, 'n_clicks'),
            State({'type': 'mermaid-viewport', 'index': MATCH}, 'style'),
        )(TranscriptRenderer.zoom_style)
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
    def zoom_style(
        zoom_in: int | None,
        zoom_out: int | None,
        fit: int | None,
        style: dict[str, float] | None,
    ) -> dict[str, float]:
        """
        Enlarge or reduce a diagram relative to its current scale, or fit it.

        :param zoom_in: Click count from the diagram's Zoom in button.
        :param zoom_out: Click count from the diagram's Zoom out button.
        :param fit: Click count from the diagram's Fit button.
        :param style: Current scale applied to this diagram's viewport.

        :return: Relative scale, or the responsive fitted scale after Fit.
        """
        action = ctx.triggered_id
        scale = (style or {}).get('--mermaid-zoom', 1)
        if isinstance(action, dict) and action['type'] == 'mermaid-zoom-in':
            scale *= 1.25
        elif isinstance(action, dict) and action['type'] == 'mermaid-zoom-out':
            scale /= 1.25
        else:
            scale = 1
        return {'--mermaid-zoom': scale}

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
            source = ''.join(lines[cursor + 1:closing])
            if language.strip().casefold() == 'mermaid' or (
                not language.strip() and TranscriptRenderer._is_unlabelled_diagram(source)
            ):
                if start < cursor:
                    children.append(TranscriptRenderer._markdown(''.join(lines[start:cursor])))
                children.append(TranscriptRenderer._diagram(source, f'{prefix}-{cursor}'))
                start = closing + 1
            cursor = closing + 1
        if start < len(lines):
            children.append(TranscriptRenderer._markdown(''.join(lines[start:])))
        return children

    @staticmethod
    def _is_unlabelled_diagram(source: str) -> bool:
        """
        Recognise an explicit Mermaid declaration in an unlabelled fenced block.

        :param source: Unmodified content between complete Markdown fence lines.

        :return: Whether the first declaration identifies a supported diagram.
        """
        return re.match(
            r'\A(?:[ \t]*(?:%%[^\r\n]*)?\r?\n)*[ \t]*'
            r'(?:(?:flowchart|graph)[ \t]+(?:TB|TD|BT|RL|LR)'
            r'|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram)'
            r'[ \t]*;?[ \t]*(?:\r?\n|$)',
            source,
        ) is not None

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
            diagram = Mermaid(
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
            )
            visual.extend([
                html.Div(
                    diagram, className='mermaid-viewport',
                    id={'type': 'mermaid-viewport', 'index': identifier},
                ),
                html.Div([
                    html.Button(
                        '−', id={'type': 'mermaid-zoom-out', 'index': identifier},
                        n_clicks=0, className='btn btn-outline-primary btn-sm mermaid-zoom-step',
                        title='Zoom out', **{'aria-label': 'Zoom out'},
                    ),
                    html.Button(
                        '+', id={'type': 'mermaid-zoom-in', 'index': identifier},
                        n_clicks=0, className='btn btn-outline-primary btn-sm mermaid-zoom-step',
                        title='Zoom in', **{'aria-label': 'Zoom in'},
                    ),
                    html.Button(
                        'Fit', id={'type': 'mermaid-zoom-fit', 'index': identifier},
                        n_clicks=0, className='btn btn-outline-primary btn-sm',
                        title='Fit the chart to the available space',
                    ),
                ], className='mermaid-zoom-control'),
            ])
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
                            html.Span('Copy'),
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
