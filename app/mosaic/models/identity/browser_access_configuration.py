import json
import os
from typing import Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class BrowserAccessConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, validate_default=True)

    allowed_origins: tuple[str, ...] = Field(
        default_factory=lambda: json.loads(
            os.getenv('MOSAIC_BROWSER_ALLOWED_ORIGINS', '[]')
        ),
        max_length=10,
        description='Exact trusted GUI origins; empty disables browser-origin access.',
    )

    @model_validator(mode='after')
    def validate_origins(self) -> Self:
        """
        Require unique canonical HTTPS origins, with HTTP only for local loopback.

        Origins contain a scheme, host and optional port, never a path, credentials,
        wildcard, query or fragment. Explicit local ports need no DNS configuration.

        :return: Validated immutable browser access policy.

        :raises ValueError: If an origin is unsafe, non-canonical or duplicated.
        """
        if len(set(self.allowed_origins)) != len(self.allowed_origins):
            raise ValueError('Browser origins must be unique.')
        for origin in self.allowed_origins:
            url = AnyHttpUrl(origin)
            if (
                url.username is not None
                or url.password is not None
                or url.path not in (None, '/')
                or url.query is not None
                or url.fragment is not None
                or '*' in origin
                or str(url).removesuffix('/') != origin
            ):
                raise ValueError('Browser access requires exact canonical origins.')
            if url.scheme == 'http' and url.host not in {
                'localhost',
                '127.0.0.1',
                '[::1]',
            }:
                raise ValueError(
                    'HTTP browser origins are permitted only for loopback.'
                )
        return self
