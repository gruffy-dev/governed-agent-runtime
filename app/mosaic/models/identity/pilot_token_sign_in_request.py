from pydantic import BaseModel, ConfigDict, Field, SecretStr


class PilotTokenSignInRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    token: SecretStr = Field(
        min_length=1,
        max_length=4096,
        description='Opaque pilot access token supplied for validation.',
    )
