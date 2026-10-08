from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class PilotUserCredential(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    user_id: str = Field(
        description='Immutable identifier of the provisioned pilot user.',
        min_length=1,
        max_length=255,
    )
    token_id: str = Field(
        description='Application-generated UUID of the stored token record.',
        min_length=36,
        max_length=36,
    )
    plaintext_token: SecretStr = Field(
        description='One-time plaintext token returned only at provisioning.',
    )
    workspace_id: str = Field(
        description='Application-generated UUID of the empty user workspace.',
        min_length=36,
        max_length=36,
    )
    created_at: datetime = Field(
        description='Time at which the pilot user was provisioned.',
    )
