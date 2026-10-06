"""Goal-scoped orchestration state persisted through ADA sessions."""

from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class OrchestrationState(BaseModel):
    """Track structural rules across invocations for one user goal."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    schema_version: Literal[5] = Field(
        default=5,
        description='Schema version for persisted orchestration state.',
    )
    goal_id: str = Field(
        description='Stable identifier retained across one complete goal.',
        min_length=1,
    )
    active_invocation_id: str = Field(
        description='ADA invocation currently permitted to mutate the goal.',
        min_length=1,
    )
    phase: Literal[
        'planning',
        'executing',
        'awaiting_clarification',
        'completed',
    ] = Field(
        default='planning',
        description='Current lifecycle phase of the user goal.',
    )
    skill_discovery_completed: bool = Field(
        default=False,
        description='Whether authorised skill metadata was discovered.',
    )
    skill_batch_loaded: bool = Field(
        default=False,
        description='Whether the single permitted skill batch loaded.',
    )
    skill_batch_attempted: bool = Field(
        default=False,
        description='Whether the single permitted skill load was attempted.',
    )
    requested_skill_names: tuple[str, ...] = Field(
        default=(),
        description='Unique normalized skill names in the batch request.',
    )
    loaded_skill_names: tuple[str, ...] = Field(
        default=(),
        description='Approved skill names returned by the loader.',
    )
    required_capability_names: tuple[str, ...] = Field(
        default=(),
        description='Required capabilities declared by loaded skills.',
    )
    optional_capability_names: tuple[str, ...] = Field(
        default=(),
        description='Optional capabilities declared by loaded skills.',
    )
    required_capability_outcome_records: dict[
        str,
        tuple[
            str,
            Literal[
                'success',
                'unavailable',
                'evidence_too_large',
                'failed',
                'timed_out',
                'limit_exceeded',
                'required_capabilities_unavailable',
            ],
        ],
    ] = Field(
        default_factory=dict,
        description=(
            'Merge-safe goal-tagged terminal outcomes for required '
            'capabilities.'
        ),
    )
    capability_discovery_attempted: bool = Field(
        default=False,
        description='Whether goal-scoped capability discovery was attempted.',
    )
    capability_discovery_completed: bool = Field(
        default=False,
        description='Whether capability candidates were bound to the goal.',
    )
    candidate_capability_names: tuple[str, ...] = Field(
        default=(),
        description='Authorised semantic capabilities exposed for the goal.',
    )
    target_id: str | None = Field(
        default=None,
        description='Canonical target immutably selected for this goal.',
        min_length=3,
        max_length=255,
        pattern=r'^[a-z][a-z0-9-]*/[a-z][a-z0-9-]*$',
    )
    target_display_name: str | None = Field(
        default=None,
        description='Safe configured display name for the selected target.',
        min_length=1,
        max_length=255,
    )
    clarification_question: str | None = Field(
        default=None,
        description='Explicit clarification question recorded by the agent.',
        min_length=1,
    )

    @classmethod
    def start(cls, invocation_id: str) -> Self:
        """Create the initial state for a genuinely new goal.

        Args:
            invocation_id: ADA invocation beginning the new goal.

        Returns:
            Validated orchestration state with a new stable goal identifier.
        """
        return cls(
            goal_id=str(uuid4()),
            active_invocation_id=invocation_id,
        )

    @property
    def required_capability_outcomes(self) -> dict[str, str]:
        """Return terminal outcomes belonging to the active goal.

        Returns:
            Required capability outcomes tagged with the current goal ID.
        """
        return {
            capability_name: outcome
            for capability_name, (
                outcome_goal_id,
                outcome,
            ) in self.required_capability_outcome_records.items()
            if outcome_goal_id == self.goal_id
        }

    @model_validator(mode='after')
    def validate_phase_fields(self) -> Self:
        """Reject state that contradicts its current phase.

        Returns:
            The validated orchestration state.

        Raises:
            ValueError: If skill, capability, or clarification fields conflict
                with the persisted lifecycle phase.
        """
        if not self.skill_batch_attempted and self.requested_skill_names:
            raise ValueError(
                'Requested skill names require a skill-load attempt.'
            )
        if self.skill_batch_loaded and not self.skill_batch_attempted:
            raise ValueError(
                'A loaded skill batch requires a skill-load attempt.'
            )
        if not self.skill_batch_loaded and (
            self.loaded_skill_names
            or self.required_capability_names
            or self.optional_capability_names
            or self.required_capability_outcomes
        ):
            raise ValueError(
                'Loaded skill state requires a successful skill batch.'
            )
        if set(self.required_capability_names) & set(
            self.optional_capability_names
        ):
            raise ValueError(
                'Required and optional capabilities must not overlap.'
            )
        if not set(self.required_capability_outcomes.keys()).issubset(
            self.required_capability_names
        ):
            raise ValueError(
                'Required capability outcomes must be declared as required.'
            )
        if any(
            not outcome_goal_id.strip()
            for outcome_goal_id, _ in (
                self.required_capability_outcome_records.values()
            )
        ):
            raise ValueError(
                'Required capability outcome goal identifiers cannot be '
                'blank.'
            )
        if (
            self.capability_discovery_completed
            and not self.capability_discovery_attempted
        ):
            raise ValueError(
                'Completed capability discovery requires an attempt.'
            )
        if self.capability_discovery_attempted and not self.skill_batch_loaded:
            raise ValueError(
                'Capability discovery requires a loaded skill batch.'
            )
        if (
            not self.capability_discovery_completed
            and self.candidate_capability_names
        ):
            raise ValueError(
                'Capability candidates require completed discovery.'
            )
        if self.capability_discovery_completed and not set(
            self.required_capability_names
        ).issubset(self.candidate_capability_names):
            raise ValueError(
                'Capability candidates must include every required capability.'
            )
        declared_capability_names = set(self.required_capability_names) | set(
            self.optional_capability_names
        )
        if not set(self.candidate_capability_names).issubset(
            declared_capability_names
        ):
            raise ValueError(
                'Capability candidates must be declared by loaded skills.'
            )
        if (self.target_id is None) != (self.target_display_name is None):
            raise ValueError(
                'Goal target identity and display name must be stored '
                'together.'
            )
        if (
            self.phase != 'awaiting_clarification'
            and self.clarification_question is not None
        ):
            raise ValueError(
                'Only an awaiting-clarification state can retain a question.'
            )
        return self
