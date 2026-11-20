import os
import signal
import socket
import ssl
import subprocess
import sys
import time
import unittest
from importlib.util import find_spec
from pathlib import Path
from shutil import which
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

from mosaic_gui.gui_application import GuiApplication
from mosaic_gui.gui_configuration import GuiConfiguration


class TestGuiServer(unittest.TestCase):
    def setUp(self) -> None:
        self.process_environment = os.environ.copy()
        self.openssl = which('openssl')
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def create_certificate(self, directory: Path, name: str) -> tuple[Path, Path]:
        certificate = directory / f'{name}.pem'
        key = directory / f'{name}.key'
        subprocess.run(
            [
                self.openssl,
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

    @unittest.skipIf(sys.platform == 'win32', 'Gunicorn is used on Unix.')
    def test_http_listener_has_no_tls_and_loads_existing_application(self) -> None:
        from mosaic_gui.gui_server import GuiServer

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

    def test_windows_uses_waitress_and_rejects_direct_https(self) -> None:
        serve = Mock()
        with (
            patch('mosaic_gui.gui_configuration.platform', 'win32'),
            patch('mosaic_gui.gui_application.platform', 'win32'),
            patch.dict(sys.modules, {'waitress': SimpleNamespace(serve=serve)}),
        ):
            GuiApplication.run()
            self.assertEqual(serve.call_args.kwargs, {'host': '127.0.0.1', 'port': 8050, 'threads': 4})
            self.assertEqual(serve.call_args.args[0].test_client().get('/').status_code, 200)
            with (
                patch.dict(os.environ, {'MOSAIC_GUI_SCHEME': 'https'}),
                self.assertRaisesRegex(ValueError, 'Windows GUI listener supports HTTP only'),
            ):
                GuiApplication.run()
            serve.assert_called_once()

    @unittest.skipIf(sys.platform == 'win32', 'Gunicorn is used on Unix.')
    def test_https_loads_environment_and_rejects_malformed_or_mismatched_keys(
        self,
    ) -> None:
        from mosaic_gui.gui_server import GuiServer

        if self.openssl is None:
            self.skipTest('OpenSSL is required to generate a test certificate.')
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

    @unittest.skipIf(sys.platform == 'win32', 'Direct GUI HTTPS is provided by Gunicorn on Unix.')
    def test_real_https_listener_with_verified_certificate_and_clean_shutdown(
        self,
    ) -> None:
        self.assert_listener('https')

    def test_real_http_listener_and_clean_shutdown(self) -> None:
        self.assert_listener('http')

    @unittest.skipUnless(find_spec('waitress'), 'Waitress is installed by default on Windows.')
    def test_real_waitress_http_listener(self) -> None:
        self.assert_listener('http', use_waitress=True)

    def assert_listener(self, scheme: str, *, use_waitress: bool = False) -> None:
        with TemporaryDirectory() as directory:
            with socket.socket() as reservation:
                reservation.bind(('127.0.0.1', 0))
                port = reservation.getsockname()[1]
            environment = {
                **{key: self.process_environment[key] for key in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if key in self.process_environment},
                'PATH': os.defpath,
                'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src'),
                'MOSAIC_GUI_SCHEME': scheme,
                'MOSAIC_GUI_PORT': str(port),
            }
            handlers = [ProxyHandler({})]
            if scheme == 'https':
                if self.openssl is None:
                    self.skipTest('OpenSSL is required to generate a test certificate.')
                certificate, key = self.create_certificate(Path(directory), 'listener')
                environment.update(
                    MOSAIC_GUI_TLS_CERT_FILE=str(certificate),
                    MOSAIC_GUI_TLS_KEY_FILE=str(key),
                )
                handlers.append(HTTPSHandler(context=ssl.create_default_context(cafile=str(certificate))))
            opener = build_opener(*handlers)
            script = 'import mosaic_gui.gui_application as entrypoint; '
            if use_waitress:
                script += "entrypoint.platform = 'win32'; "
            script += 'entrypoint.GuiApplication.run()'
            with (Path(directory) / 'server.log').open('w+') as output:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        '-c',
                        script,
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
                    if use_waitress and sys.platform != 'win32':
                        process.send_signal(signal.SIGINT)
                    else:
                        process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        self.fail('GUI required forced termination.')
                if sys.platform != 'win32':
                    self.assertEqual(process.returncode, 0)
