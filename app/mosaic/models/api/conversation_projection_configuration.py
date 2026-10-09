import os

from pydantic import BaseModel, ConfigDict, Field

from ...utilities.environment_configuration_reader import EnvironmentConfigurationReader


class ConversationProjectionConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, validate_default=True)

    public_agent_name: str = Field(
        default_factory=lambda: os.getenv('MOSAIC_PUBLIC_AGENT_NAME', 'mosaic'),
        min_length=1,
        description='Exact ADA event author allowed to supply public assistant text.',
    )
    title_maximum_characters: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_CONVERSATION_TITLE_MAXIMUM_CHARACTERS',
            120,
        ),
        gt=0,
        description='Maximum title length derived from the first public user prompt.',
    )
