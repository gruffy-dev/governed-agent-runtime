import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ...utilities.environment_configuration_reader import EnvironmentConfigurationReader


class AdaApplicationAdapterConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, validate_default=True)

    lifespan_timeout_seconds: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_ADA_LIFESPAN_TIMEOUT_SECONDS', 30
        ),
        gt=0,
        description='Maximum wait for private ADA startup or shutdown acknowledgement.',
    )
    response_queue_capacity: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_ADA_RESPONSE_QUEUE_CAPACITY', 8
        ),
        gt=0,
        description='Maximum buffered ASGI response messages before applying backpressure.',
    )
    maximum_response_bytes: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_ADA_MAXIMUM_RESPONSE_BYTES', 8388608
        ),
        gt=0,
        description='Maximum complete JSON response or individual streamed response chunk size.',
    )
    asgi_spec_version: Literal['2.3', '2.4'] = Field(
        default_factory=lambda: os.getenv('MOSAIC_ADA_ASGI_SPEC_VERSION', '2.3'),
        description='HTTP ASGI protocol supported by the in-process transport.',
    )
