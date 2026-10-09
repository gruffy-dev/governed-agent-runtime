from pydantic import BaseModel, ConfigDict, Field


class TrustedRequestContext(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    app_name: str = Field(
        min_length=1,
        max_length=255,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9._-]*$',
        description='Application name derived only from server configuration.',
    )
    user_id: str = Field(
        min_length=1,
        max_length=255,
        description=(
            'User identifier derived only from middleware-validated identity; '
            'also the lookup key for the user-owned workspace.'
        ),
    )
