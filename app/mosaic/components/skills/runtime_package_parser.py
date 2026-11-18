from pathlib import Path

from ...models.capabilities.capability_runtime_snapshot_configuration import CapabilityRuntimeSnapshotConfiguration
from ...models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot
from ..capabilities.file_capability_runtime_snapshot_provider import FileCapabilityRuntimeSnapshotProvider
from .skill_package_parser import SkillPackageParser


class RuntimePackageParser(SkillPackageParser):
    def parse_catalogue(
        self,
        repository_root: Path,
        commit_sha: str,
    ) -> SkillCatalogueSnapshot:
        """
        Validate Skills and capabilities exported from one Git commit.

        :param repository_root: Root of the isolated Git export.
        :param commit_sha: Full identifier of the exported commit.

        :return: Catalogue carrying its matching capability configuration.

        :raises RuntimeError: If the capability file is missing or invalid.
        :raises ValueError: If Skills or their capability references are invalid.
        """
        skills = super().parse_catalogue(repository_root, commit_sha)
        capabilities = FileCapabilityRuntimeSnapshotProvider(
            configuration=CapabilityRuntimeSnapshotConfiguration(
                snapshot_path=(
                    repository_root / 'config' / 'capability-runtime-snapshot.json'
                ).resolve(),
            ),
        ).load()
        return SkillCatalogueSnapshot(
            commit_sha=skills.commit_sha,
            loaded_at=skills.loaded_at,
            skills=skills.skills,
            groups=skills.groups,
            capability_runtime_snapshot=capabilities,
        )
