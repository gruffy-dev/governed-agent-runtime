from typing import Literal
from uuid import UUID

from pydantic import Field

from .api_error_response import ApiErrorResponse


class ConversationConflictResponse(ApiErrorResponse):
    error_code: Literal['conversation_busy'] = Field(
        description='An invocation already holds this conversation guard.',
    )
    conversation_id: UUID = Field(
        description='Owned conversation with an active invocation; the request was not queued.',
    )
