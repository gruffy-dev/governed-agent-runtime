"""File-backed provider for capability-runtime snapshots."""

import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...models.capabilities.capability_runtime_snapshot import (
    CapabilityRuntimeSnapshot,
)
from ...models.capabilities.capability_runtime_snapshot_configuration import (
    CapabilityRuntimeSnapshotConfiguration,
)


class FileCapabilityRuntimeSnapshotProvider(BaseModel):
    """Load and validate a bounded deployment-managed JSON snapshot."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    configuration: CapabilityRuntimeSnapshotConfiguration = Field(
        description='Trusted snapshot location and startup size limit.',
    )

    def load(self) -> CapabilityRuntimeSnapshot:
        """Read one complete snapshot and fail startup on any defect.

        Returns:
            Fully validated immutable capability-runtime snapshot.

        Raises:
            RuntimeError: If the snapshot is unreadable, oversized, malformed,
                or inconsistent with the supported snapshot schema.
        """
        snapshot_path = self.configuration.snapshot_path.expanduser()
        try:
            if (
                snapshot_path.stat().st_size
                > self.configuration.maximum_snapshot_bytes
            ):
                raise RuntimeError(
                    'The capability runtime snapshot exceeds its size limit.'
                )
            raw_snapshot = snapshot_path.read_text(encoding='utf-8')
        except RuntimeError:
            raise
        except (OSError, UnicodeError) as error:
            raise RuntimeError(
                'The capability runtime snapshot cannot be read.'
            ) from error

        try:
            snapshot_data = json.loads(raw_snapshot)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                'The capability runtime snapshot is not valid JSON.'
            ) from error
        try:
            snapshot = CapabilityRuntimeSnapshot.model_validate(snapshot_data)
        except ValidationError as error:
            raise RuntimeError(
                'The capability runtime snapshot failed validation.'
            ) from error
        self._validate_result_limits(snapshot)
        return snapshot

    def _validate_result_limits(
        self,
        snapshot: CapabilityRuntimeSnapshot,
    ) -> None:
        """Reject result bindings above deployment-wide safety ceilings.

        Args:
            snapshot: Structurally valid capability-runtime snapshot.

        Raises:
            RuntimeError: If any binding exceeds the configured response or
                collection ceiling.
        """
        for capability in snapshot.capabilities:
            for provider_binding in capability.provider_bindings:
                result_binding = provider_binding.result_binding
                if result_binding is None:
                    continue
                if (
                    result_binding.maximum_response_characters
                    > self.configuration.maximum_result_response_characters
                ):
                    raise RuntimeError(
                        'A capability result response limit exceeds the '
                        'deployment ceiling.'
                    )
                if (
                    result_binding.maximum_collection_items
                    > self.configuration.maximum_result_collection_items
                ):
                    raise RuntimeError(
                        'A capability result collection limit exceeds the '
                        'deployment ceiling.'
                    )
