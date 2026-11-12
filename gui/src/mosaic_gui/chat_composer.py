from dash import Input, Output, State


def register_chat_composer(application):
    """Route composer actions through Dash in the browser."""
    application.clientside_callback(
        """
        function(send, stop, prompt) {
            const id = window.dash_clientside.callback_context.triggered_id;
            if (id === "send-message" && send > 0) {
                window.mosaicComposerAction?.(id, prompt);
            } else if (id === "stop-stream" && stop > 0) {
                window.mosaicComposerAction?.(id);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output('composer-action-result', 'data'),
        Input('send-message', 'n_clicks'),
        Input('stop-stream', 'n_clicks'),
        State('message-input', 'value'),
        prevent_initial_call=True,
    )
