from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ConversationJobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_id: UUID
    status: Literal['queued', 'running', 'stopping', 'awaiting_clarification', 'succeeded', 'failed', 'cancelled']
