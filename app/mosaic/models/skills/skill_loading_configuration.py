from pydantic import BaseModel, ConfigDict, Field

from ...utilities.environment_configuration_reader import EnvironmentConfigurationReader


class SkillLoadingConfiguration(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, validate_default=True)

    maximum_enabled_skill_count: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_SKILLS_MAXIMUM_ENABLED_SKILL_COUNT', 50
        ),
        gt=0,
        le=1000,
        description='Maximum authorised Skills in one Goal snapshot.',
    )
    maximum_discovery_metadata_characters: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_SKILLS_MAXIMUM_DISCOVERY_METADATA_CHARACTERS', 20000
        ),
        gt=0,
        le=1000000,
        description='Maximum serialised authorised Skill discovery metadata.',
    )
    maximum_loaded_skill_count: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_SKILLS_MAXIMUM_LOADED_SKILL_COUNT', 10
        ),
        gt=0,
        le=100,
        description='Maximum complete Skills loaded in one Goal.',
    )
    maximum_loaded_skill_characters: int = Field(
        default_factory=lambda: EnvironmentConfigurationReader.read_positive_integer(
            'MOSAIC_SKILLS_MAXIMUM_LOADED_SKILL_CHARACTERS', 50000
        ),
        gt=0,
        le=2000000,
        description='Maximum serialised full Skill content loaded in one Goal.',
    )
