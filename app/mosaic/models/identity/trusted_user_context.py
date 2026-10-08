from pydantic import BaseModel, ConfigDict, Field


class TrustedUserContext(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    user_id: str = Field(
        min_length=1,
        max_length=255,
        description=(
            'MOSAIC-owned user identifier resolved from a validated '
            'credential.'
        ),
    )
