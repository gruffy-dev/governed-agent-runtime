"""Immutable externally supplied capability-runtime snapshot."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .capability import Capability
from .mcp_provider_configuration import McpProviderConfiguration
from .target_definition import TargetDefinition


class CapabilityRuntimeSnapshot(BaseModel):
    """Bind semantic capabilities to validated live MCP providers."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    schema_version: Literal[3] = Field(
        description='Version of the external snapshot document format.',
    )
    snapshot_id: str = Field(
        description='Deployment-controlled immutable snapshot identity.',
        min_length=1,
        max_length=255,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9._:-]*$',
    )
    targets: tuple[TargetDefinition, ...] = Field(
        default=(),
        description='Canonical targets governed by contributing verticals.',
    )
    providers: tuple[McpProviderConfiguration, ...] = Field(
        description='Live MCP providers available to the runtime.',
        min_length=1,
    )
    capabilities: tuple[Capability, ...] = Field(
        description='Semantic capabilities backed by the declared providers.',
        min_length=1,
    )

    @model_validator(mode='after')
    def validate_references(self) -> Self:
        """Reject duplicate identities and ungoverned provider bindings.

        Returns:
            Validated immutable capability-runtime snapshot.

        Raises:
            ValueError: If provider or capability names repeat, a binding
                references an undeclared provider or tool, or a live binding
                omits its result-reduction contract.
        """
        target_ids = [target.id for target in self.targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError('Canonical target identities must be unique.')

        alias_keys = [
            (target.vertical, alias.casefold())
            for target in self.targets
            for alias in target.aliases
        ]
        if len(alias_keys) != len(set(alias_keys)):
            raise ValueError(
                'Target aliases must be unique within each vertical.'
            )

        declared_target_ids = set(target_ids)
        for provider in self.providers:
            routing = provider.routing
            if routing.mode == 'target_independent':
                continue
            referenced_target_ids = (
                {routing.target_id}
                if routing.mode == 'endpoint_per_target'
                else {
                    binding.target_id
                    for binding in routing.target_bindings
                }
            )
            if not referenced_target_ids.issubset(declared_target_ids):
                raise ValueError(
                    'Provider routing must reference declared targets.'
                )

        provider_names = [provider.provider_name for provider in self.providers]
        if len(provider_names) != len(set(provider_names)):
            raise ValueError('Capability provider names must be unique.')

        capability_names = [capability.name for capability in self.capabilities]
        if len(capability_names) != len(set(capability_names)):
            raise ValueError('Capability names must be unique.')

        for capability in self.capabilities:
            for binding in capability.provider_bindings:
                matching_providers = tuple(
                    provider
                    for provider in self.providers
                    if provider.provider_type == binding.provider_type
                    and binding.tool_name in provider.allowed_tool_names
                )
                if not matching_providers:
                    raise ValueError(
                        'Capability bindings must reference a declared '
                        'provider type with the allowlisted tool.'
                    )
                if binding.result_binding is None:
                    raise ValueError(
                        'Live capability bindings require result reduction.'
                    )
                for provider in matching_providers:
                    target_argument_name = (
                        provider.routing.target_argument_name
                    )
                    if (
                        target_argument_name is not None
                        and target_argument_name in {
                            argument.tool_argument_name
                            for argument in binding.argument_bindings
                        }
                    ):
                        raise ValueError(
                            'Shared provider target arguments must be '
                            'controlled only by provider routing.'
                        )
                for target_id in (None, *target_ids):
                    compatible_providers = tuple(
                        provider
                        for provider in matching_providers
                        if provider.supports_target(target_id)
                    )
                    if len(compatible_providers) > 1:
                        raise ValueError(
                            'Provider type, tool, and target routing must '
                            'resolve to at most one provider instance.'
                        )
        return self
