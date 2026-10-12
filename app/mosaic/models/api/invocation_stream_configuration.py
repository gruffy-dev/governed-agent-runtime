from pydantic import BaseModel, ConfigDict, Field

from ...utilities.environment_configuration_reader import EnvironmentConfigurationReader


class InvocationStreamConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, validate_default=True)

    maximum_event_bytes: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_INVOCATION_MAXIMUM_EVENT_BYTES',
            1048576,
        ),
        gt=0,
        description='Maximum private SSE frame bytes after normalizing CRLF to LF.',
    )
    maximum_turn_characters: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_INVOCATION_MAXIMUM_TURN_CHARACTERS',
            1048576,
        ),
        gt=0,
        description='Maximum public text retained to reconcile one streamed model turn.',
    )
