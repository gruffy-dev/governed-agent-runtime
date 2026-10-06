"""Result model for a governed semantic capability execution."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class CapabilityExecutionResult(BaseModel):
    """Report the outcome of one capability execution request."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    status: Literal[
        'success',
        'missing_arguments',
        'invalid_arguments',
        'unavailable',
        'evidence_too_large',
        'failed',
        'timed_out',
    ] = Field(
        description='Governed capability execution outcome.',
    )
    capability_name: str = Field(
        description='Semantic capability requested for execution.',
        min_length=1,
    )
    target_id: str | None = Field(
        default=None,
        description='Canonical goal target associated with this execution.',
        min_length=3,
        max_length=255,
        pattern=r'^[a-z][a-z0-9-]*/[a-z][a-z0-9-]*$',
    )
    evidence: dict[str, JsonValue] | None = Field(
        default=None,
        description='Provider evidence returned by a successful execution.',
    )
    missing_semantic_argument_names: tuple[str, ...] = Field(
        default=(),
        description='Required semantic inputs absent from the request.',
    )
    invalid_semantic_argument_names: tuple[str, ...] = Field(
        default=(),
        description='Semantic inputs rejected by capability policy.',
    )
    ignored_semantic_argument_names: tuple[str, ...] = Field(
        default=(),
        description='Unrecognised inputs that were not sent to the provider.',
    )
    error_message: str | None = Field(
        default=None,
        description='Safe failure information suitable for the agent.',
        min_length=1,
    )

    @model_validator(mode='after')
    def validate_status_consistency(self) -> Self:
        """Validate fields associated with each execution status.

        Returns:
            The validated execution result.

        Raises:
            ValueError: If evidence, argument errors, or failure information
                conflicts with the execution status.
        """
        if self.status == 'success':
            if self.evidence is None or self.error_message is not None:
                raise ValueError(
                    'A successful execution requires evidence and no error.'
                )
            if (
                self.missing_semantic_argument_names
                or self.invalid_semantic_argument_names
            ):
                raise ValueError(
                    'A successful execution cannot contain argument errors.'
                )
        elif self.status == 'missing_arguments':
            if not self.missing_semantic_argument_names:
                raise ValueError(
                    'A missing-arguments result requires missing inputs.'
                )
        elif self.status == 'invalid_arguments':
            if not self.invalid_semantic_argument_names:
                raise ValueError(
                    'An invalid-arguments result requires invalid inputs.'
                )
        elif self.status in {'evidence_too_large', 'failed', 'timed_out'}:
            if self.error_message is None:
                raise ValueError(
                    'A failed execution requires a safe error message.'
                )

        if self.status != 'success' and self.evidence is not None:
            raise ValueError(
                'Only a successful execution can contain provider evidence.'
            )

        return self
