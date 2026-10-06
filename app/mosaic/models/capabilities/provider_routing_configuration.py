"""Target-aware routing configuration for one MCP provider instance."""

import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .provider_target_binding import ProviderTargetBinding


class ProviderRoutingConfiguration(BaseModel):
    """Declare endpoint-specific or shared-endpoint target routing."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    mode: Literal[
        'target_independent',
        'endpoint_per_target',
        'shared_endpoint',
    ] = Field(
        description='Governed strategy used to route canonical targets.',
    )
    target_id: str | None = Field(
        default=None,
        description='Canonical target atomically served by this endpoint.',
        min_length=3,
        max_length=255,
        pattern=r'^[a-z][a-z0-9-]*/[a-z][a-z0-9-]*$',
    )
    target_argument_name: str | None = Field(
        default=None,
        description='Protected tool argument used by a shared endpoint.',
        min_length=1,
        max_length=100,
        pattern=r'^[a-z][A-Za-z0-9_]*$',
    )
    target_bindings: tuple[ProviderTargetBinding, ...] = Field(
        default=(),
        description='Approved target-to-provider values for shared routing.',
    )

    @model_validator(mode='after')
    def validate_mode_configuration(self) -> Self:
        """Reject fields that conflict with the selected routing mode.

        Returns:
            Validated immutable provider routing configuration.

        Raises:
            ValueError: If required fields are absent, inapplicable fields are
                supplied, or shared target mappings are ambiguous.
        """
        if self.mode == 'target_independent':
            if (
                self.target_id is not None
                or self.target_argument_name is not None
                or self.target_bindings
            ):
                raise ValueError(
                    'Target-independent routing accepts no target fields.'
                )
            return self

        if self.mode == 'endpoint_per_target':
            if (
                self.target_id is None
                or self.target_argument_name is not None
                or self.target_bindings
            ):
                raise ValueError(
                    'Endpoint-per-target routing requires only target_id.'
                )
            return self

        if (
            self.target_id is not None
            or self.target_argument_name is None
            or not self.target_bindings
        ):
            raise ValueError(
                'Shared-endpoint routing requires an argument name and '
                'target bindings, without target_id.'
            )

        target_ids = [binding.target_id for binding in self.target_bindings]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError(
                'Shared provider target identities must be unique.'
            )

        argument_values = [
            json.dumps(
                binding.argument_value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(',', ':'),
            )
            for binding in self.target_bindings
        ]
        if len(argument_values) != len(set(argument_values)):
            raise ValueError(
                'Shared provider target argument values must be unique.'
            )
        return self
