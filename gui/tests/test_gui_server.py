import os
import socket
import ssl
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import HTTPSHandler, ProxyHandler, build_opener
from unittest.mock import patch

from mosaic_gui.gui_application import GuiApplication
from mosaic_gui.gui_configuration import GuiConfiguration
from mosaic_gui.gui_server import GuiServer


class TestGuiServer(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def create_certificate(self, directory: Path, name: str) -> tuple[Path, Path]:
        certificate = directory / f'{name}.pem'
        key = directory / f'{name}.key'
        subprocess.run(
            [
                '/usr/bin/openssl',
                'req',
                '-x509',
                '-newkey',
                'rsa:2048',
                '-nodes',
                '-days',
                '1',
                '-subj',
                '/CN=localhost',
                '-addext',
                'subjectAltName=DNS:localhost,IP:127.0.0.1',
                '-keyout',
                str(key),
                '-out',
                str(certificate),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return certificate, key

    def test_http_listener_has_no_tls_and_loads_existing_application(self) -> None:
        configuration = GuiConfiguration(host='::1', port=8051)
        application = GuiApplication.create_application(configuration).server
        server = GuiServer(application, configuration)
        self.assertIs(server.load(), application)
        self.assertEqual(server.cfg.bind, ['[::1]:8051'])
        self.assertIsNone(server.cfg.certfile)
        self.assertIsNone(server.cfg.keyfile)

    def test_explicit_modes_reject_missing_or_conflicting_files(self) -> None:
        for values in (
            {'scheme': 'automatic'},
            {'scheme': 'https'},
            {'scheme': 'https', 'tls_cert_file': '/nonexistent/certificate.pem'},
            {'scheme': 'http', 'tls_key_file': '/nonexistent/private.key'},
            {'scheme': 'http', 'tls_cert_file': '/nonexistent/certificate.pem'},
            {
                'scheme': 'https',
                'tls_cert_file': '/nonexistent/certificate.pem',
                'tls_key_file': '/nonexistent/private.key',
            },
        ):
            with self.subTest(values=values), self.assertRaises(ValueError):
                GuiConfiguration(**values)

    def test_https_loads_environment_and_rejects_malformed_or_mismatched_keys(
        self,
    ) -> None:
        with TemporaryDirectory() as directory:
            certificate, key = self.create_certificate(Path(directory), 'first')
            _, other_key = self.create_certificate(Path(directory), 'second')
            with patch.dict(
                os.environ,
                {
                    'MOSAIC_GUI_SCHEME': 'https',
                    'MOSAIC_GUI_TLS_CERT_FILE': str(certificate),
                    'MOSAIC_GUI_TLS_KEY_FILE': str(key),
                },
            ):
                configuration = GuiConfiguration()
            server = GuiServer(
                GuiApplication.create_application(configuration).server, configuration
            )
            self.assertEqual(server.cfg.certfile, str(certificate.resolve()))
            self.assertEqual(server.cfg.keyfile, str(key.resolve()))
            with self.assertRaises(ValueError):
                GuiConfiguration(
                    scheme='https', tls_cert_file=certificate, tls_key_file=other_key
                )
            key.write_text('not a private key')
            with self.assertRaises(ValueError):
                GuiConfiguration(
                    scheme='https', tls_cert_file=certificate, tls_key_file=key
                )

    def test_real_https_listener_with_verified_certificate_and_clean_shutdown(
        self,
    ) -> None:
        self.assert_listener('https')

    def test_real_http_listener_and_clean_shutdown(self) -> None:
        self.assert_listener('http')

    def assert_listener(self, scheme: str) -> None:
        with TemporaryDirectory() as directory:
            certificate, key = self.create_certificate(Path(directory), 'listener')
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            environment = {
                'PATH': os.defpath,
                'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                'MOSAIC_GUI_SCHEME': scheme,
                'MOSAIC_GUI_PORT': str(port),
            }
            if scheme == 'https':
                environment.update(
                    MOSAIC_GUI_TLS_CERT_FILE=str(certificate),
                    MOSAIC_GUI_TLS_KEY_FILE=str(key),
                )
            opener = build_opener(
                ProxyHandler({}),
                HTTPSHandler(
                    context=ssl.create_default_context(cafile=str(certificate))
                ),
            )
            with (Path(directory) / 'server.log').open('w+') as output:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        '-c',
                        (
                            'from mosaic_gui.gui_application import GuiApplication; '
                            'GuiApplication.run()'
                        ),
                    ],
                    env=environment,
                    stdout=output,
                    stderr=output,
                )
                try:
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            with opener.open(
                                f'{scheme}://localhost:{port}/', timeout=1
                            ) as response:
                                self.assertEqual(response.status, 200)
                                self.assertIn(b'MOSAIC', response.read())
                            break
                        except OSError:
                            if (
                                process.poll() is not None
                                or time.monotonic() > deadline
                            ):
                                output.seek(0)
                                self.fail(output.read())
                            time.sleep(0.1)
                    with opener.open(
                        f'{scheme}://localhost:{port}/assets/api_client.mjs', timeout=2
                    ) as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn(b'export class ApiClient', response.read())
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        self.fail('GUI required forced termination.')
                self.assertEqual(process.returncode, 0)
