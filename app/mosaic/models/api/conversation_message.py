from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class ConversationMessage(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    message_id: str = Field(
        min_length=1, description='Opaque persisted message identifier.'
    )
    role: Literal['user', 'assistant'] = Field(
        description='Public conversation participant.'
    )
    text: str = Field(
        description='Displayable text without internal tool or provider payloads.'
    )
    created_at: AwareDatetime = Field(
        description='Persisted message time with timezone.'
    )
