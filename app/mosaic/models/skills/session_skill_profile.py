"""Immutable session authorization for one skill-catalogue snapshot."""

from pydantic import BaseModel, ConfigDict, Field


class SessionSkillProfile(BaseModel):
    """Bind one ADA session to an authorised set of immutable skills."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    profile_id: str = Field(
        description='Trusted deployment-defined skill-profile identifier.',
        min_length=1,
        pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$',
    )
    allowed_skill_names: tuple[str, ...] = Field(
        description='Skill names authorised for the bound ADA session.',
    )
    catalogue_commit_sha: str = Field(
        description='Immutable Git commit supplying the authorised skills.',
        pattern=r'^[0-9a-f]{40,64}$',
    )
