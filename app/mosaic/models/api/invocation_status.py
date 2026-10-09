from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InvocationStatus(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    conversation_id: UUID = Field(
        description='Owned conversation containing this invocation.'
    )
    invocation_id: UUID | None = Field(
        description='Server-generated invocation ID, or null when idle.'
    )
    status: Literal[
        'idle', 'working', 'completed', 'failed', 'cancelled', 'interrupted'
    ] = Field(
        description=(
            'Current or most recent invocation state. Completed includes a '
            'response asking for clarification; the next message may continue its Goal.'
        ),
    )

    @model_validator(mode='after')
    def validate_invocation_identity(self) -> Self:
        """
        Require an invocation identifier for every non-idle state.

        :return: Consistent immutable invocation status.

        :raises ValueError: If idle has an ID or a non-idle state lacks one.
        """
        if (self.status == 'idle') != (self.invocation_id is None):
            raise ValueError('Only idle status may have no invocation ID.')
        return self
