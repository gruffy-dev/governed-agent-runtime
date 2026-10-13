import os
from pathlib import Path
from typing import Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, model_validator


class GuiConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, validate_default=True)

    backend_url: str = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_GUI_BACKEND_URL', 'http://127.0.0.1:8000'
        ),
        description='Public backend origin; browser calls go there directly.',
    )
    host: str = Field(
        default_factory=lambda: os.getenv('MOSAIC_GUI_HOST', '127.0.0.1'),
        min_length=1,
        description='GUI listener address, independent of the backend.',
    )
    port: int = Field(
        default_factory=lambda: os.getenv('MOSAIC_GUI_PORT', '8050'),
        gt=0,
        le=65535,
        description='Standalone GUI listener port.',
    )
    organisation_logo_path: Path | None = Field(
        default_factory=lambda: os.getenv('MOSAIC_GUI_ORGANISATION_LOGO_PATH') or None,
        description='Optional private PNG outside packaged public assets.',
    )
    organisation_logo_width: int = Field(
        default_factory=lambda: os.getenv('MOSAIC_GUI_ORGANISATION_LOGO_WIDTH', '88'),
        ge=24,
        le=320,
        description='Maximum organisation PNG width in CSS pixels.',
    )
    organisation_logo_height: int = Field(
        default_factory=lambda: os.getenv('MOSAIC_GUI_ORGANISATION_LOGO_HEIGHT', '40'),
        ge=16,
        le=120,
        description='Maximum organisation PNG height; preserve aspect ratio.',
    )

    @model_validator(mode='after')
    def validate_configuration(self) -> Self:
        """
        Validate the backend origin and optional operator-supplied PNG.

        :return: Validated standalone GUI configuration.

        :raises ValueError: If an origin contains credentials or a logo is not a PNG.
        :raises OSError: If the configured private logo cannot be read.
        """
        url = AnyHttpUrl(self.backend_url)
        if (
            url.username is not None
            or url.password is not None
            or url.query is not None
            or url.fragment is not None
            or url.path not in (None, '/')
        ):
            raise ValueError(
                'The GUI backend URL must be an origin without credentials.'
            )
        if str(url).removesuffix('/') != self.backend_url:
            raise ValueError(
                'The GUI backend URL must be canonical without a trailing slash.'
            )
        if url.scheme == 'http' and url.host not in {'localhost', '127.0.0.1', '[::1]'}:
            raise ValueError('HTTP is permitted only for a local loopback backend.')
        if self.organisation_logo_path is not None:
            with self.organisation_logo_path.open('rb') as logo:
                if logo.read(8) != b'\x89PNG\r\n\x1a\n':
                    raise ValueError('The organisation logo must be a PNG file.')
        return self
