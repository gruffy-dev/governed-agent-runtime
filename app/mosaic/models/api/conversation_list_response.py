from pydantic import BaseModel, ConfigDict, Field

from .conversation_summary import ConversationSummary


class ConversationListResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    conversations: tuple[ConversationSummary, ...] = Field(
        description='Only owned conversations, ordered by most recent activity first.',
    )
