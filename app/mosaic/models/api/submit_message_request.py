from pydantic import BaseModel, ConfigDict, Field, field_validator


class SubmitMessageRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    text: str = Field(
        min_length=1,
        description='User message; application, ownership and Skill state are server-owned.',
    )

    @field_validator('text')
    @classmethod
    def validate_text(cls, value: str) -> str:
        """
        Reject blank messages while preserving meaningful whitespace.

        :param value: User-submitted message text.

        :return: Original non-blank message text.

        :raises ValueError: If the message contains only whitespace.
        """
        if not value.strip():
            raise ValueError('Message text must not be blank.')
        return value
