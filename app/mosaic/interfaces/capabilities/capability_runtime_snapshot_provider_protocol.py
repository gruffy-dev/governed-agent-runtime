"""Provider contract for immutable capability-runtime snapshots."""

from typing import Protocol

from ...models.capabilities.capability_runtime_snapshot import (
    CapabilityRuntimeSnapshot,
)


class CapabilityRuntimeSnapshotProviderProtocol(Protocol):
    """Load one validated capability-runtime snapshot at startup."""

    def load(self) -> CapabilityRuntimeSnapshot:
        """Return the configured immutable snapshot or fail closed.

        Returns:
            Fully validated immutable capability-runtime snapshot.

        Raises:
            RuntimeError: If no valid configured snapshot can be supplied.
        """
        ...
