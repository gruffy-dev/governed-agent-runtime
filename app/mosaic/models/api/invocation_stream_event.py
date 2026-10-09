from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .api_error_response import ApiErrorResponse


class InvocationStreamEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    event: Literal['started', 'text_delta', 'completed', 'failed', 'cancelled'] = Field(
        description='SSE event name; completed, failed and cancelled are terminal.',
    )
    conversation_id: UUID = Field(description='Owned conversation receiving the event.')
    invocation_id: UUID = Field(description='Server-generated invocation identifier.')
    correlation_id: UUID = Field(
        description='Server-generated correlation shared by this stream.'
    )
    text: str | None = Field(
        default=None, description='Incremental text for text_delta only.'
    )
    error: ApiErrorResponse | None = Field(
        default=None, description='Safe failure envelope for failed only.'
    )

    @model_validator(mode='after')
    def validate_event_payload(self) -> Self:
        """
        Keep text and safe error payloads consistent with their SSE event.

        :return: Validated public streaming event.

        :raises ValueError: If an event carries an invalid or missing payload.
        """
        if self.event == 'text_delta':
            if self.text is None or not self.text:
                raise ValueError('text_delta requires non-empty text.')
        elif self.text is not None:
            raise ValueError('Only text_delta may contain text.')
        if (self.event == 'failed') != (self.error is not None):
            raise ValueError('Only failed events must contain an error.')
        if self.error is not None and self.error.correlation_id != self.correlation_id:
            raise ValueError('Stream and error correlation identifiers must match.')
        return self
