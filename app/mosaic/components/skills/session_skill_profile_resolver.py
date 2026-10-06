"""Resolver for trusted session-to-skill-profile assignments."""

import json
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...models.skills.session_skill_profile import SessionSkillProfile
from ...models.skills.session_skill_profile_configuration import (
    SessionSkillProfileConfiguration,
)
from ...models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot


class SessionSkillProfileResolver(BaseModel):
    """Resolve trusted session assignments against one catalogue snapshot."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    configuration: SessionSkillProfileConfiguration = Field(
        description='Trusted deployment-owned profile configuration.',
    )
    catalogue_snapshot: SkillCatalogueSnapshot = Field(
        description='Immutable skill snapshot available to all profiles.',
    )

    @model_validator(mode='after')
    def validate_profile_skill_names(self) -> Self:
        """Reject configured profiles that reference absent catalogue skills.

        Returns:
            The validated profile resolver.

        Raises:
            ValueError: If a profile references an unavailable skill or
                exceeds its trusted discovery exposure limits.
        """
        available_skill_names = {
            skill.name
            for skill in self.catalogue_snapshot.skills
        }
        for profile_id, skill_names in self.configuration.profiles.items():
            unavailable_skill_names = sorted(
                set(skill_names) - available_skill_names
            )
            if unavailable_skill_names:
                raise ValueError(
                    f"Profile '{profile_id}' references unavailable skills: "
                    f"{', '.join(unavailable_skill_names)}."
                )
            if (
                len(skill_names)
                > self.configuration.maximum_enabled_skill_count
            ):
                raise ValueError(
                    f"Profile '{profile_id}' exceeds the maximum enabled "
                    'skill count.'
                )
            skill_names_set = set(skill_names)
            discovery_entries = [
                {
                    'name': skill.name,
                    'kind': skill.kind,
                    'version': skill.version,
                    'description': skill.description,
                }
                for skill in self.catalogue_snapshot.skills
                if skill.name in skill_names_set
            ]
            metadata_characters = len(
                json.dumps(
                    discovery_entries,
                    ensure_ascii=False,
                    separators=(',', ':'),
                )
            )
            if (
                metadata_characters
                > self.configuration.maximum_discovery_metadata_characters
            ):
                raise ValueError(
                    f"Profile '{profile_id}' exceeds the maximum discovery "
                    'metadata size.'
                )
        return self

    def resolve(self, session_id: str) -> SessionSkillProfile:
        """Resolve one ADA session to its trusted immutable profile.

        Args:
            session_id: ADA session identifier used only as a configured key.

        Returns:
            Profile bound to the active immutable catalogue commit.

        Raises:
            ValueError: If the supplied session identifier is empty.
        """
        normalized_session_id = session_id.strip()
        if not normalized_session_id:
            raise ValueError('session_id must not be empty.')

        profile_id = self.configuration.session_profile_assignments.get(
            normalized_session_id,
            self.configuration.default_profile_id,
        )
        return SessionSkillProfile(
            profile_id=profile_id,
            allowed_skill_names=self.configuration.profiles[profile_id],
            catalogue_commit_sha=self.catalogue_snapshot.commit_sha,
        )
