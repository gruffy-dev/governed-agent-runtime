from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ConversationJobDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    conversation_id: UUID
    status: Literal['queued', 'running', 'stopping', 'awaiting_clarification', 'succeeded', 'failed', 'cancelled']
    result_text: str | None
