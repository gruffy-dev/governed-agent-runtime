from pydantic import BaseModel, ConfigDict, Field


class SessionSkillProfile(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    profile_id: str = Field(
        description='Trusted workspace or explicitly configured legacy profile identifier.',
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
    goal_id: str | None = Field(
        default=None,
        min_length=1,
        description='Goal owning a workspace snapshot; absent for legacy profiles.',
    )
    user_id: str | None = Field(
        default=None,
        min_length=1,
        description='Trusted workspace owner; never accepted from message state.',
    )
    app_name: str | None = Field(
        default=None,
        min_length=1,
        description='Trusted application owning the workspace binding.',
    )
    session_id: str | None = Field(
        default=None,
        min_length=1,
        description='Owned conversation retaining this Goal snapshot.',
    )
