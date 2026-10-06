"""Persistence contract for compact session target context."""

from typing import Protocol, runtime_checkable

from ...models.orchestration.session_target_context import SessionTargetContext
from .callback_context_protocol import CallbackContextProtocol


@runtime_checkable
class SessionTargetContextStoreProtocol(Protocol):
    """Read and mutate active target state without exposing its storage."""

    def get(
        self,
        context: CallbackContextProtocol,
    ) -> SessionTargetContext | None:
        """Return the active target state when one exists.

        Args:
            context: ADA context containing session-scoped state.

        Returns:
            Validated target context or ``None`` when no target is saved.

        Raises:
            pydantic.ValidationError: If persisted target state is malformed.
        """
        ...

    def set(
        self,
        context: CallbackContextProtocol,
        target_id: str,
    ) -> SessionTargetContext:
        """Persist and return one validated canonical target.

        Args:
            context: ADA context containing session-scoped state.
            target_id: Canonical target identity to retain.

        Returns:
            Persisted immutable target context.

        Raises:
            pydantic.ValidationError: If the target identity is malformed.
        """
        ...

    def clear(self, context: CallbackContextProtocol) -> None:
        """Remove any active target from the supplied session.

        Args:
            context: ADA context containing session-scoped state.
        """
        ...
