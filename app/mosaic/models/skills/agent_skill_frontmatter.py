"""Standard Agent Skills frontmatter contract for ``SKILL.md``."""

from pydantic import BaseModel, ConfigDict, Field


class AgentSkillFrontmatter(BaseModel):
    """Represent the standard YAML frontmatter of one Agent Skill."""

    model_config = ConfigDict(
        extra='forbid',
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    name: str = Field(
        description='Skill identifier matching its parent directory.',
        min_length=1,
        max_length=64,
        pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$',
    )
    description: str = Field(
        description='What the skill does and when an agent should use it.',
        min_length=1,
        max_length=1024,
    )
    license: str | None = Field(
        default=None,
        description='Optional license name or bundled license-file reference.',
        min_length=1,
    )
    compatibility: str | None = Field(
        default=None,
        description='Optional environment and product requirements.',
        min_length=1,
        max_length=500,
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description='Optional implementation-specific string metadata.',
    )
    allowed_tools: str | None = Field(
        default=None,
        alias='allowed-tools',
        description='Experimental standard pre-approved tool declaration.',
        min_length=1,
    )
