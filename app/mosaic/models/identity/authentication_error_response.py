from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuthenticationErrorResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    detail: Literal['Unauthorized', 'Forbidden'] = Field(
        description='Generic failure description without credential details.',
    )
    error_code: Literal['unauthorized', 'forbidden'] = Field(
        description='Stable authentication failure code for API consumers.',
    )
    action: str = Field(
        min_length=1,
        description='Safe next action for the caller.',
    )
    correlation_id: UUID = Field(
        description='Server-generated identifier shared with the failure log.',
    )
