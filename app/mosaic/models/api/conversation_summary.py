from typing import Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ConversationSummary(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    conversation_id: UUID = Field(
        description='Opaque server-generated conversation identifier.'
    )
    title: str | None = Field(
        description='Truncated first user prompt, or null before the first message.',
    )
    created_at: AwareDatetime = Field(
        description='Conversation creation time with timezone.'
    )
    last_activity_at: AwareDatetime = Field(
        description='Most recent persisted activity time.'
    )
    can_continue: bool = Field(
        default=True,
        description='Whether another message may be submitted; false while reserved or interrupted.',
    )
    is_interrupted: bool = Field(
        default=False,
        description='Confirmed stopped or failed execution; display Interrupted — cannot continue and retain read-only history.',
    )

    @model_validator(mode='after')
    def validate_availability(self) -> Self:
        """
        Prevent interrupted conversations from advertising continuation permission.

        :return: Consistent immutable public availability flags.

        :raises ValueError: If an interrupted conversation permits continuation.
        """
        if self.is_interrupted and self.can_continue:
            raise ValueError('Interrupted conversations cannot continue.')
        return self
