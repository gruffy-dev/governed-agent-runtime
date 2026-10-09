from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


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
