"""Deterministic resolver for configured session targets."""

from pydantic import BaseModel, ConfigDict, Field

from ...interfaces.orchestration.callback_context_protocol import CallbackContextProtocol
from ...interfaces.orchestration.session_target_context_store_protocol import SessionTargetContextStoreProtocol
from ...models.capabilities.target_definition import TargetDefinition
from ...models.capabilities.target_resolution_candidate import TargetResolutionCandidate
from ...models.capabilities.target_resolution_result import TargetResolutionResult


class SessionTargetResolver(BaseModel):
    """Resolve user-facing names without exposing endpoints to the model."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra='forbid',
        frozen=True,
    )

    targets: tuple[TargetDefinition, ...] = Field(
        default=(),
        description='Validated canonical targets in the active snapshot.',
    )
    context_store: SessionTargetContextStoreProtocol = Field(
        description='Replaceable persistence for the active session target.',
    )

    def resolve(
        self,
        context: CallbackContextProtocol,
        target_name: str | None = None,
        allowed_verticals: tuple[str, ...] = (),
    ) -> TargetResolutionResult:
        """Resolve an explicit name or reuse the active session target.

        Args:
            context: ADA context containing session-scoped target state.
            target_name: Optional user-facing alias, display name, or canonical
                target identity.
            allowed_verticals: Trusted vertical scope derived by the caller.

        Returns:
            Resolved target or a safe required, ambiguous, or unknown result.

        Raises:
            pydantic.ValidationError: If persisted target state is malformed.
        """
        eligible_targets = self._eligible_targets(allowed_verticals)
        current_target = self._current_target(context)
        normalized_name = (
            target_name.strip().casefold()
            if isinstance(target_name, str) and target_name.strip()
            else None
        )

        if normalized_name is None:
            if current_target is None or current_target not in eligible_targets:
                return TargetResolutionResult(status='required')
            return TargetResolutionResult(
                status='resolved',
                resolved_target=self._candidate(current_target),
            )

        matches = tuple(
            target
            for target in eligible_targets
            if normalized_name == target.id.casefold()
            or normalized_name == target.display_name.casefold()
            or normalized_name in {
                alias.casefold() for alias in target.aliases
            }
        )
        if not matches:
            return TargetResolutionResult(status='unknown')
        if len(matches) > 1:
            return TargetResolutionResult(
                status='ambiguous',
                candidate_targets=tuple(
                    self._candidate(target) for target in matches
                ),
            )

        resolved_target = matches[0]
        target_changed = (
            current_target is not None
            and current_target.id != resolved_target.id
        )
        self.context_store.set(context, resolved_target.id)
        return TargetResolutionResult(
            status='resolved',
            resolved_target=self._candidate(resolved_target),
            previous_target=(
                self._candidate(current_target) if target_changed else None
            ),
            target_changed=target_changed,
        )

    def _current_target(
        self,
        context: CallbackContextProtocol,
    ) -> TargetDefinition | None:
        """Return the configured target saved for the session.

        Args:
            context: ADA context containing session-scoped target state.

        Returns:
            Current configured target or ``None`` when absent or stale.

        Raises:
            pydantic.ValidationError: If persisted target state is malformed.
        """
        target_context = self.context_store.get(context)
        if target_context is None:
            return None
        current_target = next(
            (
                target
                for target in self.targets
                if target.id == target_context.target_id
            ),
            None,
        )
        if current_target is None:
            self.context_store.clear(context)
        return current_target

    def _eligible_targets(
        self,
        allowed_verticals: tuple[str, ...],
    ) -> tuple[TargetDefinition, ...]:
        """Filter targets using only caller-supplied trusted vertical scope.

        Args:
            allowed_verticals: Vertical identities permitted by the caller.

        Returns:
            Targets in the supplied verticals, or every target when unscoped.
        """
        if not allowed_verticals:
            return self.targets
        normalized_verticals = {
            vertical.strip().casefold()
            for vertical in allowed_verticals
            if vertical.strip()
        }
        return tuple(
            target
            for target in self.targets
            if target.vertical.casefold() in normalized_verticals
        )

    def _candidate(
        self,
        target: TargetDefinition,
    ) -> TargetResolutionCandidate:
        """Create safe model-visible identity metadata for one target.

        Args:
            target: Configured target selected or offered for clarification.

        Returns:
            Provider-free target identity and display name.
        """
        return TargetResolutionCandidate(
            target_id=target.id,
            display_name=target.display_name,
        )
