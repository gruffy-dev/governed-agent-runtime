"""Goal-scoped governed capability discovery tool."""

from pydantic import BaseModel, ConfigDict, Field

from ...interfaces.orchestration.callback_context_protocol import CallbackContextProtocol
from ...models.capabilities.target_resolution_result import TargetResolutionResult
from ...models.orchestration.orchestration_state import OrchestrationState
from .capability_catalogue_and_resolver import CapabilityCatalogueAndResolver
from .session_target_resolver import SessionTargetResolver


class CapabilityDiscoveryService(BaseModel):
    """Expose only bounded semantic capabilities relevant to one goal."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    capability_catalogue_and_resolver: CapabilityCatalogueAndResolver = Field(
        description='Authorised runtime capability snapshot and resolver.',
    )
    session_target_resolver: SessionTargetResolver = Field(
        description='Deterministic resolver for the active session target.',
    )
    orchestration_state_key: str = Field(
        default='mosaic:orchestration',
        description='ADA session-state key containing current goal state.',
        min_length=1,
    )

    def discover_capabilities(
        self,
        tool_context: CallbackContextProtocol,
        target_name: str | None = None,
    ) -> dict[str, object]:
        """Expose the bounded capability set declared by loaded skills.

        Call this once after loading the complete relevant skill batch and
        before capability execution. Only required and optional capability
        names declared by those loaded skills are resolved against the trusted
        runtime snapshot. The model cannot add names or search the wider
        capability registry.

        Args:
            tool_context: ADA-injected context excluded from the model schema.
            target_name: Optional user-supplied target alias, display name, or
                canonical identity. Provider endpoints are never accepted.

        Returns:
            Provider-free semantic capability metadata for this goal only.

        Raises:
            RuntimeError: If orchestration state was not initialized.
            pydantic.ValidationError: If persisted state is malformed.
        """
        raw_state = tool_context.state.get(self.orchestration_state_key)
        if raw_state is None:
            raise RuntimeError('MOSAIC orchestration state is not initialized.')
        state = OrchestrationState.model_validate(raw_state)
        if not state.skill_batch_loaded:
            return {
                'status': 'skill_required',
                'capabilities': [],
                'message': (
                    'Load a relevant skill before discovering capabilities.'
                ),
            }
        target_verticals = (
            self.capability_catalogue_and_resolver
            .target_verticals_for_capabilities(
                tuple(
                    dict.fromkeys(
                        (
                            *state.required_capability_names,
                            *state.optional_capability_names,
                        )
                    )
                )
            )
        )
        target_id: str | None = None
        target_result = None
        if target_verticals:
            target_result = self.session_target_resolver.resolve(
                context=tool_context,
                target_name=target_name,
                allowed_verticals=target_verticals,
            )
            if target_result.status != 'resolved':
                return self._unresolved_target_result(
                    target_result,
                    target_verticals,
                )
            if target_result.resolved_target is None:
                raise RuntimeError(
                    'Resolved target outcome omitted target metadata.'
                )
            target_id = target_result.resolved_target.target_id

        result = (
            self.capability_catalogue_and_resolver
            .discover_capability_candidates(
                required_capability_names=state.required_capability_names,
                optional_capability_names=state.optional_capability_names,
                target_id=target_id,
            )
        )
        if target_result is not None:
            result['target'] = target_result.resolved_target.model_dump(
                mode='json'
            )
            result['target_changed'] = target_result.target_changed
            if target_result.previous_target is not None:
                result['previous_target'] = (
                    target_result.previous_target.model_dump(mode='json')
                )
        return result

    def _unresolved_target_result(
        self,
        target_result: TargetResolutionResult,
        target_verticals: tuple[str, ...],
    ) -> dict[str, object]:
        """Build a provider-free clarification result for target resolution.

        Args:
            target_result: Validated resolution outcome returned by the
                session target resolver.
            target_verticals: Trusted platform scopes requiring a target.

        Returns:
            Safe target status and optional candidate identities.

        """
        response: dict[str, object] = {
            'status': f'target_{target_result.status}',
            'capabilities': [],
            'required_target_verticals': list(target_verticals),
        }
        if target_result.candidate_targets:
            response['candidate_targets'] = [
                candidate.model_dump(mode='json')
                for candidate in target_result.candidate_targets
            ]
        return response
