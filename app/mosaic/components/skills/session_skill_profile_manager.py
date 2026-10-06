"""ADA session-state persistence for trusted skill profiles."""

from pydantic import BaseModel, ConfigDict, Field

from ...interfaces.orchestration.callback_context_protocol import (
    CallbackContextProtocol,
)
from ...models.skills.session_skill_profile import SessionSkillProfile
from .session_skill_profile_resolver import SessionSkillProfileResolver


class SessionSkillProfileManager(BaseModel):
    """Persist only the deployment-authorised profile for each ADA session."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    resolver: SessionSkillProfileResolver = Field(
        description='Trusted session skill-profile resolver.',
    )
    state_key: str = Field(
        default='mosaic:skill-profile',
        description='ADA session-state key containing the bound profile.',
        min_length=1,
    )

    def ensure_profile(
        self,
        context: CallbackContextProtocol,
    ) -> SessionSkillProfile:
        """Resolve and persist the trusted profile for the current session.

        Existing state is never treated as authorization because callers can
        supply session state in the current unauthenticated ADA configuration.
        The deployment mapping is re-evaluated and overwrites any conflicting
        value before the agent or a skill tool can use it.

        Args:
            context: ADA callback or tool context for the current session.

        Returns:
            Trusted profile bound to the active catalogue snapshot.
        """
        expected_profile = self.resolver.resolve(context.session.id)
        serialized_profile = expected_profile.model_dump(mode='json')
        if context.state.get(self.state_key) != serialized_profile:
            context.state[self.state_key] = serialized_profile
        return expected_profile
