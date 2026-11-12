from pathlib import Path

from dash import Dash
from flask import Response, send_file

from .gui_configuration import GuiConfiguration
from .gui_layout import GuiLayout
from .gui_server import GuiServer
from .skill_views import register_skill_callbacks


class GuiApplication:
    @staticmethod
    def create_application(configuration: GuiConfiguration | None = None) -> Dash:
        """
        Create a standalone Dash app with local presentation callbacks and browser API access.

        :param configuration: Optional operator-owned GUI configuration.

        :return: Dash application serving the GUI.
        """
        configuration = configuration or GuiConfiguration()
        application = Dash(
            __name__,
            assets_folder=str(Path(__file__).parent / 'assets'),
            title='MOSAIC | Agent workspace',
            update_title=None,
        )
        application.layout = GuiLayout(configuration).create_layout()
        register_skill_callbacks(application)
        application.index_string = """<!DOCTYPE html>
<html><head>{%metas%}<title>{%title%}</title>
<link rel="icon" type="image/svg+xml" href="/assets/tangram.svg">{%css%}</head>
<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body></html>"""

        @application.server.after_request
        def protect_response(response: Response) -> Response:
            """
            Prevent caching user pages, framing, and third-party model-content loads.

            :param response: GUI HTTP response receiving security headers.

            :return: Response with a constrained browser resource policy.
            """
            response.headers['Cache-Control'] = 'no-store'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            response.headers['Referrer-Policy'] = 'no-referrer'
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
                f"connect-src 'self' {configuration.backend_url}; "
                "object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'none'"
            )
            return response

        if configuration.organisation_logo_path is not None:

            @application.server.get('/branding/logo.png')
            def organisation_logo() -> Response:
                """
                Serve only the configured private logo, never caller-selected files.

                :return: Operator-provided PNG with no exposed filesystem path.
                """
                return send_file(
                    configuration.organisation_logo_path.resolve(), mimetype='image/png'
                )

        return application

    @staticmethod
    def run() -> None:
        """
        Serve the standalone GUI with Gunicorn and explicit HTTP or HTTPS settings.
        """
        configuration = GuiConfiguration()
        GuiServer(
            GuiApplication.create_application(configuration).server,
            configuration,
        ).run()
