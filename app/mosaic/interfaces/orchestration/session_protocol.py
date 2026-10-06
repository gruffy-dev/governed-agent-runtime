"""ADA session contract required by MOSAIC orchestration."""

from typing import Protocol


class SessionProtocol(Protocol):
    """Expose the ADA session identifier required by MOSAIC."""

    id: str
