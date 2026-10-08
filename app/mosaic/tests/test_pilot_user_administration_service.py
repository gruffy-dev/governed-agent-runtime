import base64
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from mosaic.components.identity.pilot_user_administration_service import PilotUserAdministrationService
from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.components.persistence.workspace_service import WorkspaceService
from mosaic.models.identity.pilot_workspace_skill_update_request import PilotWorkspaceSkillUpdateRequest
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration
from mosaic.models.skills.skill import Skill
from mosaic.models.skills.skill_catalogue_group import SkillCatalogueGroup
from mosaic.models.skills.skill_catalogue_snapshot import SkillCatalogueSnapshot


class TestPilotUserAdministrationService(unittest.TestCase):
    def test_create_user_provisions_token_and_empty_workspace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            service = PilotUserAdministrationService(database)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                credential = service.create_user('pilot-user')
                plaintext_token = (
                    credential.plaintext_token.get_secret_value()
                )
                with database.create_session() as session:
                    resolved_user = UserAccessRepository(
                        session
                    ).resolve_enabled_user(plaintext_token)
                    workspace = WorkspaceService(session).get_for_user(
                        'pilot-user'
                    )
            finally:
                database.dispose()

            self.assertTrue(plaintext_token.startswith('mosaic_r1_'))
            encoded_random_bytes = plaintext_token.removeprefix('mosaic_r1_')
            padded_token = encoded_random_bytes + '=' * (
                -len(encoded_random_bytes) % 4
            )
            random_bytes = base64.urlsafe_b64decode(padded_token)
            self.assertEqual(len(random_bytes), 32)
            self.assertEqual(str(UUID(credential.token_id)), credential.token_id)
            self.assertIsNotNone(resolved_user)
            self.assertIsNotNone(workspace)
            self.assertEqual(workspace.skill_ids, ())

    def test_duplicate_user_rolls_back_without_extra_workspace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            service = PilotUserAdministrationService(database)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                service.create_user('duplicate-pilot-user')
                with self.assertRaises(IntegrityError):
                    service.create_user('duplicate-pilot-user')
                users = service.list_users()
                with database.create_session() as session:
                    workspace = WorkspaceService(session).get_for_user(
                        'duplicate-pilot-user'
                    )
            finally:
                database.dispose()

            self.assertEqual(len(users), 1)
            self.assertIsNotNone(workspace)

    def test_list_and_disable_do_not_expose_token_material(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            service = PilotUserAdministrationService(database)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                credential = service.create_user('disable-pilot-user')
                self.assertTrue(service.disable_user('disable-pilot-user'))
                users = service.list_users()
                with database.create_session() as session:
                    resolved_user = UserAccessRepository(
                        session
                    ).resolve_enabled_user(
                        credential.plaintext_token.get_secret_value()
                    )
            finally:
                database.dispose()

            self.assertEqual(len(users), 1)
            self.assertFalse(users[0].is_enabled)
            self.assertIsNotNone(users[0].disabled_at)
            self.assertNotIn('token', users[0].model_dump())
            self.assertIsNone(resolved_user)

    def test_token_generation_requests_32_random_bytes(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            service = PilotUserAdministrationService(database)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                with patch(
                    'mosaic.components.identity.'
                    'pilot_user_administration_service.token_urlsafe',
                    return_value='synthetic-pilot-token',
                ) as token_generator:
                    credential = service.create_user('entropy-pilot-user')
            finally:
                database.dispose()

            token_generator.assert_called_once_with(32)
            self.assertEqual(
                credential.plaintext_token.get_secret_value(),
                'mosaic_r1_synthetic-pilot-token',
            )

    def test_workspace_skill_updates_expand_groups_and_fail_closed(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            service = PilotUserAdministrationService(
                database,
                self._create_catalogue_snapshot(),
            )

            try:
                MosaicDatabaseMigrator(database).upgrade()
                service.create_user('workspace-user')
                dry_run = service.update_workspace_skills(
                    'workspace-user',
                    PilotWorkspaceSkillUpdateRequest(
                        group_ids=('platform/diagnostics',),
                        dry_run=True,
                    ),
                )
                unchanged = service.get_workspace_skills('workspace-user')
                applied = service.update_workspace_skills(
                    'workspace-user',
                    PilotWorkspaceSkillUpdateRequest(
                        skill_ids=('summarize-findings',),
                        group_ids=('platform/diagnostics',),
                    ),
                )
                with self.assertRaises(ValueError):
                    service.update_workspace_skills(
                        'workspace-user',
                        PilotWorkspaceSkillUpdateRequest(
                            skill_ids=('unknown-skill',),
                        ),
                    )
                with self.assertRaises(ValueError):
                    service.update_workspace_skills(
                        'workspace-user',
                        PilotWorkspaceSkillUpdateRequest(
                            group_ids=('platform/unknown',),
                        ),
                    )
                after_rejection = service.get_workspace_skills(
                    'workspace-user'
                )
            finally:
                database.dispose()

        self.assertFalse(dry_run.applied)
        self.assertEqual(
            dry_run.skill_ids,
            ('inspect-platform',),
        )
        self.assertEqual(unchanged.skill_ids, ())
        self.assertEqual(unchanged.version, 1)
        self.assertTrue(applied.applied)
        self.assertEqual(
            applied.skill_ids,
            ('inspect-platform', 'summarize-findings'),
        )
        self.assertEqual(applied.version, 2)
        self.assertEqual(after_rejection.skill_ids, applied.skill_ids)
        self.assertEqual(after_rejection.version, applied.version)

    @staticmethod
    def _create_catalogue_snapshot() -> SkillCatalogueSnapshot:
        skills = tuple(
            Skill(
                name=name,
                version='1.0.0',
                kind='procedural',
                description=f'{name} description.',
                instruction=f'{name} instruction.',
            )
            for name in ('inspect-platform', 'summarize-findings')
        )
        return SkillCatalogueSnapshot(
            commit_sha='a' * 40,
            loaded_at=datetime.now(UTC),
            skills=skills,
            groups=(
                SkillCatalogueGroup(
                    group_id='platform/diagnostics',
                    skill_ids=('inspect-platform',),
                ),
            ),
        )
