import os
import ssl
import subprocess
import threading
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from wsgiref.simple_server import WSGIRequestHandler, make_server

from dulwich import porcelain
from dulwich.repo import Repo
from dulwich.server import DictBackend
from dulwich.web import make_wsgi_chain
from dulwich.client import default_urllib3_manager

from mosaic.components.skills.git_skill_catalogue_provider import GitSkillCatalogueProvider
from mosaic.components.skills.skill_package_parser import SkillPackageParser
from mosaic.models.skills.git_skill_catalogue_configuration import GitSkillCatalogueConfiguration


class TestGitSkillCatalogueProvider(unittest.TestCase):
    def test_valid_remote_commit_is_synchronised(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            provider = self._create_provider(
                repository_path,
                temporary_root / 'cache.git',
            )

            snapshot = provider.synchronise()

            self.assertEqual(snapshot, provider.get_snapshot())
            self.assertEqual(
                snapshot.commit_sha,
                self._head_commit(repository_path),
            )
            self.assertEqual(snapshot.skills[0].version, '1.0.0')

    def test_synchronisation_does_not_require_git_executable(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            provider = self._create_provider(
                repository_path,
                temporary_root / 'cache.git',
            )

            with patch.dict(os.environ, {'PATH': ''}):
                snapshot = provider.synchronise()

            self.assertEqual(snapshot.skills[0].name, 'investigate-platform')

    def test_british_timeout_field_configures_initial_and_cached_transport(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            cache_path = temporary_root / 'cache.git'
            provider = GitSkillCatalogueProvider(
                configuration=GitSkillCatalogueConfiguration(
                    repository_url=str(repository_path),
                    revision='main',
                    repository_cache_path=cache_path,
                    access_token='synthetic-token',
                    synchronisation_timeout_seconds=17,
                ),
                package_parser=SkillPackageParser(),
            )
            self.assertEqual(
                provider._build_transport_configuration().get((b'http',), b'timeout'),
                b'17.0',
            )
            provider.synchronise()
            with Repo(cache_path) as repository:
                self.assertEqual(
                    repository.get_config().get((b'http',), b'timeout'),
                    b'17.0',
                )

    def test_bearer_token_is_not_persisted_in_repository_cache(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            cache_path = temporary_root / 'cache.git'
            provider = self._create_provider(repository_path, cache_path)

            provider.synchronise()

            cache_configuration = (cache_path / 'config').read_text(encoding='utf-8')
            self.assertNotIn('test-token', cache_configuration)
            self.assertNotIn(
                'extraheader',
                cache_configuration.lower(),
            )

    def test_default_transport_requires_verification_without_a_custom_bundle(
        self,
    ) -> None:
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            provider = self._create_provider(root / 'repository', root / 'cache.git')
            configuration = provider._build_transport_configuration()
            self.assertTrue(configuration.get_boolean((b'http',), b'sslVerify'))
            with self.assertRaises(KeyError):
                configuration.get((b'http',), b'sslCAInfo')
            pool = default_urllib3_manager(configuration)
            try:
                self.assertEqual(pool.connection_pool_kw['cert_reqs'], 'CERT_REQUIRED')
            finally:
                pool.clear()

    def test_https_clone_and_cached_fetch_accept_two_ca_chains_in_one_bundle(
        self,
    ) -> None:
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            repository_path = self._create_repository(root)
            first_certificate, first_key = self._create_tls_certificate(root, 'first')
            second_certificate, second_key = self._create_tls_certificate(
                root, 'second'
            )
            bundle = root / 'combined.pem'
            bundle.write_bytes(
                first_certificate.read_bytes() + second_certificate.read_bytes()
            )
            for name, certificate, key in (
                ('first', first_certificate, first_key),
                ('second', second_certificate, second_key),
            ):
                with (
                    self.subTest(chain=name),
                    self._serve_git_https(repository_path, certificate, key) as url,
                    patch.dict(os.environ, {'SSL_CERT_FILE': str(bundle)}),
                ):
                    cache = root / f'{name}.git'
                    provider = self._create_provider(url, cache)
                    first = provider.synchronise()
                    self._write_package(
                        repository_path, version=f'1.{1 if name == "first" else 2}.0'
                    )
                    self._commit(repository_path, 'Update over verified HTTPS')
                    second = provider.synchronise()
                    self.assertNotEqual(first.commit_sha, second.commit_sha)
                    self.assertEqual(
                        second.commit_sha, self._head_commit(repository_path)
                    )
                    saved_configuration = (cache / 'config').read_text()
                    self.assertNotIn('test-token', saved_configuration)
                    self.assertNotIn(str(bundle), saved_configuration)

    def test_https_rejects_untrusted_certificates_and_hostname_mismatches(self) -> None:
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            repository_path = self._create_repository(root)
            trusted, _ = self._create_tls_certificate(root, 'trusted')
            untrusted, untrusted_key = self._create_tls_certificate(root, 'untrusted')
            wrong_host, wrong_key = self._create_tls_certificate(
                root, 'wrong-host', hostname='wrong.example.test'
            )
            for name, certificate, key, bundle in (
                ('untrusted', untrusted, untrusted_key, trusted),
                ('hostname', wrong_host, wrong_key, wrong_host),
            ):
                with (
                    self.subTest(failure=name),
                    self._serve_git_https(repository_path, certificate, key) as url,
                    patch.dict(os.environ, {'SSL_CERT_FILE': str(bundle)}),
                ):
                    cache = root / f'{name}.git'
                    provider = self._create_provider(url, cache)
                    with self.assertRaises(RuntimeError) as failure:
                        provider.synchronise()
                    self.assertIsNotNone(failure.exception.__cause__)
                    self.assertFalse(cache.exists())

    def test_untrusted_cached_fetch_retains_only_the_previous_valid_snapshot(
        self,
    ) -> None:
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            root = Path(directory)
            repository_path = self._create_repository(root)
            certificate, key = self._create_tls_certificate(root, 'server')
            other_certificate, _ = self._create_tls_certificate(root, 'other')
            cache = root / 'cache.git'
            with self._serve_git_https(repository_path, certificate, key) as url:
                with patch.dict(os.environ, {'SSL_CERT_FILE': str(certificate)}):
                    first = self._create_provider(url, cache).synchronise()
                self._write_package(repository_path, version='1.1.0')
                self._commit(
                    repository_path, 'Remote update must not cross invalid TLS'
                )
                with Repo(cache) as repository:
                    configuration = repository.get_config()
                    configuration.set((b'http',), b'sslVerify', b'false')
                    configuration.write_to_path()
                with patch.dict(os.environ, {'SSL_CERT_FILE': str(other_certificate)}):
                    retained = self._create_provider(url, cache).synchronise()
                self.assertEqual(retained.commit_sha, first.commit_sha)
                self.assertNotEqual(
                    retained.commit_sha, self._head_commit(repository_path)
                )

    def _create_tls_certificate(
        self, root: Path, name: str, hostname: str = 'localhost'
    ) -> tuple[Path, Path]:
        certificate = root / f'{name}.pem'
        key = root / f'{name}.key'
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
                f'/CN={hostname}',
                '-addext',
                f'subjectAltName=DNS:{hostname}',
                '-addext',
                'basicConstraints=critical,CA:TRUE',
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

    @contextmanager
    def _serve_git_https(
        self, repository_path: Path, certificate: Path, key: Path
    ) -> Iterator[str]:
        with (
            Repo(repository_path) as repository,
            patch.object(WSGIRequestHandler, 'log_message'),
            make_server(
                '127.0.0.1',
                0,
                make_wsgi_chain(DictBackend({'/skills.git': repository})),
            ) as server,
        ):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(certificate), str(key))
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                yield f'https://localhost:{server.server_port}/skills.git'
            finally:
                server.shutdown()
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())

    def test_new_valid_commit_replaces_active_snapshot(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            provider = self._create_provider(
                repository_path,
                temporary_root / 'cache.git',
            )
            first_snapshot = provider.synchronise()
            self._write_package(repository_path, version='1.1.0')
            self._commit(repository_path, 'Update skill')

            second_snapshot = provider.synchronise()

            self.assertNotEqual(
                first_snapshot.commit_sha,
                second_snapshot.commit_sha,
            )
            self.assertEqual(second_snapshot.skills[0].version, '1.1.0')

    def test_invalid_new_commit_preserves_last_valid_snapshot(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            cache_path = temporary_root / 'cache.git'
            provider = self._create_provider(repository_path, cache_path)
            first_snapshot = provider.synchronise()
            metadata_path = (
                repository_path
                / 'skills'
                / 'container-platforms'
                / 'diagnostics'
                / 'investigate-platform'
                / 'mosaic.yaml'
            )
            metadata_path.write_text(
                'schema_version: 1\nversion: invalid\nkind: procedural\n',
                encoding='utf-8',
            )
            self._commit(repository_path, 'Invalid skill')

            retained_snapshot = provider.synchronise()
            restarted_provider = self._create_provider(
                repository_path,
                cache_path,
            )
            restarted_snapshot = restarted_provider.synchronise()

            self.assertEqual(retained_snapshot, first_snapshot)
            self.assertEqual(
                restarted_snapshot.commit_sha,
                first_snapshot.commit_sha,
            )

    def test_unavailable_remote_recovers_persisted_snapshot(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            repository_path = self._create_repository(temporary_root)
            cache_path = temporary_root / 'cache.git'
            provider = self._create_provider(repository_path, cache_path)
            first_snapshot = provider.synchronise()
            unavailable_repository_path = temporary_root / 'offline-repository'
            repository_path.rename(unavailable_repository_path)
            restarted_provider = self._create_provider(
                repository_path,
                cache_path,
            )

            recovered_snapshot = restarted_provider.synchronise()

            self.assertEqual(
                recovered_snapshot.commit_sha,
                first_snapshot.commit_sha,
            )

    def test_get_snapshot_requires_prior_synchronisation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            provider = self._create_provider(
                temporary_root / 'repository',
                temporary_root / 'cache.git',
            )

            with self.assertRaises(RuntimeError):
                provider.get_snapshot()

    def _create_repository(self, temporary_root: Path) -> Path:
        repository_path = temporary_root / 'repository'
        repository = porcelain.init(repository_path)
        repository.refs.set_symbolic_ref(b'HEAD', b'refs/heads/main')
        repository.close()
        self._write_package(repository_path, version='1.0.0')
        self._commit(repository_path, 'Initial skill')
        return repository_path

    def _create_provider(
        self,
        repository_path: Path | str,
        cache_path: Path,
    ) -> GitSkillCatalogueProvider:
        return GitSkillCatalogueProvider(
            configuration=GitSkillCatalogueConfiguration(
                repository_url=str(repository_path),
                revision='main',
                repository_cache_path=cache_path,
                access_token='test-token',
            ),
            package_parser=SkillPackageParser(),
        )

    def _write_package(self, repository_path: Path, version: str) -> None:
        package_directory = (
            repository_path
            / 'skills'
            / 'container-platforms'
            / 'diagnostics'
            / 'investigate-platform'
        )
        package_directory.mkdir(parents=True, exist_ok=True)
        (package_directory / 'SKILL.md').write_text(
            '---\n'
            'name: investigate-platform\n'
            'description: Investigate platform failures.\n'
            '---\n\n'
            '# Investigation\n\n'
            'Collect approved platform evidence.\n',
            encoding='utf-8',
        )
        (package_directory / 'mosaic.yaml').write_text(
            'schema_version: 1\n'
            f'version: {version}\n'
            'kind: procedural\n'
            'required_capability_names:\n'
            '  - platform.status.read\n'
            'optional_capability_names: []\n',
            encoding='utf-8',
        )

    def _commit(self, repository_path: Path, message: str) -> None:
        porcelain.add(repository_path)
        porcelain.commit(
            repository_path,
            message=message,
            author=b'MOSAIC Test <test@example.test>',
            committer=b'MOSAIC Test <test@example.test>',
        )

    def _head_commit(self, repository_path: Path) -> str:
        with Repo(repository_path) as repository:
            return repository.head().decode('ascii').lower()


if __name__ == '__main__':
    unittest.main()
