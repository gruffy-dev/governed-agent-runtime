import os
import ssl
from pathlib import Path
from typing import Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    model_validator,
)


class GitSkillCatalogueConfiguration(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        str_strip_whitespace=True,
        validate_default=True,
    )

    repository_url: str = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_SKILLS_REPOSITORY_URL',
            '',
        ),
        description='Remote Git repository containing the skill catalogue.',
        min_length=1,
    )
    revision: str = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_SKILLS_REPOSITORY_REVISION',
            'main',
        ),
        description='Branch, tag, or commit selected from the repository.',
        min_length=1,
        max_length=255,
        pattern=r'^[A-Za-z0-9][A-Za-z0-9._/-]*$',
    )
    repository_cache_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv(
                'MOSAIC_SKILLS_REPOSITORY_CACHE_PATH',
                '/tmp/mosaic/skill-repository.git',
            )
        ),
        description='Absolute path of the deployment-local bare Git cache.',
    )
    access_token: SecretStr = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_SKILLS_REPOSITORY_ACCESS_TOKEN',
            '',
        ),
        description='Required Bearer token for the private skill repository.',
        min_length=1,
        repr=False,
        exclude=True,
    )
    synchronisation_timeout_seconds: float = Field(
        default_factory=lambda: os.getenv(
            'MOSAIC_SKILLS_SYNCHRONIZATION_TIMEOUT_SECONDS',
            '60',
        ),
        description='Maximum duration of each Git operation in seconds.',
        gt=0,
        le=300,
    )
    ca_bundle_path: Path | None = Field(
        default_factory=lambda: os.getenv('SSL_CERT_FILE'),
        description='Optional shared PEM CA bundle supplied through SSL_CERT_FILE.',
    )

    @model_validator(mode='after')
    def validate_ca_bundle(self) -> Self:
        """
        Reject an explicitly configured CA bundle that cannot establish trust.

        :return: Configuration with a usable bundle or standard CA defaults.

        :raises ValueError: If SSL_CERT_FILE cannot be loaded as a PEM CA bundle.
        """
        if self.ca_bundle_path is not None:
            try:
                context = ssl.create_default_context(
                    cafile=str(self.ca_bundle_path.expanduser().resolve())
                )
                if not context.get_ca_certs():
                    raise ValueError('The bundle contains no CA certificates.')
            except (OSError, ValueError) as error:
                raise ValueError(
                    'SSL_CERT_FILE must reference a readable PEM CA bundle.'
                ) from error
        return self

    @model_validator(mode='after')
    def validate_secure_configuration(self) -> Self:
        """
        Reject unsafe paths, embedded credentials and unencrypted Git HTTP URLs.

        :return: The validated configuration.

        :raises ValueError: If the URL, cache path or credential configuration
            is unsafe or incomplete.
        """
        if '\n' in self.repository_url or '\r' in self.repository_url:
            raise ValueError('repository_url must not contain newlines.')

        parsed_url = urlsplit(self.repository_url)
        if parsed_url.scheme.lower() == 'http':
            raise ValueError('Remote HTTP Git repositories must use HTTPS.')
        if parsed_url.username is not None or parsed_url.password is not None:
            raise ValueError('repository_url must not contain embedded credentials.')

        access_token = self.access_token.get_secret_value()
        if '\n' in access_token or '\r' in access_token:
            raise ValueError('access_token must not contain newlines.')

        cache_path = self.repository_cache_path.expanduser()
        if not cache_path.is_absolute():
            raise ValueError('repository_cache_path must be absolute.')
        if cache_path in {Path('/'), Path.home()}:
            raise ValueError('repository_cache_path is too broad.')

        return self
