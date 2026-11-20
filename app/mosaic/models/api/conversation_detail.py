from pydantic import Field

from .conversation_job_summary import ConversationJobSummary
from .conversation_message import ConversationMessage
from .conversation_summary import ConversationSummary


class ConversationDetail(ConversationSummary):
    messages: tuple[ConversationMessage, ...] = Field(
        description='Complete public message history ordered from oldest to newest.',
    )
    latest_job: ConversationJobSummary | None = Field(
        default=None,
        description='Most recently submitted background job, including its current status.',
    )
