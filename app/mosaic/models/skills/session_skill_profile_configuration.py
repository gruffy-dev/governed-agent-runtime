"""Trusted environment configuration for session skill profiles."""

import os
import re
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...utilities.environment_configuration_reader import (
    EnvironmentConfigurationReader,
)


class SessionSkillProfileConfiguration(BaseModel):
    """Map trusted session identifiers to deployment-defined skill sets."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    profiles: dict[str, tuple[str, ...]] = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_json_object(
            'MOSAIC_SKILLS_PROFILES',
            '{}',
        ),
        description='Profile identifiers mapped to authorised skill names.',
        min_length=1,
    )
    default_profile_id: str = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_SKILLS_DEFAULT_PROFILE_ID',
            '',
        ),
        description='Profile assigned to sessions without an explicit map.',
        min_length=1,
        pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$',
    )
    session_profile_assignments: dict[str, str] = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_json_object(
            'MOSAIC_SKILLS_SESSION_PROFILE_ASSIGNMENTS',
            '{}',
        ),
        description='Exact ADA session identifiers mapped to profile IDs.',
    )
    maximum_enabled_skill_count: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_SKILLS_MAXIMUM_ENABLED_SKILL_COUNT',
            50,
        ),
        description='Maximum skills authorised by one session profile.',
        gt=0,
        le=1000,
    )
    maximum_discovery_metadata_characters: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_SKILLS_MAXIMUM_DISCOVERY_METADATA_CHARACTERS',
            20000,
        ),
        description='Maximum serialized discovery metadata per profile.',
        gt=0,
        le=1000000,
    )
    maximum_loaded_skill_count: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_SKILLS_MAXIMUM_LOADED_SKILL_COUNT',
            10,
        ),
        description='Maximum complete skills loaded for one goal.',
        gt=0,
        le=100,
    )
    maximum_loaded_skill_characters: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_SKILLS_MAXIMUM_LOADED_SKILL_CHARACTERS',
            50000,
        ),
        description='Maximum serialized full-skill content for one goal.',
        gt=0,
        le=2000000,
    )

    @model_validator(mode='after')
    def validate_profile_configuration(self) -> Self:
        """Validate profile names, skill names, and session assignments.

        Returns:
            The validated trusted profile configuration.

        Raises:
            ValueError: If identifiers are malformed, skills repeat, or an
                assignment references an undefined profile.
        """
        identifier_pattern = r'[a-z0-9]+(?:-[a-z0-9]+)*'
        skill_name_pattern = r'[a-z0-9]+(?:-[a-z0-9]+)*'

        for profile_id, skill_names in self.profiles.items():
            if re.fullmatch(identifier_pattern, profile_id) is None:
                raise ValueError(
                    'Profile identifiers must use lowercase kebab-case.'
                )
            if len(skill_names) != len(set(skill_names)):
                raise ValueError(
                    f"Profile '{profile_id}' contains duplicate skills."
                )
            if any(
                re.fullmatch(skill_name_pattern, skill_name) is None
                for skill_name in skill_names
            ):
                raise ValueError(
                    'Configured skill names must use lowercase kebab-case.'
                )

        if self.default_profile_id not in self.profiles:
            raise ValueError('The default profile must be defined.')

        for session_id, profile_id in self.session_profile_assignments.items():
            if not session_id.strip():
                raise ValueError('Session assignment IDs must not be empty.')
            if profile_id not in self.profiles:
                raise ValueError(
                    f"Session assignment references undefined profile "
                    f"'{profile_id}'."
                )

        return self
