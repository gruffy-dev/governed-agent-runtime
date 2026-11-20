from uuid import UUID

from .conversation_job_summary import ConversationJobSummary


class ConversationJobDetail(ConversationJobSummary):
    conversation_id: UUID
    result_text: str | None
