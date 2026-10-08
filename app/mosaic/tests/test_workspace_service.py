import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.stale_workspace_version_error import StaleWorkspaceVersionError
from mosaic.components.persistence.user_access_repository import UserAccessRepository
from mosaic.components.persistence.workspace_service import WorkspaceService
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestWorkspaceService(unittest.TestCase):
    def test_create_for_user_returns_one_empty_workspace(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            created_at = datetime.now(UTC)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                with database.create_session() as session:
                    user_repository = UserAccessRepository(session)
                    workspace_service = WorkspaceService(session)
                    with session.begin():
                        user_repository.add_user(
                            'workspace-service-user',
                            created_at,
                        )
                        workspace = workspace_service.create_for_user(
                            'workspace-service-user',
                            created_at,
                        )

                    with (
                        self.assertRaises(ValueError),
                        session.begin(),
                    ):
                        workspace_service.create_for_user(
                            'workspace-service-user',
                            created_at,
                        )
            finally:
                database.dispose()

            self.assertEqual(workspace.user_id, 'workspace-service-user')
            self.assertEqual(workspace.version, 1)
            self.assertEqual(workspace.skill_ids, ())
            self.assertEqual(str(UUID(workspace.workspace_id)), workspace.workspace_id)

    def test_replace_skill_ids_is_atomic_and_versioned(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            created_at = datetime.now(UTC)
            updated_at = created_at + timedelta(minutes=1)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                with database.create_session() as session:
                    user_repository = UserAccessRepository(session)
                    workspace_service = WorkspaceService(session)
                    with session.begin():
                        user_repository.add_user(
                            'replacement-user',
                            created_at,
                        )
                        workspace_service.create_for_user(
                            'replacement-user',
                            created_at,
                        )
                        updated_workspace = (
                            workspace_service.replace_skill_ids(
                                'replacement-user',
                                1,
                                ('skill-b', 'skill-a'),
                                updated_at,
                            )
                        )

                    with (
                        self.assertRaises(ValueError),
                        session.begin(),
                    ):
                        workspace_service.replace_skill_ids(
                            'replacement-user',
                            2,
                            ('skill-a', 'skill-a'),
                            updated_at,
                        )
                    current_workspace = workspace_service.get_for_user(
                        'replacement-user'
                    )
            finally:
                database.dispose()

            self.assertEqual(updated_workspace.version, 2)
            self.assertEqual(
                updated_workspace.skill_ids,
                ('skill-a', 'skill-b'),
            )
            self.assertEqual(current_workspace, updated_workspace)

    def test_stale_replacement_is_rejected_without_changing_skills(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            created_at = datetime.now(UTC)

            try:
                MosaicDatabaseMigrator(database).upgrade()
                with database.create_session() as session:
                    user_repository = UserAccessRepository(session)
                    workspace_service = WorkspaceService(session)
                    with session.begin():
                        user_repository.add_user('stale-user', created_at)
                        workspace_service.create_for_user(
                            'stale-user',
                            created_at,
                        )
                        workspace_service.replace_skill_ids(
                            'stale-user',
                            1,
                            ('current-skill',),
                            created_at,
                        )

                    with (
                        self.assertRaises(StaleWorkspaceVersionError),
                        session.begin(),
                    ):
                        workspace_service.replace_skill_ids(
                            'stale-user',
                            1,
                            ('stale-skill',),
                            created_at,
                        )
                    current_workspace = workspace_service.get_for_user(
                        'stale-user'
                    )
            finally:
                database.dispose()

            self.assertEqual(current_workspace.version, 2)
            self.assertEqual(
                current_workspace.skill_ids,
                ('current-skill',),
            )
