"""Skill discovery and progressive-loading support for MOSAIC."""

import json
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...interfaces.orchestration.callback_context_protocol import (
    CallbackContextProtocol,
)
from ...models.skills.skill import Skill
from .session_skill_profile_manager import SessionSkillProfileManager


class SkillDiscoveryAndLoader(BaseModel):
    """Expose compact skill metadata and load approved skill instructions."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    skills: tuple[Skill, ...] = Field(
        description='Approved skills available for discovery and loading.',
        min_length=1,
    )
    profile_manager: SessionSkillProfileManager = Field(
        description='Trusted session skill-profile state manager.',
    )

    @model_validator(mode='after')
    def validate_unique_skill_names(self) -> Self:
        """Validate that each configured skill has a unique name.

        Returns:
            The validated loader instance.

        Raises:
            ValueError: If two or more configured skills have the same name.
        """
        skill_names = [skill.name for skill in self.skills]
        if len(skill_names) != len(set(skill_names)):
            raise ValueError('Skill names must be unique.')

        return self

    def discover_skills(
        self,
        tool_context: CallbackContextProtocol,
    ) -> dict[str, object]:
        """Discover compact metadata authorised for the current ADA session.

        Use this tool once when a goal may benefit from specialised procedural
        or output guidance. The returned catalogue is already restricted by
        trusted deployment configuration. Skill instructions and output
        contracts remain hidden until selected through ``load_skills``.

        Args:
            tool_context: ADA-injected context excluded from the model schema.

        Returns:
            Profile identity, immutable catalogue commit, and compact metadata
            for every skill authorised in the current session.
        """
        profile = self.profile_manager.ensure_profile(tool_context)
        allowed_skill_names = set(profile.allowed_skill_names)
        skill_entries = [
            {
                'name': skill.name,
                'kind': skill.kind,
                'version': skill.version,
                'description': skill.description,
            }
            for skill in self.skills
            if skill.name in allowed_skill_names
        ]
        return {
            'status': 'available' if skill_entries else 'none_available',
            'profile_id': profile.profile_id,
            'catalogue_commit_sha': profile.catalogue_commit_sha,
            'skills': skill_entries,
        }

    def load_skills(
        self,
        skill_names: list[str],
        tool_context: CallbackContextProtocol,
    ) -> dict[str, object]:
        """Load a complete set of approved skills by their exact names.

        Use this tool after decomposing the user's goal and identifying every
        relevant skill returned by ``discover_skills``. Each loaded skill
        returns its instruction and optional output form. Requested names that
        are absent or unauthorised share the same non-revealing not-found
        result.

        Args:
            skill_names: Exact skill names selected from the available skill
                catalogue. Duplicate names are loaded only once.
            tool_context: ADA-injected context excluded from the model schema.

        Returns:
            A dictionary containing the overall status, every successfully
            loaded serialized skill, and any names that were not found. The
            status is ``loaded``, ``not_found``, or ``limit_exceeded``.
            A failed batch never returns partial full-skill content. Unknown
            and unauthorised names share the same non-revealing outcome.
        """
        profile = self.profile_manager.ensure_profile(tool_context)
        requested_names = list(
            dict.fromkeys(
                skill_name.strip().lower()
                for skill_name in skill_names
            )
        )
        configuration = self.profile_manager.resolver.configuration
        if len(requested_names) > configuration.maximum_loaded_skill_count:
            return self._load_limit_exceeded_result(
                profile_id=profile.profile_id,
                catalogue_commit_sha=profile.catalogue_commit_sha,
                limit_name='maximum_loaded_skill_count',
            )
        allowed_skill_names = set(profile.allowed_skill_names)
        skills_by_name = {
            skill.name: skill
            for skill in self.skills
            if skill.name in allowed_skill_names
        }
        candidate_loaded_skills = [
            skills_by_name[skill_name].model_dump(
                mode='json',
                exclude_none=True,
            )
            for skill_name in requested_names
            if skill_name in skills_by_name
        ]
        not_found_skill_names = [
            skill_name
            for skill_name in requested_names
            if skill_name not in skills_by_name
        ]
        if not_found_skill_names or not candidate_loaded_skills:
            return {
                'status': 'not_found',
                'profile_id': profile.profile_id,
                'catalogue_commit_sha': profile.catalogue_commit_sha,
                'loaded_skills': [],
                'not_found_skill_names': not_found_skill_names,
            }

        serialized_characters = len(
            json.dumps(
                candidate_loaded_skills,
                ensure_ascii=False,
                separators=(',', ':'),
            )
        )
        if (
            serialized_characters
            > configuration.maximum_loaded_skill_characters
        ):
            return self._load_limit_exceeded_result(
                profile_id=profile.profile_id,
                catalogue_commit_sha=profile.catalogue_commit_sha,
                limit_name='maximum_loaded_skill_characters',
            )

        return {
            'status': 'loaded',
            'profile_id': profile.profile_id,
            'catalogue_commit_sha': profile.catalogue_commit_sha,
            'loaded_skills': candidate_loaded_skills,
            'not_found_skill_names': [],
        }

    def _load_limit_exceeded_result(
        self,
        profile_id: str,
        catalogue_commit_sha: str,
        limit_name: str,
    ) -> dict[str, object]:
        """Build a fail-closed result for an oversized complete skill batch.

        Args:
            profile_id: Trusted profile handling the request.
            catalogue_commit_sha: Immutable catalogue commit for the profile.
            limit_name: Trusted limit exceeded by the requested batch.

        Returns:
            Non-partial result containing no full skill content.
        """
        return {
            'status': 'limit_exceeded',
            'profile_id': profile_id,
            'catalogue_commit_sha': catalogue_commit_sha,
            'loaded_skills': [],
            'not_found_skill_names': [],
            'limit_name': limit_name,
        }
