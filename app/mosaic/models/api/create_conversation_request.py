from pydantic import BaseModel, ConfigDict


class CreateConversationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
