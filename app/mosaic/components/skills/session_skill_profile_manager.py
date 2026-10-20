from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ...interfaces.orchestration.callback_context_protocol import CallbackContextProtocol
from ...models.identity.trusted_request_context import TrustedRequestContext
from ...models.orchestration.orchestration_state import OrchestrationState
from ...models.skills.session_skill_profile import SessionSkillProfile
from ..orchestration.orchestration_transition_controller import OrchestrationTransitionController
from .session_skill_profile_resolver import SessionSkillProfileResolver
from .workspace_skill_profile_resolver import WorkspaceSkillProfileResolver


class SessionSkillProfileManager(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    resolver: SessionSkillProfileResolver | WorkspaceSkillProfileResolver = Field(
        description='Trusted session skill-profile resolver.',
    )
    state_key: str = Field(
        default='mosaic:skill-profile',
        description='ADA session-state key containing the bound profile.',
        min_length=1,
    )
    orchestration_state_key: str = Field(
        default_factory=lambda: OrchestrationTransitionController().state_key,
        description='Session-state key containing the Goal owning this binding.',
        min_length=1,
    )

    def ensure_profile(
        self,
        context: CallbackContextProtocol,
    ) -> SessionSkillProfile:
        """
        Bind workspace Skills once per Goal, retaining them through clarification.

        Cached bindings require the protected private dispatch boundary: the public
        API never accepts caller-supplied session state or identity. Legacy profile
        resolution remains available only through explicit alternative composition.

        :param context: Private ADA callback or tool context for the active Goal.

        :return: Immutable authorised profile for this Goal.

        :raises ValueError: If a workspace binding lacks its owning Goal or identity.
        """
        if isinstance(self.resolver, SessionSkillProfileResolver):
            expected_profile = self.resolver.resolve(context.session.id)
        else:
            goal = OrchestrationState.model_validate(
                context.state.get(self.orchestration_state_key)
            )
            if goal.active_invocation_id != context.invocation_id:
                raise ValueError(
                    'Workspace Skill binding requires the active invocation.'
                )
            identity = TrustedRequestContext(
                app_name=context.session.app_name, user_id=context.session.user_id
            )
            conversation_id = UUID(context.session.id)
            raw_profile = context.state.get(self.state_key)
            if raw_profile is not None:
                bound = SessionSkillProfile.model_validate(raw_profile)
                if bound.goal_id == goal.goal_id:
                    if (
                        bound.user_id != identity.user_id
                        or bound.app_name != identity.app_name
                        or bound.session_id != str(conversation_id)
                        or bound.catalogue_commit_sha
                        != self.resolver.catalogue_snapshot.commit_sha
                    ):
                        raise ValueError(
                            'Workspace Skill binding does not match its owner or catalogue.'
                        )
                    return bound
            if goal.skill_discovery_completed or goal.skill_batch_attempted:
                raise ValueError(
                    'An established Goal cannot acquire a replacement Skill binding.'
                )
            expected_profile = self.resolver.resolve(
                identity, conversation_id, goal.goal_id
            )
        serialised_profile = expected_profile.model_dump(mode='json')
        if context.state.get(self.state_key) != serialised_profile:
            context.state[self.state_key] = serialised_profile
        return expected_profile
