from pydantic import Field

from .conversation_message import ConversationMessage
from .conversation_summary import ConversationSummary


class ConversationDetail(ConversationSummary):
    messages: tuple[ConversationMessage, ...] = Field(
        description='Complete public message history ordered from oldest to newest.',
    )
