import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from mosaic_gui.gui_application import GuiApplication
from mosaic_gui.gui_configuration import GuiConfiguration


class TestGuiApplication(unittest.TestCase):
    def test_ada_credit_appears_only_in_sign_in_card(self) -> None:
        layout = (
            GuiApplication.create_application(GuiConfiguration())
            .server.test_client()
            .get('/_dash-layout')
            .get_json()
        )
        screens = next(
            child['props']['children'] for child in layout['props']['children']
            if child['props'].get('id') == 'workspace-main'
        )
        card = screens[0]['props']['children'][1]
        credit = card['props']['children']['props']['children'][-1]
        self.assertEqual(credit['type'], 'P')
        self.assertEqual(credit['props']['children'], 'Built on Ada')
        self.assertEqual(credit['props']['className'], 'foundation-credit')
        self.assertNotIn('Built on Ada', str(screens[1]))
        self.assertEqual(str(layout).count('Built on Ada'), 1)

    def test_sign_in_introduction_keeps_only_headline(self) -> None:
        layout = (
            GuiApplication.create_application(GuiConfiguration())
            .server.test_client()
            .get('/_dash-layout')
            .get_json()
        )
        screens = next(
            child['props']['children'] for child in layout['props']['children']
            if child['props'].get('id') == 'workspace-main'
        )
        introduction = screens[0]['props']['children'][0]['props']['children']
        self.assertEqual(len(introduction), 1)
        self.assertEqual(introduction[0]['type'], 'H1')
        self.assertIn('Intelligence,', str(introduction[0]))
        self.assertIn('orchestrated.', str(introduction[0]))
        self.assertNotIn(
            'Modular Orchestrator of Skills, AI and Capabilities', str(layout)
        )
        self.assertNotIn('MODULAR BY DESIGN', str(introduction))
        self.assertNotIn('One focused workspace', str(introduction))
        self.assertNotIn('login-pillars', str(introduction))

    def test_unbranded_header_has_no_organisation_logo_or_divider(self) -> None:
        layout = (
            GuiApplication.create_application(GuiConfiguration())
            .server.test_client()
            .get('/_dash-layout')
            .get_json()
        )
        header = layout['props']['children'][0]['props']['children']
        branding = header[0]['props']['children']
        self.assertEqual(branding[0]['props']['className'], 'mosaic-symbol')
        self.assertNotIn('brand-divider', str(header))
        self.assertNotIn('organisation-logo', str(header))

    def test_organisation_logo_and_divider_precede_mosaic_branding(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic-logo.png'
            path.write_bytes(b'\x89PNG\r\n\x1a\nsynthetic-test-data')
            layout = (
                GuiApplication.create_application(
                    GuiConfiguration(organisation_logo_path=path)
                )
                .server.test_client()
                .get('/_dash-layout')
                .get_json()
            )
            header = layout['props']['children'][0]['props']['children']
            branding = header[0]['props']['children']
            self.assertEqual(branding[0]['props']['className'], 'organisation-logo')
            self.assertEqual(branding[1]['props']['className'], 'brand-divider')
            self.assertEqual(branding[1]['props']['aria-hidden'], 'true')
            self.assertEqual(branding[2]['props']['className'], 'mosaic-symbol')
            self.assertNotIn('organisation-logo', str(header[1]))
            self.assertEqual(
                header[1]['props']['children'][0]['props']['children'], 'PILOT'
            )

    def test_collapsed_controls_have_matching_icons_and_accessible_names(self) -> None:
        layout = (
            GuiApplication.create_application()
            .server.test_client()
            .get('/_dash-layout')
            .get_json()
        )
        pending = [layout]
        controls = {}
        while pending:
            component = pending.pop()
            if not isinstance(component, dict):
                continue
            props = component.get('props', {})
            if props.get('id') in ('history-show', 'skills-show'):
                controls[props['id']] = props
            children = props.get('children', [])
            pending.extend(children if isinstance(children, list) else [children])
        for identifier, name in (
            ('history-show', 'Conversations'),
            ('skills-show', 'Current Skills'),
        ):
            props = controls[identifier]
            self.assertEqual(props['className'], 'panel-show')
            self.assertEqual(props['title'], 'Show ' + name)
            self.assertEqual(
                props['children'][1]['props']['className'], 'visually-hidden'
            )
            self.assertEqual(props['children'][1]['props']['children'], 'Show ' + name)
        self.assertIn(
            'MOSAIC can make mistakes. Validate important information.', str(layout)
        )

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
            '#42549a',
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
            'invocation_activity.mjs',
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
