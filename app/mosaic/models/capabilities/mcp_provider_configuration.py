"""Trusted configuration for one live MCP capability provider."""

from typing import Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator

from .provider_routing_configuration import ProviderRoutingConfiguration


class McpProviderConfiguration(BaseModel):
    """Configure one externally declared MCP provider connection."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    provider_name: str = Field(
        description='Governed provider identity used by capability bindings.',
        min_length=1,
        pattern=r'^[a-z][a-z0-9-]*$',
    )
    provider_type: str = Field(
        description='Provider function used for target-aware selection.',
        min_length=1,
        max_length=100,
        pattern=r'^[a-z][a-z0-9-]*$',
    )
    transport: Literal['streamable_http'] = Field(
        description='MCP transport implemented by the runtime adapter.',
    )
    header_strategy: Literal['ada_request_context'] = Field(
        description='Trusted request-header strategy for this connection.',
    )
    base_url: AnyHttpUrl = Field(
        description='Streamable HTTP endpoint for the MCP provider.',
    )
    allowed_tool_names: tuple[str, ...] = Field(
        description='Exact MCP tools callable through this provider.',
        min_length=1,
    )
    routing: ProviderRoutingConfiguration = Field(
        description='Trusted target-routing policy for this provider.',
    )

    @model_validator(mode='after')
    def validate_allowed_tool_names(self) -> Self:
        """Reject malformed or duplicated concrete MCP tool names.

        Returns:
            Validated immutable provider configuration.

        Raises:
            ValueError: If names repeat or are not lower snake case.
        """
        if len(self.allowed_tool_names) != len(set(self.allowed_tool_names)):
            raise ValueError('Allowed MCP tool names must be unique.')
        if any(
            not name
            or not name.replace('_', '').isalnum()
            or name.lower() != name
            or name[0].isdigit()
            for name in self.allowed_tool_names
        ):
            raise ValueError(
                'Allowed MCP tool names must use lower snake case.'
            )
        return self

    def supports_target(self, target_id: str | None) -> bool:
        """Return whether this provider can serve a canonical target.

        Target-independent providers remain usable when a session happens to
        retain a target because the capability itself requires no routing.

        Args:
            target_id: Trusted canonical target identity, when available.

        Returns:
            Whether the routing configuration permits this provider.
        """
        if self.routing.mode == 'target_independent':
            return True
        if target_id is None:
            return False
        if self.routing.mode == 'endpoint_per_target':
            return self.routing.target_id == target_id
        return any(
            binding.target_id == target_id
            for binding in self.routing.target_bindings
        )
