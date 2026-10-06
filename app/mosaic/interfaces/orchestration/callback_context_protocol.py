"""ADA callback-context contract required by MOSAIC orchestration."""

from collections.abc import MutableMapping
from typing import Protocol

from .session_protocol import SessionProtocol


class CallbackContextProtocol(Protocol):
    """Expose the ADA context fields required by the controller."""

    invocation_id: str
    session: SessionProtocol
    state: MutableMapping[str, object]
