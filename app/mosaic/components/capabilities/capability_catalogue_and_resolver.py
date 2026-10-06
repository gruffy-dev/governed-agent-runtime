"""Capability catalogue and provider resolver for the MOSAIC runtime."""

import json
import re
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from ...models.capabilities.capability import Capability
from ...models.capabilities.capability_discovery_configuration import CapabilityDiscoveryConfiguration
from ...models.capabilities.capability_provider_binding import CapabilityProviderBinding
from ...models.capabilities.capability_resolution_result import CapabilityResolutionResult
from ...models.capabilities.mcp_provider_configuration import McpProviderConfiguration
from ...models.capabilities.prepared_capability_invocation import PreparedCapabilityInvocation
from ...models.capabilities.resolved_capability import ResolvedCapability


class CapabilityCatalogueAndResolver(BaseModel):
    """Resolve semantic capability requirements to concrete provider tools."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    capabilities: tuple[Capability, ...] = Field(
        description='Approved semantic capabilities available to the runtime.',
        min_length=1,
    )
    providers: tuple[McpProviderConfiguration, ...] = Field(
        description='Validated provider instances available to the resolver.',
        min_length=1,
    )
    allow_mutating_capabilities: bool = Field(
        default=False,
        description='Whether mutating provider tools may be resolved.',
    )
    discovery_configuration: CapabilityDiscoveryConfiguration = Field(
        default_factory=CapabilityDiscoveryConfiguration,
        description='Trusted limits for model-visible goal candidates.',
    )

    @model_validator(mode='after')
    def validate_catalogue_references(self) -> Self:
        """Validate unique identities and concrete provider references.

        Returns:
            The validated capability catalogue and resolver.

        Raises:
            ValueError: If identities repeat, a capability references an
                unknown provider or tool, or a shared protected argument is
                also populated by the capability binding.
        """
        capability_names = [
            capability.name
            for capability in self.capabilities
        ]
        if len(capability_names) != len(set(capability_names)):
            raise ValueError('Capability names must be unique.')

        provider_names = [provider.provider_name for provider in self.providers]
        if len(provider_names) != len(set(provider_names)):
            raise ValueError('Capability provider names must be unique.')

        for capability in self.capabilities:
            for binding in capability.provider_bindings:
                matching_providers = self._providers_for_binding(binding)
                if not matching_providers:
                    raise ValueError(
                        'Capability bindings must reference a declared '
                        'provider type with the allowlisted tool.'
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

                target_ids = {
                    target_id
                    for provider in matching_providers
                    for target_id in self._provider_target_ids(provider)
                }
                for target_id in (None, *sorted(target_ids)):
                    if sum(
                        provider.supports_target(target_id)
                        for provider in matching_providers
                    ) > 1:
                        raise ValueError(
                            'Provider type, tool, and target routing must '
                            'resolve to at most one provider instance.'
                        )

        return self

    def target_verticals_for_capabilities(
        self,
        capability_names: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Return trusted verticals used by target-aware capabilities.

        A capability contributes target scope only when none of its allowed
        provider bindings is target independent. Unknown capabilities remain
        the responsibility of normal availability handling.

        Args:
            capability_names: Capability names declared by loaded skills.

        Returns:
            Unique target verticals in deterministic catalogue order.
        """
        capabilities_by_name = {
            capability.name: capability for capability in self.capabilities
        }
        verticals: list[str] = []
        for capability_name in dict.fromkeys(capability_names):
            capability = capabilities_by_name.get(capability_name)
            if capability is None:
                continue
            allowed_bindings = self._allowed_provider_bindings(capability)
            provider_routings = tuple(
                provider.routing
                for binding in allowed_bindings
                for provider in self._providers_for_binding(binding)
            )
            if any(
                routing.mode == 'target_independent'
                for routing in provider_routings
            ):
                continue
            for routing in provider_routings:
                target_ids = (
                    (routing.target_id,)
                    if routing.mode == 'endpoint_per_target'
                    else tuple(
                        target_binding.target_id
                        for target_binding in routing.target_bindings
                    )
                )
                for target_id in target_ids:
                    if target_id is None:
                        continue
                    vertical = target_id.split('/', maxsplit=1)[0]
                    if vertical not in verticals:
                        verticals.append(vertical)
        return tuple(verticals)

    def discover_capability_candidates(
        self,
        required_capability_names: tuple[str, ...],
        optional_capability_names: tuple[str, ...],
        target_id: str | None = None,
    ) -> dict[str, object]:
        """Expose capabilities declared by the loaded skill batch.

        Required and optional capabilities are selected only by exact trusted
        names from loaded skill definitions. Provider details and fixed
        arguments never leave this resolver.

        Args:
            required_capability_names: Exact requirements from loaded skills.
            optional_capability_names: Exact optional capabilities from loaded
                skills.
            target_id: Trusted canonical session target, when required.

        Returns:
            Bounded model-visible candidate metadata or a fail-closed status.
        """
        capabilities_by_name = {
            capability.name: capability
            for capability in self.capabilities
        }
        required_names = tuple(dict.fromkeys(required_capability_names))
        required_name_set = set(required_names)
        optional_names = tuple(
            name
            for name in dict.fromkeys(optional_capability_names)
            if name not in required_name_set
        )
        unavailable_required_names = tuple(
            name
            for name in required_names
            if name not in capabilities_by_name
            or self._select_provider_binding(
                capabilities_by_name[name],
                target_id,
            ) is None
        )
        if unavailable_required_names:
            return {
                'status': 'required_capabilities_unavailable',
                'capabilities': [],
                'unavailable_required_capability_names': list(
                    unavailable_required_names
                ),
            }

        unavailable_optional_names = tuple(
            name
            for name in optional_names
            if name not in capabilities_by_name
            or self._select_provider_binding(
                capabilities_by_name[name],
                target_id,
            ) is None
        )
        unavailable_optional_name_set = set(unavailable_optional_names)
        ordered_names = [
            *required_names,
            *(
                name
                for name in optional_names
                if name not in unavailable_optional_name_set
            ),
        ]
        if (
            len(ordered_names)
            > self.discovery_configuration.maximum_candidate_count
        ):
            return {
                'status': 'limit_exceeded',
                'capabilities': [],
                'limit_name': 'maximum_candidate_count',
            }

        entries = [
            self._model_visible_capability_metadata(
                capabilities_by_name[capability_name],
                target_id,
            )
            for capability_name in ordered_names
        ]
        metadata_characters = len(
            json.dumps(
                entries,
                ensure_ascii=False,
                separators=(',', ':'),
            )
        )
        if (
            metadata_characters
            > self.discovery_configuration.maximum_metadata_characters
        ):
            return {
                'status': 'limit_exceeded',
                'capabilities': [],
                'limit_name': 'maximum_metadata_characters',
            }
        result: dict[str, object] = {
            'status': 'available' if entries else 'none_available',
            'capabilities': entries,
        }
        if unavailable_optional_names:
            result['unavailable_optional_capability_names'] = list(
                unavailable_optional_names
            )
        return result

    def resolve_capabilities(
        self,
        capability_names: list[str],
        target_id: str | None = None,
    ) -> dict[str, object]:
        """Resolve semantic capabilities to allowed provider tools.

        Use this tool once after loading the complete relevant skill set.
        Resolve every required capability and any optional capabilities that
        materially improve the user's outcome. Do not call a concrete provider
        tool unless this method returns that tool for its capability.

        Args:
            capability_names: Semantic capability names selected from loaded
                skill requirements or the available capability catalogue.
                Duplicate names are resolved only once.
            target_id: Trusted canonical session target, when required.

        Returns:
            A serialized capability-resolution result. Its status is
            ``resolved``, ``partially_resolved``, or ``unavailable``. Each
            resolution identifies the approved provider and concrete tool;
            unresolved names are returned without raising an exception.
        """
        requested_names = list(
            dict.fromkeys(
                capability_name.strip().lower()
                for capability_name in capability_names
            )
        )
        capabilities_by_name = {
            capability.name: capability
            for capability in self.capabilities
        }
        resolved_capabilities: list[ResolvedCapability] = []
        unavailable_capability_names: list[str] = []

        for capability_name in requested_names:
            capability = capabilities_by_name.get(capability_name)
            if capability is None:
                unavailable_capability_names.append(capability_name)
                continue

            provider_selection = self._select_provider_binding(
                capability,
                target_id,
            )
            if provider_selection is None:
                unavailable_capability_names.append(capability_name)
                continue
            provider_binding, provider = provider_selection

            resolved_capabilities.append(
                ResolvedCapability(
                    capability_name=capability.name,
                    provider_name=provider.provider_name,
                    tool_name=provider_binding.tool_name,
                    read_only=provider_binding.read_only,
                    required_semantic_argument_names=(
                        self._semantic_argument_names(
                            provider_binding,
                            required=True,
                        )
                    ),
                    optional_semantic_argument_names=(
                        self._semantic_argument_names(
                            provider_binding,
                            required=False,
                        )
                    ),
                )
            )

        if resolved_capabilities and unavailable_capability_names:
            status = 'partially_resolved'
        elif resolved_capabilities:
            status = 'resolved'
        else:
            status = 'unavailable'

        result = CapabilityResolutionResult(
            status=status,
            resolved_capabilities=tuple(resolved_capabilities),
            unavailable_capability_names=tuple(
                unavailable_capability_names
            ),
        )
        return result.model_dump(mode='json')

    def prepare_capability_invocation(
        self,
        capability_name: str,
        semantic_arguments: dict[str, JsonValue],
        target_id: str | None = None,
    ) -> dict[str, object]:
        """Prepare approved arguments for one resolved capability call.

        Fixed arguments come only from catalogue metadata and cannot be
        overridden by the caller. Semantic arguments are mapped, validated,
        and optionally composed into a provider-specific template. Unmapped
        caller inputs are reported and never forwarded to the provider.

        Args:
            capability_name: Semantic capability to prepare for invocation.
            semantic_arguments: Goal or evidence values keyed by the semantic
                input names declared by the selected provider binding.
            target_id: Trusted canonical session target, when required.

        Returns:
            A serialized prepared invocation. A ``ready`` result identifies
            the provider tool and exact arguments to pass. Other statuses
            report unavailable capabilities or missing or invalid inputs.
        """
        normalized_name = capability_name.strip().lower()
        capability = next(
            (
                item
                for item in self.capabilities
                if item.name == normalized_name
            ),
            None,
        )
        provider_selection = (
            self._select_provider_binding(capability, target_id)
            if capability is not None
            else None
        )
        if provider_selection is None:
            return PreparedCapabilityInvocation(
                status='unavailable',
                capability_name=normalized_name,
            ).model_dump(mode='json')
        provider_binding, provider = provider_selection

        expected_names = {
            name
            for binding in provider_binding.argument_bindings
            for name in binding.semantic_argument_names
        }
        ignored_names = tuple(
            sorted(set(semantic_arguments) - expected_names)
        )
        missing_names: set[str] = set()
        invalid_names: set[str] = set()
        tool_arguments: dict[str, JsonValue] = {}

        for binding in provider_binding.argument_bindings:
            if binding.source == 'fixed':
                tool_arguments[binding.tool_argument_name] = (
                    binding.fixed_value
                )
                continue

            absent_names = set(binding.semantic_argument_names) - set(
                semantic_arguments
            )
            if absent_names:
                if binding.required:
                    missing_names.update(absent_names)
                continue

            binding_invalid_names = {
                name
                for name, pattern in binding.semantic_argument_patterns.items()
                if not isinstance(semantic_arguments[name], str)
                or re.fullmatch(pattern, semantic_arguments[name]) is None
            }
            if binding_invalid_names:
                invalid_names.update(binding_invalid_names)
                continue

            if binding.source == 'semantic':
                semantic_name = binding.semantic_argument_names[0]
                tool_arguments[binding.tool_argument_name] = (
                    semantic_arguments[semantic_name]
                )
            else:
                template_values = {
                    name: semantic_arguments[name]
                    for name in binding.semantic_argument_names
                }
                value_template = binding.value_template
                if value_template is None:
                    raise RuntimeError(
                        'Validated template binding has no value template.'
                    )
                tool_arguments[binding.tool_argument_name] = (
                    value_template.format_map(template_values)
                )

        if provider.routing.mode == 'shared_endpoint':
            target_binding = next(
                (
                    item
                    for item in provider.routing.target_bindings
                    if item.target_id == target_id
                ),
                None,
            )
            target_argument_name = provider.routing.target_argument_name
            if target_binding is None or target_argument_name is None:
                raise RuntimeError(
                    'Selected shared provider has no target binding.'
                )
            if target_argument_name in tool_arguments:
                raise RuntimeError(
                    'Protected target arguments cannot be overridden.'
                )
            tool_arguments[target_argument_name] = target_binding.argument_value

        if invalid_names:
            status = 'invalid_arguments'
        elif missing_names:
            status = 'missing_arguments'
        else:
            status = 'ready'

        result = PreparedCapabilityInvocation(
            status=status,
            capability_name=normalized_name,
            provider_name=provider.provider_name,
            tool_name=provider_binding.tool_name,
            tool_arguments=tool_arguments,
            result_binding=provider_binding.result_binding,
            missing_semantic_argument_names=tuple(sorted(missing_names)),
            invalid_semantic_argument_names=tuple(sorted(invalid_names)),
            ignored_semantic_argument_names=ignored_names,
        )
        return result.model_dump(mode='json')

    def _select_provider_binding(
        self,
        capability: Capability,
        target_id: str | None,
    ) -> tuple[CapabilityProviderBinding, McpProviderConfiguration] | None:
        """Select the highest-priority allowed provider for a capability.

        Args:
            capability: Semantic capability requiring a concrete provider.
            target_id: Trusted canonical session target, when required.

        Returns:
            The allowed binding and resolved concrete provider with the lowest
            priority value, or ``None`` when no pair satisfies runtime policy.
        """
        selections: list[
            tuple[CapabilityProviderBinding, McpProviderConfiguration]
        ] = []
        for binding in self._allowed_provider_bindings(capability):
            compatible_providers = tuple(
                provider
                for provider in self._providers_for_binding(binding)
                if provider.supports_target(target_id)
            )
            if len(compatible_providers) > 1:
                raise RuntimeError(
                    'Validated provider routing resolved ambiguously.'
                )
            if compatible_providers:
                selections.append((binding, compatible_providers[0]))
        if not selections:
            return None

        return min(
            selections,
            key=lambda selection: (
                selection[0].priority,
                selection[1].provider_name,
                selection[0].tool_name,
            ),
        )

    def _model_visible_capability_metadata(
        self,
        capability: Capability,
        target_id: str | None,
    ) -> dict[str, object]:
        """Build provider-free semantic metadata for one capability.

        Args:
            capability: Authorised runtime capability to expose.
            target_id: Trusted canonical session target, when required.

        Returns:
            Semantic name, description, availability, and input contract.
        """
        provider_selection = self._select_provider_binding(
            capability,
            target_id,
        )
        if provider_selection is None:
            return {
                'name': capability.name,
                'description': capability.description,
                'available': False,
                'required_semantic_argument_names': [],
                'optional_semantic_argument_names': [],
            }
        provider_binding, _ = provider_selection
        return {
            'name': capability.name,
            'description': capability.description,
            'available': True,
            'required_semantic_argument_names': list(
                self._semantic_argument_names(
                    provider_binding,
                    required=True,
                )
            ),
            'optional_semantic_argument_names': list(
                self._semantic_argument_names(
                    provider_binding,
                    required=False,
                )
            ),
        }

    def _allowed_provider_bindings(
        self,
        capability: Capability,
    ) -> tuple[CapabilityProviderBinding, ...]:
        """Return bindings allowed by the runtime mutation policy.

        Args:
            capability: Semantic capability being evaluated.

        Returns:
            Provider bindings permitted by the current runtime policy.
        """
        return tuple(
            binding
            for binding in capability.provider_bindings
            if binding.read_only or self.allow_mutating_capabilities
        )

    def _providers_for_binding(
        self,
        binding: CapabilityProviderBinding,
    ) -> tuple[McpProviderConfiguration, ...]:
        """Return providers implementing a binding's type and tool.

        Args:
            binding: Concrete capability-to-provider binding.

        Returns:
            Declared provider configurations in snapshot order.
        """
        return tuple(
            provider
            for provider in self.providers
            if provider.provider_type == binding.provider_type
            and binding.tool_name in provider.allowed_tool_names
        )

    def _provider_target_ids(
        self,
        provider: McpProviderConfiguration,
    ) -> tuple[str, ...]:
        """Return canonical targets explicitly served by a provider.

        Args:
            provider: Provider instance being considered.

        Returns:
            Configured target identities, or an empty tuple for a
            target-independent provider.
        """
        routing = provider.routing
        if routing.mode == 'target_independent':
            return ()
        if routing.mode == 'endpoint_per_target':
            if routing.target_id is None:
                raise RuntimeError(
                    'Validated endpoint routing omitted its target.'
                )
            return (routing.target_id,)
        return tuple(
            binding.target_id for binding in routing.target_bindings
        )

    def _semantic_argument_names(
        self,
        provider_binding: CapabilityProviderBinding,
        required: bool,
    ) -> tuple[str, ...]:
        """Return unique semantic input names for one requirement level.

        Args:
            provider_binding: Selected concrete provider binding.
            required: Requirement level to include.

        Returns:
            Semantic input names in their catalogue declaration order.
        """
        return tuple(
            dict.fromkeys(
                name
                for binding in provider_binding.argument_bindings
                if binding.source != 'fixed'
                and binding.required is required
                for name in binding.semantic_argument_names
            )
        )
