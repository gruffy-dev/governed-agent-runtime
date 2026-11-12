from dash import ALL, MATCH, Input, Output, ctx, html


def register_conversation_sidebar(application):
    """Register Dash presentation and controls for the conversation sidebar."""
    application.callback(
        Output('conversation-list', 'children'),
        Input('conversation-row-ids', 'data'),
    )(render_conversation_rows)
    application.callback(
        Output('history-panel', 'style'),
        Output('history-resizer', 'style'),
        Output('history-show', 'style'),
        Input('history-show', 'n_clicks'),
        Input('history-toggle', 'n_clicks'),
        prevent_initial_call=True,
    )(_toggle_sidebar)

    application.clientside_callback(
        """
        function(view, row) {
            const conversation = view?.conversations.find(item => item.id === row.conversation);
            if (!conversation) return ["btn btn-link history-item", true, "", "", true];
            const active = view.active === row.conversation;
            const date = new Date(conversation.lastActivity).toLocaleDateString(
                undefined, {month: "short", day: "numeric"}
            );
            return [
                "btn btn-link history-item" + (active ? " active" : ""),
                view.disabled,
                conversation.title || "New conversation",
                date,
                !conversation.interrupted,
            ];
        }
        """,
        Output({'type': 'conversation-row', 'conversation': MATCH}, 'className'),
        Output({'type': 'conversation-row', 'conversation': MATCH}, 'disabled'),
        Output({'type': 'conversation-row-title', 'conversation': MATCH}, 'children'),
        Output({'type': 'conversation-row-date', 'conversation': MATCH}, 'children'),
        Output(
            {'type': 'conversation-row-interrupted', 'conversation': MATCH}, 'hidden'
        ),
        Input('conversation-sidebar-view', 'data'),
        Input({'type': 'conversation-row', 'conversation': MATCH}, 'id'),
    )
    application.clientside_callback(
        """
        function(rows, newConversation) {
            const context = window.dash_clientside.callback_context;
            const id = context.triggered_id;
            if (id === "new-conversation" && newConversation > 0) {
                window.mosaicConversationAction?.();
            } else if (id && typeof id === "object") {
                const row = context.inputs_list[0].find(input => input.id.conversation === id.conversation);
                if (row?.value > 0) window.mosaicConversationAction?.(id.conversation);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output('conversation-action-result', 'data'),
        Input({'type': 'conversation-row', 'conversation': ALL}, 'n_clicks'),
        Input('new-conversation', 'n_clicks'),
        prevent_initial_call=True,
    )


def render_conversation_rows(conversation_ids):
    """Build the sidebar from IDs. The browser supplies titles and activity dates."""
    rows = []
    for conversation_id in conversation_ids or []:
        rows.append(
            html.Button(
                [
                    html.Span(
                        id=_row_id('conversation-row-title', conversation_id),
                        className='history-title',
                    ),
                    html.Span(
                        [
                            html.Span(
                                id=_row_id('conversation-row-date', conversation_id)
                            ),
                            html.Span(
                                'Interrupted',
                                id=_row_id(
                                    'conversation-row-interrupted', conversation_id
                                ),
                                className='interrupted-label',
                                hidden=True,
                            ),
                        ],
                        className='history-meta',
                    ),
                ],
                id=_row_id('conversation-row', conversation_id),
                type='button',
                className='btn btn-link history-item',
                key=conversation_id,
                disabled=True,
                n_clicks=0,
            )
        )
    return rows


def _row_id(component_type, conversation_id):
    return {'type': component_type, 'conversation': conversation_id}


def _toggle_sidebar(_show_clicks, _hide_clicks):
    show = ctx.triggered_id == 'history-show'
    return (
        {'display': 'flex' if show else 'none'},
        {'display': 'block' if show else 'none'},
        {'display': 'none' if show else 'inline-block'},
    )
