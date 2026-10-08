from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PilotUserSummary(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
    )

    user_id: str = Field(
        description='Immutable pilot user identifier.',
        min_length=1,
        max_length=255,
    )
    is_enabled: bool = Field(
        description='Whether the pilot user can currently authenticate.',
    )
    created_at: datetime = Field(
        description='Time at which the pilot user was created.',
    )
    disabled_at: datetime | None = Field(
        description='Time at which the pilot user was disabled.',
    )
