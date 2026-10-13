import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from mosaic_gui.gui_application import GuiApplication
from mosaic_gui.gui_configuration import GuiConfiguration


class TestGuiApplication(unittest.TestCase):
    def test_tangram_uses_the_approved_m_shape_and_distinct_halves(self) -> None:
        path = (
            Path(__file__).parent.parent
            / 'src'
            / 'mosaic_gui'
            / 'assets'
            / 'tangram.svg'
        )
        root = ElementTree.fromstring(path.read_text())
        namespace = {'svg': 'http://www.w3.org/2000/svg'}
        left = root.find("svg:g[@id='left-half']", namespace)
        right = root.find("svg:g[@id='right-half']", namespace)
        self.assertEqual(len(left), 4)
        self.assertEqual(len(right), 4)
        self.assertNotEqual(left.attrib['fill'], right.attrib['fill'])
        self.assertEqual(
            root.find(
                "svg:defs/svg:linearGradient[@id='left-primary']/svg:stop", namespace
            ).attrib['stop-color'],
            '#1e2a78',
        )
        self.assertEqual(
            root.find(
                "svg:defs/svg:linearGradient[@id='right-strong']/svg:stop", namespace
            ).attrib['stop-color'],
            '#16205d',
        )

    def test_serves_bootstrap_layout_and_local_assets_without_server_callbacks(
        self,
    ) -> None:
        application = GuiApplication.create_application(GuiConfiguration())
        client = application.server.test_client()
        response = client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'/assets/tangram.svg', response.data)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertIn(
            "img-src 'self' data:", response.headers['Content-Security-Policy']
        )
        self.assertIn(
            "frame-ancestors 'none'", response.headers['Content-Security-Policy']
        )
        layout = client.get('/_dash-layout').get_json()
        self.assertEqual(layout['props']['data-backend-url'], 'http://127.0.0.1:8000')
        self.assertIn('dash_bootstrap_components', str(layout))
        self.assertNotIn('plaintext_token', str(layout))
        self.assertEqual(application.callback_map, {})
        for asset in (
            '00_bootstrap.min.css',
            '10_workspace.css',
            'api_client.mjs',
            'adk_stream.mjs',
            'workspace_controller.mjs',
            'tangram.svg',
        ):
            with client.get('/assets/' + asset) as asset_response:
                self.assertEqual(asset_response.status_code, 200)

    def test_no_logo_route_without_private_branding_and_no_api_proxy(self) -> None:
        client = GuiApplication.create_application().server.test_client()
        self.assertNotIn(
            '/branding/logo.png',
            {rule.rule for rule in client.application.url_map.iter_rules()},
        )
        self.assertEqual(
            client.post(
                '/api/v1/auth/token', json={'token': 'synthetic-value'}
            ).status_code,
            405,
        )

    def test_private_logo_route_does_not_accept_a_caller_path(self) -> None:
        with TemporaryDirectory() as directory:
            logo = Path(directory) / 'synthetic-logo.png'
            data = b'\x89PNG\r\n\x1a\nsynthetic-test-data'
            logo.write_bytes(data)
            application = GuiApplication.create_application(
                GuiConfiguration(
                    organisation_logo_path=logo, organisation_logo_width=110
                )
            )
            client = application.server.test_client()
            with client.get('/branding/logo.png?path=untrusted') as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data, data)
            layout = client.get('/_dash-layout').get_json()
            self.assertNotIn(str(logo), str(layout))
            self.assertIn('110px', str(layout))
