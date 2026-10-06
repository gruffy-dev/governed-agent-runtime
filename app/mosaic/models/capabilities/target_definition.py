"""Canonical target identity owned by one platform vertical."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TargetDefinition(BaseModel):
    """Describe one stable deployment identity and its user-facing names."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    id: str = Field(
        description='Globally unique vertical-qualified target identity.',
        min_length=3,
        max_length=255,
        pattern=r'^[a-z][a-z0-9-]*/[a-z][a-z0-9-]*$',
    )
    display_name: str = Field(
        description='Human-readable name used in clarification and results.',
        min_length=1,
        max_length=200,
    )
    aliases: tuple[str, ...] = Field(
        description='Case-insensitively unique names accepted from users.',
        min_length=1,
    )

    @model_validator(mode='after')
    def validate_aliases(self) -> Self:
        """Reject empty, malformed, or duplicated target aliases.

        Returns:
            Validated immutable target definition.

        Raises:
            ValueError: If an alias is empty, oversized, qualified, or
                repeated using different letter casing.
        """
        if any(
            not alias
            or len(alias) > 100
            or '/' in alias
            for alias in self.aliases
        ):
            raise ValueError(
                'Target aliases must be unqualified values of 1-100 '
                'characters.'
            )
        normalized_aliases = [alias.casefold() for alias in self.aliases]
        if len(normalized_aliases) != len(set(normalized_aliases)):
            raise ValueError(
                'Target aliases must be case-insensitively unique.'
            )
        return self

    @property
    def vertical(self) -> str:
        """Return the authoritative vertical namespace from the target ID."""
        return self.id.partition('/')[0]
