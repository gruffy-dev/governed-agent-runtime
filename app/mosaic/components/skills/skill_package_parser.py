"""Parser for standard Agent Skills packages with MOSAIC metadata."""

import json
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import ValidationError

from ...models.skills.agent_skill_frontmatter import AgentSkillFrontmatter
from ...models.skills.mosaic_skill_metadata import MosaicSkillMetadata
from ...models.skills.skill import Skill
from ...models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot


class SkillPackageParser:
    """Validate a repository export and construct an immutable snapshot."""

    def parse_catalogue(
        self,
        repository_root: Path,
        commit_sha: str,
    ) -> SkillCatalogueSnapshot:
        """Parse every package below the repository's ``skills`` directory.

        Args:
            repository_root: Root of the exported Git commit.
            commit_sha: Full Git object identifier for the exported commit.

        Returns:
            An immutable snapshot containing every validated skill.

        Raises:
            ValueError: If the repository or any skill package violates the
                catalogue contract.
        """
        skills_root = repository_root / 'skills'
        if not skills_root.is_dir() or skills_root.is_symlink():
            raise ValueError(
                "The repository must contain a 'skills' directory."
            )

        package_directories = self._discover_package_directories(
            skills_root
        )

        skills = tuple(
            self._parse_package(skills_root, package_directory)
            for package_directory in package_directories
        )

        try:
            return SkillCatalogueSnapshot(
                commit_sha=commit_sha,
                loaded_at=datetime.now(timezone.utc),
                skills=skills,
            )
        except ValidationError as error:
            raise ValueError(
                'The catalogue snapshot metadata is invalid.'
            ) from error

    def _discover_package_directories(
        self,
        skills_root: Path,
    ) -> tuple[Path, ...]:
        """Discover packages at the required domain/function/name depth.

        Args:
            skills_root: Validated root of the skill catalogue.

        Returns:
            Deterministically ordered package directories.

        Raises:
            ValueError: If no packages exist, a package is at the wrong
                depth, or MOSAIC metadata is not paired with ``SKILL.md``.
        """
        skill_documents = sorted(
            skills_root.rglob('SKILL.md'),
            key=lambda path: path.relative_to(skills_root).as_posix(),
        )
        if not skill_documents:
            raise ValueError(
                'The catalogue must contain at least one skill package.'
            )

        package_directories: list[Path] = []
        for skill_document in skill_documents:
            package_directory = skill_document.parent
            self._validate_package_hierarchy(
                skills_root,
                package_directory,
            )
            package_directories.append(package_directory)

        package_directory_set = set(package_directories)
        for metadata_path in skills_root.rglob('mosaic.yaml'):
            if metadata_path.parent not in package_directory_set:
                raise ValueError(
                    "Every 'mosaic.yaml' file must be paired with "
                    "'SKILL.md' in the same skill package."
                )

        return tuple(package_directories)

    def _validate_package_hierarchy(
        self,
        skills_root: Path,
        package_directory: Path,
    ) -> None:
        """Validate the catalogue's domain/function/skill-name hierarchy.

        Args:
            skills_root: Validated root of the skill catalogue.
            package_directory: Candidate package directory.

        Raises:
            ValueError: If the package is outside the root, at the wrong
                depth, or uses an invalid hierarchy segment.
        """
        self._validate_contained_path(skills_root, package_directory)
        try:
            relative_path = package_directory.relative_to(skills_root)
        except ValueError as error:
            raise ValueError(
                'A skill package path escapes its allowed directory.'
            ) from error

        if len(relative_path.parts) != 3:
            raise ValueError(
                "Skill packages must use the hierarchy "
                "'skills/<domain>/<function>/<skill-name>'."
            )

        for segment in relative_path.parts:
            if re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', segment) is None:
                raise ValueError(
                    'Skill hierarchy names must use lowercase kebab-case.'
                )

    def _parse_package(
        self,
        skills_root: Path,
        package_directory: Path,
    ) -> Skill:
        """Parse one standard Agent Skill and its MOSAIC extension.

        Args:
            skills_root: Validated root containing all skill packages.
            package_directory: Directory of the package being parsed.

        Returns:
            The immutable runtime skill constructed from the package.

        Raises:
            ValueError: If package content is missing, malformed, unsafe, or
                inconsistent.
        """
        self._validate_contained_path(skills_root, package_directory)
        self._validate_non_executable_scripts(package_directory)

        skill_document = self._read_required_text(
            package_directory,
            Path('SKILL.md'),
        )
        frontmatter_data, instruction = self._parse_skill_document(
            skill_document
        )
        metadata_data = self._read_yaml_mapping(
            package_directory,
            Path('mosaic.yaml'),
        )

        try:
            frontmatter = AgentSkillFrontmatter.model_validate(
                frontmatter_data
            )
            metadata = MosaicSkillMetadata.model_validate(metadata_data)
        except ValidationError as error:
            raise ValueError(
                f"Skill package '{package_directory.name}' has invalid "
                'metadata.'
            ) from error

        if frontmatter.name != package_directory.name:
            raise ValueError(
                f"Skill package directory '{package_directory.name}' must "
                f"match frontmatter name '{frontmatter.name}'."
            )

        output_form = self._read_optional_output_form(
            package_directory,
            metadata,
        )
        output_schema = self._read_optional_output_schema(
            package_directory,
            metadata,
        )

        try:
            return Skill(
                name=frontmatter.name,
                version=metadata.version,
                kind=metadata.kind,
                description=frontmatter.description,
                instruction=instruction,
                output_form=output_form,
                output_schema=output_schema,
                required_capability_names=(
                    metadata.required_capability_names
                ),
                optional_capability_names=(
                    metadata.optional_capability_names
                ),
            )
        except ValidationError as error:
            raise ValueError(
                f"Skill package '{package_directory.name}' is invalid."
            ) from error

    def _parse_skill_document(
        self,
        skill_document: str,
    ) -> tuple[dict[str, Any], str]:
        """Separate and parse YAML frontmatter from Markdown instructions.

        Args:
            skill_document: Complete UTF-8 text of ``SKILL.md``.

        Returns:
            Parsed frontmatter mapping and non-empty Markdown instructions.

        Raises:
            ValueError: If frontmatter delimiters, YAML, or instructions are
                invalid.
        """
        lines = skill_document.splitlines()
        if not lines or lines[0].strip() != '---':
            raise ValueError(
                'SKILL.md must begin with YAML frontmatter.'
            )

        closing_index = next(
            (
                index
                for index, line in enumerate(lines[1:], start=1)
                if line.strip() == '---'
            ),
            None,
        )
        if closing_index is None:
            raise ValueError(
                'SKILL.md frontmatter must have a closing delimiter.'
            )

        frontmatter_text = '\n'.join(lines[1:closing_index])
        instruction = '\n'.join(lines[closing_index + 1 :]).strip()
        if not instruction:
            raise ValueError(
                'SKILL.md must contain non-empty instructions.'
            )

        frontmatter = self._parse_yaml_mapping(
            frontmatter_text,
            'SKILL.md frontmatter',
        )
        return frontmatter, instruction

    def _read_yaml_mapping(
        self,
        package_directory: Path,
        relative_path: Path,
    ) -> dict[str, Any]:
        """Read a required UTF-8 YAML file as a mapping.

        Args:
            package_directory: Root directory of the skill package.
            relative_path: Safe path of the required YAML file.

        Returns:
            Parsed YAML mapping.

        Raises:
            ValueError: If the file or YAML is invalid.
        """
        text = self._read_required_text(package_directory, relative_path)
        return self._parse_yaml_mapping(text, str(relative_path))

    def _parse_yaml_mapping(
        self,
        text: str,
        source_name: str,
    ) -> dict[str, Any]:
        """Parse trusted-format YAML with safe construction.

        Args:
            text: YAML content to parse.
            source_name: Safe source label used in validation errors.

        Returns:
            Parsed YAML mapping.

        Raises:
            ValueError: If YAML is malformed or not a map.
        """
        try:
            parsed_value = yaml.safe_load(text)
        except yaml.YAMLError as error:
            raise ValueError(
                f'{source_name} contains malformed YAML.'
            ) from error

        if not isinstance(parsed_value, dict):
            raise ValueError(  # noqa: TRY004
                f'{source_name} must contain a YAML mapping.'
            )
        return parsed_value

    def _read_optional_output_form(
        self,
        package_directory: Path,
        metadata: MosaicSkillMetadata,
    ) -> str | None:
        """Read the optional Markdown output form.

        Args:
            package_directory: Root directory of the skill package.
            metadata: Validated MOSAIC metadata for the package.

        Returns:
            The output-form text, or ``None`` when it is not declared.

        Raises:
            ValueError: If the declared file is invalid.
        """
        if metadata.output_form_file is None:
            return None
        return self._read_required_text(
            package_directory,
            Path(metadata.output_form_file),
        )

    def _read_optional_output_schema(
        self,
        package_directory: Path,
        metadata: MosaicSkillMetadata,
    ) -> dict[str, Any] | None:
        """Read and validate the optional Draft 2020-12 JSON Schema.

        Args:
            package_directory: Root directory of the skill package.
            metadata: Validated MOSAIC metadata for the package.

        Returns:
            The JSON Schema object, or ``None`` when it is not declared.

        Raises:
            ValueError: If JSON or its schema is invalid.
        """
        if metadata.output_schema_file is None:
            return None

        schema_text = self._read_required_text(
            package_directory,
            Path(metadata.output_schema_file),
        )
        try:
            parsed_schema = json.loads(schema_text)
        except json.JSONDecodeError as error:
            raise ValueError(
                'The declared output schema contains malformed JSON.'
            ) from error
        if not isinstance(parsed_schema, dict):
            raise ValueError(  # noqa: TRY004
                'The declared output schema must be a JSON object.'
            )

        try:
            Draft202012Validator.check_schema(parsed_schema)
        except SchemaError as error:
            raise ValueError(
                'The declared output schema is not a valid JSON Schema.'
            ) from error
        return parsed_schema

    def _read_required_text(
        self,
        package_directory: Path,
        relative_path: Path,
    ) -> str:
        """Read a non-empty UTF-8 regular file within a package.

        Args:
            package_directory: Root directory of the skill package.
            relative_path: Package-relative path of the required file.

        Returns:
            Stripped UTF-8 file content.

        Raises:
            ValueError: If the file is missing, unsafe, unreadable, empty, or
                not valid UTF-8.
        """
        file_path = package_directory / relative_path
        self._validate_contained_path(package_directory, file_path)
        if not file_path.is_file() or file_path.is_symlink():
            raise ValueError(
                f"Required file '{relative_path.as_posix()}' is missing."
            )

        try:
            content = file_path.read_text(encoding='utf-8').strip()
        except (OSError, UnicodeError) as error:
            raise ValueError(
                f"Required file '{relative_path.as_posix()}' is unreadable."
            ) from error
        if not content:
            raise ValueError(
                f"Required file '{relative_path.as_posix()}' is empty."
            )
        return content

    def _validate_contained_path(
        self,
        parent_directory: Path,
        candidate_path: Path,
    ) -> None:
        """Ensure a candidate resolves beneath its expected parent.

        Args:
            parent_directory: Directory that must contain the candidate.
            candidate_path: Path being checked.

        Raises:
            ValueError: If the candidate escapes its parent.
        """
        try:
            candidate_path.resolve().relative_to(
                parent_directory.resolve()
            )
        except (OSError, ValueError) as error:
            raise ValueError(
                'A skill package path escapes its allowed directory.'
            ) from error

    def _validate_non_executable_scripts(
        self,
        package_directory: Path,
    ) -> None:
        """Reject executable files because MVP skills are declarative only.

        Args:
            package_directory: Root directory of the skill package.

        Raises:
            ValueError: If an executable file exists below the standard
                ``scripts`` directory.
        """
        scripts_directory = package_directory / 'scripts'
        if not scripts_directory.exists():
            return
        if not scripts_directory.is_dir() or scripts_directory.is_symlink():
            raise ValueError(
                "'scripts' must be a regular directory when present."
            )

        for script_path in scripts_directory.rglob('*'):
            if script_path.is_symlink():
                raise ValueError(
                    'Skill packages cannot contain symbolic links.'
                )
            if script_path.is_file() and script_path.stat().st_mode & (
                stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
            ):
                raise ValueError(
                    'Executable skill scripts are not permitted in the MVP.'
                )
