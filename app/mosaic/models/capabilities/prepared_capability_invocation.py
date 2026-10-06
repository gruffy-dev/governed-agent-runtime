"""Prepared provider-tool invocation for a resolved capability."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .capability_result_binding import CapabilityResultBinding


class PreparedCapabilityInvocation(BaseModel):
    """Return validated concrete arguments for one provider-tool call."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    status: Literal[
        'ready',
        'missing_arguments',
        'invalid_arguments',
        'unavailable',
    ] = Field(
        description='Whether the concrete invocation is ready to execute.',
    )
    capability_name: str = Field(
        description='Semantic capability being prepared.',
        min_length=1,
    )
    provider_name: str | None = Field(
        default=None,
        description='Selected provider when the capability is available.',
    )
    tool_name: str | None = Field(
        default=None,
        description='Selected concrete provider tool when available.',
    )
    tool_arguments: dict[str, JsonValue] = Field(
        default_factory=dict,
        description='Validated concrete arguments for the provider tool.',
    )
    result_binding: CapabilityResultBinding | None = Field(
        default=None,
        description='Bounded reduction selected with the provider binding.',
    )
    missing_semantic_argument_names: tuple[str, ...] = Field(
        default=(),
        description='Required semantic inputs not supplied for preparation.',
    )
    invalid_semantic_argument_names: tuple[str, ...] = Field(
        default=(),
        description='Supplied semantic inputs rejected by binding rules.',
    )
    ignored_semantic_argument_names: tuple[str, ...] = Field(
        default=(),
        description='Supplied semantic inputs not used by the binding.',
    )

    @model_validator(mode='after')
    def validate_status_consistency(self) -> Self:
        """Validate consistency between status and invocation fields.

        Returns:
            The validated prepared invocation.

        Raises:
            ValueError: If readiness, provider details, concrete arguments, or
                missing inputs are inconsistent with the status.
        """
        has_provider = (
            self.provider_name is not None
            and self.tool_name is not None
        )
        if self.status == 'ready':
            if (
                not has_provider
                or self.missing_semantic_argument_names
                or self.invalid_semantic_argument_names
            ):
                raise ValueError(
                    'A ready invocation requires a provider and valid inputs.'
                )
        elif self.status == 'missing_arguments':
            if (
                not has_provider
                or not self.missing_semantic_argument_names
                or self.invalid_semantic_argument_names
            ):
                raise ValueError(
                    'A missing-arguments result requires provider details and '
                    'only missing inputs.'
                )
        elif self.status == 'invalid_arguments':
            if not has_provider or not self.invalid_semantic_argument_names:
                raise ValueError(
                    'An invalid-arguments result requires provider details '
                    'and at least one invalid input.'
                )
        elif (
            has_provider
            or self.tool_arguments
            or self.result_binding is not None
            or self.missing_semantic_argument_names
            or self.invalid_semantic_argument_names
        ):
            raise ValueError(
                'An unavailable invocation cannot contain provider details or '
                'argument results.'
            )

        return self
