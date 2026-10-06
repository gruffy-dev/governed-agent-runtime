"""Provider contract for immutable skill-catalogue snapshots."""

from typing import Protocol

from ...models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot


class SkillCatalogueProviderProtocol(Protocol):
    """Supply validated skill snapshots to the MOSAIC runtime."""

    def synchronize(self) -> SkillCatalogueSnapshot:
        """Synchronise the backing source and return the active snapshot.

        Returns:
            The active immutable skill-catalogue snapshot.

        Raises:
            RuntimeError: If no valid snapshot can be supplied.
        """
        ...

    def get_snapshot(self) -> SkillCatalogueSnapshot:
        """Return the active snapshot without synchronising its source.

        Returns:
            The active immutable skill-catalogue snapshot.

        Raises:
            RuntimeError: If synchronisation has not produced a snapshot.
        """
        ...
