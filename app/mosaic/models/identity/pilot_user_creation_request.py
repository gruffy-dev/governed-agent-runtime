from pydantic import BaseModel, ConfigDict, Field


class PilotUserCreationRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
    )

    user_id: str = Field(
        description='Immutable identifier for the new pilot user.',
        min_length=1,
        max_length=255,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]*$',
    )
