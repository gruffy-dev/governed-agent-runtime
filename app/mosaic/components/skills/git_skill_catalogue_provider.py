"""Dulwich-backed provider for immutable skill-catalogue snapshots."""

import os
import re
import shutil
import stat
import tempfile
import threading
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path, PurePosixPath

from dulwich import porcelain
from dulwich.client import (
    HTTPProxyUnauthorized,
    HTTPUnauthorized,
    get_transport_and_path,
)
from dulwich.config import ConfigDict
from dulwich.errors import (
    FileFormatException,
    GitProtocolError,
    NotGitRepository,
    ObjectMissing,
    RefFormatError,
    WrongObjectException,
)
from dulwich.object_store import iter_commit_contents
from dulwich.objects import Blob
from dulwich.objectspec import parse_commit
from dulwich.porcelain import Error as PorcelainError
from dulwich.repo import Repo
from urllib3.exceptions import HTTPError

from ...models.skills.git_skill_catalogue_configuration import (
    GitSkillCatalogueConfiguration,
)
from ...models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot
from .skill_package_parser import SkillPackageParser


class GitSkillCatalogueProvider:
    """Synchronise and validate skills without requiring a Git executable."""

    _ACTIVE_COMMIT_FILE = 'mosaic-active-commit'

    def __init__(
        self,
        configuration: GitSkillCatalogueConfiguration,
        package_parser: SkillPackageParser,
    ) -> None:
        """Initialise the provider without performing network operations.

        Args:
            configuration: Trusted Git repository configuration.
            package_parser: Validator for exported skill packages.
        """
        self._configuration = configuration
        self._package_parser = package_parser
        self._snapshot: SkillCatalogueSnapshot | None = None
        self._synchronization_lock = threading.Lock()

    def synchronize(self) -> SkillCatalogueSnapshot:
        """Fetch, validate, and atomically activate a catalogue commit.

        Returns:
            The new validated snapshot, or the last valid snapshot if a newer
            commit cannot be fetched or validated.

        Raises:
            RuntimeError: If no valid snapshot can be supplied.
        """
        with self._synchronization_lock:
            cache_preexisted = self._cache_path.exists()
            try:
                self._ensure_repository_cache()
            except RuntimeError:
                if self._snapshot is not None:
                    return self._snapshot
                raise
            previous_commit = self._read_active_commit()

            try:
                if cache_preexisted:
                    self._refresh_repository_cache()
                candidate_commit = self._resolve_revision()
            except RuntimeError:
                return self._recover_previous_snapshot(previous_commit)

            if (
                self._snapshot is not None
                and self._snapshot.commit_sha == candidate_commit
            ):
                return self._snapshot

            try:
                candidate_snapshot = self._load_snapshot(candidate_commit)
            except (RuntimeError, ValueError):
                return self._recover_previous_snapshot(previous_commit)

            try:
                self._persist_active_commit_marker(candidate_commit)
            except RuntimeError:
                if self._snapshot is not None:
                    return self._snapshot
                raise
            self._snapshot = candidate_snapshot
            return candidate_snapshot

    def get_snapshot(self) -> SkillCatalogueSnapshot:
        """Return the active snapshot without contacting the remote source.

        Returns:
            The active immutable catalogue snapshot.

        Raises:
            RuntimeError: If no snapshot has been activated.
        """
        if self._snapshot is None:
            raise RuntimeError(
                'The skill catalogue has not been synchronized.'
            )
        return self._snapshot

    @property
    def _cache_path(self) -> Path:
        """Return the normalized deployment-local repository path.

        Returns:
            Absolute cache path from trusted configuration.
        """
        return self._configuration.repository_cache_path.expanduser()

    def _ensure_repository_cache(self) -> None:
        """Create the bare cache or verify an existing cache's remote.

        Raises:
            RuntimeError: If cloning or cache validation fails.
        """
        if self._cache_path.exists():
            self._validate_existing_cache()
            return

        cache_parent = self._cache_path.parent
        try:
            cache_parent.mkdir(parents=True, exist_ok=True)
            temporary_parent = Path(
                tempfile.mkdtemp(
                    prefix=f'.{self._cache_path.name}-',
                    dir=cache_parent,
                )
            )
        except OSError as error:
            raise RuntimeError(
                'The local Git cache directory cannot be created.'
            ) from error

        temporary_cache = temporary_parent / 'repository.git'
        try:
            try:
                repository = porcelain.clone(
                    source=self._configuration.repository_url,
                    target=temporary_cache,
                    bare=True,
                    checkout=False,
                    config=self._build_transport_configuration(),
                    errstream=BytesIO(),
                    quiet=True,
                )
                try:
                    self._persist_transport_configuration(repository)
                finally:
                    repository.close()
            except (
                OSError,
                ValueError,
                GitProtocolError,
                HTTPError,
                HTTPProxyUnauthorized,
                HTTPUnauthorized,
                PorcelainError,
            ) as error:
                raise RuntimeError(
                    'The remote skill repository could not be cloned.'
                ) from error

            try:
                os.replace(temporary_cache, self._cache_path)
            except OSError as error:
                if self._cache_path.exists():
                    self._validate_existing_cache()
                else:
                    raise RuntimeError(
                        'The local Git cache could not be activated.'
                    ) from error
        finally:
            shutil.rmtree(temporary_parent, ignore_errors=True)

    def _validate_existing_cache(self) -> None:
        """Verify that the cache is bare and uses the configured remote.

        Raises:
            RuntimeError: If the cache is invalid or belongs to a different
                repository.
        """
        if not self._cache_path.is_dir() or self._cache_path.is_symlink():
            raise RuntimeError(
                'The configured Git cache path is not a regular directory.'
            )

        try:
            with Repo(self._cache_path) as repository:
                if not repository.bare:
                    raise RuntimeError(
                        'The configured Git cache is not a bare repository.'
                    )
                remote_url = repository.get_config().get(
                    (b'remote', b'origin'),
                    b'url',
                ).decode('utf-8')
        except RuntimeError:
            raise
        except (
            OSError,
            KeyError,
            UnicodeError,
            FileFormatException,
            NotGitRepository,
        ) as error:
            raise RuntimeError(
                'The configured Git cache is invalid.'
            ) from error

        if remote_url != self._configuration.repository_url:
            raise RuntimeError(
                'The existing Git cache belongs to a different repository.'
            )

    def _refresh_repository_cache(self) -> None:
        """Fetch remote branches and tags into the existing bare cache.

        Raises:
            RuntimeError: If the remote cannot be refreshed.
        """
        try:
            with Repo(self._cache_path) as repository:
                client, remote_path = get_transport_and_path(
                    self._configuration.repository_url,
                    config=self._build_transport_configuration(),
                    operation='fetch',
                    quiet=True,
                    include_tags=True,
                )
                fetch_result = client.fetch(
                    remote_path.encode('utf-8'),
                    repository,
                )
                self._replace_remote_refs(repository, fetch_result.refs)
        except (
            OSError,
            UnicodeError,
            ValueError,
            FileFormatException,
            GitProtocolError,
            HTTPError,
            HTTPProxyUnauthorized,
            HTTPUnauthorized,
            NotGitRepository,
            PorcelainError,
        ) as error:
            raise RuntimeError(
                'The remote skill repository could not be refreshed.'
            ) from error

    def _replace_remote_refs(
        self,
        repository: Repo,
        remote_refs: Mapping[bytes, bytes | None],
    ) -> None:
        """Replace cached remote branch and tag references after a fetch.

        Args:
            repository: Bare cache receiving the fetched references.
            remote_refs: References advertised by the remote repository.
        """
        branch_prefix = b'refs/heads/'
        tag_prefix = b'refs/tags/'
        peeled_tag_suffix = b'^{}'
        branch_refs = {
            reference[len(branch_prefix) :]: object_id
            for reference, object_id in remote_refs.items()
            if reference.startswith(branch_prefix) and object_id is not None
        }
        tag_refs = {
            reference[len(tag_prefix) :]: object_id
            for reference, object_id in remote_refs.items()
            if (
                reference.startswith(tag_prefix)
                and not reference.endswith(peeled_tag_suffix)
                and object_id is not None
            )
        }
        repository.refs.import_refs(
            b'refs/remotes/origin',
            branch_refs,
            prune=True,
        )
        repository.refs.import_refs(
            b'refs/tags',
            tag_refs,
            prune=True,
        )

    def _resolve_revision(self) -> str:
        """Resolve the configured revision to a full commit identifier.

        Returns:
            Full lowercase Git commit identifier.

        Raises:
            RuntimeError: If the revision is not a cached commit.
        """
        revision = self._configuration.revision.encode('utf-8')
        candidates = [revision]
        if not revision.startswith(b'refs/') and re.fullmatch(
            rb'[0-9a-fA-F]{40,64}',
            revision,
        ) is None:
            candidates = [
                b'refs/remotes/origin/' + revision,
                b'refs/tags/' + revision,
                b'refs/heads/' + revision,
                revision,
            ]

        try:
            with Repo(self._cache_path) as repository:
                for candidate in candidates:
                    try:
                        commit = parse_commit(repository, candidate)
                    except (
                        KeyError,
                        ObjectMissing,
                        RefFormatError,
                        WrongObjectException,
                    ):
                        continue
                    commit_sha = commit.id.decode('ascii').lower()
                    if re.fullmatch(r'[0-9a-f]{40,64}', commit_sha):
                        return commit_sha
        except (
            OSError,
            UnicodeError,
            FileFormatException,
            NotGitRepository,
        ) as error:
            raise RuntimeError(
                'The cached skill repository could not be read.'
            ) from error

        raise RuntimeError(
            'The configured Git revision did not resolve to a commit.'
        )

    def _load_snapshot(self, commit_sha: str) -> SkillCatalogueSnapshot:
        """Export and parse a candidate commit in an isolated directory.

        Args:
            commit_sha: Full Git commit identifier to export.

        Returns:
            The validated immutable catalogue snapshot.

        Raises:
            RuntimeError: If the commit cannot be materialized.
            ValueError: If package validation fails.
        """
        try:
            with tempfile.TemporaryDirectory(
                prefix='mosaic-skill-snapshot-'
            ) as temporary_directory:
                export_root = Path(temporary_directory) / 'export'
                export_root.mkdir()
                self._export_commit(commit_sha, export_root)
                return self._package_parser.parse_catalogue(
                    export_root,
                    commit_sha,
                )
        except OSError as error:
            raise RuntimeError(
                'The Git catalogue snapshot could not be materialized.'
            ) from error

    def _export_commit(self, commit_sha: str, export_root: Path) -> None:
        """Materialize regular files directly from a Dulwich commit tree.

        Args:
            commit_sha: Full Git commit identifier to materialize.
            export_root: Isolated destination for the commit contents.

        Raises:
            RuntimeError: If an object, path, or file mode is unsupported.
        """
        try:
            with Repo(self._cache_path) as repository:
                commit = parse_commit(repository, commit_sha)
                for entry in iter_commit_contents(
                    repository.object_store,
                    commit,
                ):
                    if not stat.S_ISREG(entry.mode):
                        raise RuntimeError(
                            'The Git commit contains a symbolic link, '
                            'submodule, or unsupported entry.'
                        )
                    try:
                        relative_path = PurePosixPath(
                            entry.path.decode('utf-8')
                        )
                    except UnicodeError as error:
                        raise RuntimeError(
                            'The Git commit contains a non-UTF-8 path.'
                        ) from error
                    if relative_path.is_absolute() or '..' in (
                        relative_path.parts
                    ):
                        raise RuntimeError(
                            'The Git commit contains an unsafe path.'
                        )

                    blob = repository[entry.sha]
                    if not isinstance(blob, Blob):
                        raise RuntimeError(  # noqa: TRY004
                            'The Git commit contains a non-file object.'
                        )
                    destination = export_root.joinpath(*relative_path.parts)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(blob.data)
                    destination.chmod(
                        0o755 if entry.mode & stat.S_IXUSR else 0o644
                    )
        except RuntimeError:
            raise
        except (
            OSError,
            KeyError,
            FileFormatException,
            NotGitRepository,
            ObjectMissing,
            RefFormatError,
            WrongObjectException,
        ) as error:
            raise RuntimeError(
                'The Git commit contents could not be read.'
            ) from error

    def _recover_previous_snapshot(
        self,
        previous_commit: str | None,
    ) -> SkillCatalogueSnapshot:
        """Return or reconstruct the last valid snapshot after failure.

        Args:
            previous_commit: Persisted commit previously validated as active.

        Returns:
            The last valid immutable catalogue snapshot.

        Raises:
            RuntimeError: If no valid prior snapshot is available.
        """
        if self._snapshot is not None:
            return self._snapshot
        if previous_commit is not None:
            try:
                previous_snapshot = self._load_snapshot(previous_commit)
            except (RuntimeError, ValueError) as error:
                raise RuntimeError(
                    'Neither the remote nor cached skill snapshot is valid.'
                ) from error
            self._snapshot = previous_snapshot
            return previous_snapshot
        raise RuntimeError(
            'No valid skill catalogue snapshot is available.'
        )

    def _read_active_commit(self) -> str | None:
        """Read the last atomically activated commit from the bare cache.

        Returns:
            The validated commit identifier, or ``None`` when absent.
        """
        active_commit_path = self._cache_path / self._ACTIVE_COMMIT_FILE
        try:
            commit_sha = active_commit_path.read_text(
                encoding='ascii'
            ).strip()
        except (FileNotFoundError, OSError, UnicodeError):
            return None
        if re.fullmatch(r'[0-9a-f]{40,64}', commit_sha) is None:
            return None
        return commit_sha

    def _persist_active_commit_marker(self, commit_sha: str) -> None:
        """Atomically persist the last successfully validated commit.

        Args:
            commit_sha: Full identifier of the validated commit.

        Raises:
            RuntimeError: If the activation marker cannot be persisted.
        """
        active_commit_path = self._cache_path / self._ACTIVE_COMMIT_FILE
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='ascii',
                dir=self._cache_path,
                prefix='.mosaic-active-',
                delete=False,
            ) as temporary_file:
                temporary_file.write(f'{commit_sha}\n')
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, active_commit_path)
        except OSError as error:
            raise RuntimeError(
                'The validated skill snapshot could not be activated.'
            ) from error

    def _build_transport_configuration(self) -> ConfigDict:
        """Create in-memory Dulwich configuration for Git transport.

        Returns:
            Configuration containing the timeout and Bearer authorization.
        """
        configuration = ConfigDict()
        configuration.set(
            (b'http',),
            b'timeout',
            str(
                self._configuration.synchronization_timeout_seconds
            ).encode('ascii'),
        )
        configuration.set(
            (b'http',),
            b'extraHeader',
            f'Authorization: Bearer {self._access_token}'.encode(),
        )
        configuration.set(
            (b'http',),
            b'sslVerify',
            b'false',
        )
        return configuration

    def _persist_transport_configuration(self, repository: Repo) -> None:
        """Persist the transport timeout used by subsequent fetches.

        Args:
            repository: Newly cloned bare Dulwich repository.

        Raises:
            OSError: If the local repository configuration cannot be written.
        """
        configuration = repository.get_config()
        configuration.set(
            (b'http',),
            b'timeout',
            str(
                self._configuration.synchronization_timeout_seconds
            ).encode('ascii'),
        )
        configuration.write_to_path()

    @property
    def _access_token(self) -> str:
        """Return the private token only at the Dulwich transport boundary.

        Returns:
            Plain Bearer token required by Dulwich.
        """
        return self._configuration.access_token.get_secret_value()
