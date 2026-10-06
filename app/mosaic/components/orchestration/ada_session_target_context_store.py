"""ADA session-state implementation of target-context persistence."""

from pydantic import BaseModel, ConfigDict, Field

from ...interfaces.orchestration.callback_context_protocol import CallbackContextProtocol
from ...models.orchestration.session_target_context import SessionTargetContext


class AdaSessionTargetContextStore(BaseModel):
    """Persist compact canonical target state through an ADA context."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    state_key: str = Field(
        default='mosaic:session-target',
        description='ADA session-state key containing active target context.',
        min_length=1,
    )

    def get(
        self,
        context: CallbackContextProtocol,
    ) -> SessionTargetContext | None:
        """Return validated active target state from ADA.

        Args:
            context: ADA context containing session-scoped state.

        Returns:
            Active target context or ``None`` when the session has none.

        Raises:
            pydantic.ValidationError: If persisted target state is malformed.
        """
        raw_context = context.state.get(self.state_key)
        if raw_context is None:
            return None
        return SessionTargetContext.model_validate(raw_context)

    def set(
        self,
        context: CallbackContextProtocol,
        target_id: str,
    ) -> SessionTargetContext:
        """Persist one validated canonical target through ADA.

        Args:
            context: ADA context containing session-scoped state.
            target_id: Canonical target identity to retain.

        Returns:
            Persisted immutable target context.

        Raises:
            pydantic.ValidationError: If the target identity is malformed.
        """
        target_context = SessionTargetContext(target_id=target_id)
        context.state[self.state_key] = target_context.model_dump(mode='json')
        return target_context

    def clear(self, context: CallbackContextProtocol) -> None:
        """Remove active target state from ADA.

        Args:
            context: ADA context containing session-scoped state.
        """
        context.state.pop(self.state_key, None)
