"""ADA tool contract required by MOSAIC orchestration."""

from typing import Protocol


class ToolProtocol(Protocol):
    """Expose the ADA tool fields required by the controller."""

    name: str
