from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiErrorResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    detail: str = Field(min_length=1, description='Safe public error description.')
    error_code: Literal[
        'invalid_request',
        'conversation_not_found',
        'conversation_busy',
        'internal_error',
        'invocation_failed',
    ] = Field(
        description='Stable machine-readable error code.',
    )
    action: str = Field(
        min_length=1, description='Concrete next action for the caller.'
    )
    correlation_id: UUID = Field(
        description='Server-generated identifier shared with the backend log.',
    )
