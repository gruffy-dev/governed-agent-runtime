"""Validated outcome of deterministic session-target resolution."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .target_resolution_candidate import TargetResolutionCandidate


class TargetResolutionResult(BaseModel):
    """Report a resolved target or a safe clarification requirement."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    status: Literal['resolved', 'required', 'ambiguous', 'unknown'] = Field(
        description='Outcome of matching configured target identities.',
    )
    resolved_target: TargetResolutionCandidate | None = Field(
        default=None,
        description='Validated target available for the current session.',
    )
    candidate_targets: tuple[TargetResolutionCandidate, ...] = Field(
        default=(),
        description='Safe choices presented when an alias is ambiguous.',
    )
    previous_target: TargetResolutionCandidate | None = Field(
        default=None,
        description='Prior target replaced by an explicit user selection.',
    )
    target_changed: bool = Field(
        default=False,
        description='Whether the explicit selection replaced a prior target.',
    )

    @model_validator(mode='after')
    def validate_status_fields(self) -> Self:
        """Require fields consistent with the target-resolution outcome.

        Returns:
            Validated immutable target-resolution result.

        Raises:
            ValueError: If resolved, ambiguous, or changed-target metadata is
                absent or conflicts with the declared status.
        """
        if self.status == 'resolved':
            if self.resolved_target is None or self.candidate_targets:
                raise ValueError(
                    'A resolved target requires one result and no candidates.'
                )
        elif self.status == 'ambiguous':
            if self.resolved_target is not None or len(
                self.candidate_targets
            ) < 2:
                raise ValueError(
                    'An ambiguous target requires at least two candidates.'
                )
        elif self.resolved_target is not None or self.candidate_targets:
            raise ValueError(
                'An unresolved target cannot contain results or candidates.'
            )

        if self.target_changed:
            if (
                self.status != 'resolved'
                or self.previous_target is None
                or self.resolved_target is None
                or self.previous_target.target_id
                == self.resolved_target.target_id
            ):
                raise ValueError(
                    'A changed target requires distinct previous and resolved '
                    'targets.'
                )
        elif self.previous_target is not None:
            raise ValueError(
                'A previous target is retained only when the target changes.'
            )
        return self
