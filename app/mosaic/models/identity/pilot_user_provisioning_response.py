from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PilotUserProvisioningResponse(BaseModel):
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
    plaintext_token: str = Field(
        description='One-time plaintext token shown only in this response.',
        min_length=53,
        pattern=r'^mosaic_r1_[A-Za-z0-9_-]+$',
    )
    workspace_id: str = Field(
        description='Application-generated UUID of the empty user workspace.',
        min_length=36,
        max_length=36,
    )
    created_at: datetime = Field(
        description='Time at which the pilot user was provisioned.',
    )
