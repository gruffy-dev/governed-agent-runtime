import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import select

from mosaic.components.persistence.mosaic_database import MosaicDatabase
from mosaic.components.persistence.mosaic_database_migrator import MosaicDatabaseMigrator
from mosaic.components.persistence.user_record import UserRecord
from mosaic.components.persistence.workspace_record import WorkspaceRecord
from mosaic.components.persistence.workspace_skill_record import WorkspaceSkillRecord
from mosaic.models.mosaic_database_configuration import MosaicDatabaseConfiguration


class TestWorkspaceRecords(unittest.TestCase):
    def test_records_match_migrated_table_columns(self) -> None:
        self.assertEqual(
            set(WorkspaceRecord.__table__.columns.keys()),
            {
                'workspace_id',
                'user_id',
                'version',
                'created_at',
                'updated_at',
            },
        )
        self.assertEqual(
            set(WorkspaceSkillRecord.__table__.columns.keys()),
            {'workspace_id', 'skill_id'},
        )

    def test_workspace_starts_empty_and_persists_atomic_skill_ids(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = MosaicDatabase(
                MosaicDatabaseConfiguration(
                    database_path=(
                        Path(temporary_directory) / 'mosaic.db'
                    )
                )
            )
            created_at = datetime.now(UTC)
            user = UserRecord(
                user_id='workspace-record-user',
                is_enabled=True,
                created_at=created_at,
                disabled_at=None,
            )
            workspace = WorkspaceRecord(
                workspace_id='00000000-0000-4000-8000-000000000030',
                user_id=user.user_id,
                version=1,
                created_at=created_at,
                updated_at=created_at,
            )

            try:
                MosaicDatabaseMigrator(database).upgrade()
                with database.create_session() as session:
                    session.add(user)
                    session.flush()
                    session.add(workspace)
                    session.flush()
                    initial_skills = session.scalars(
                        select(WorkspaceSkillRecord).where(
                            WorkspaceSkillRecord.workspace_id
                            == workspace.workspace_id
                        )
                    ).all()
                    session.add(
                        WorkspaceSkillRecord(
                            workspace_id=workspace.workspace_id,
                            skill_id='example-skill',
                        )
                    )
                    session.commit()
                    stored_skills = session.scalars(
                        select(WorkspaceSkillRecord).where(
                            WorkspaceSkillRecord.workspace_id
                            == workspace.workspace_id
                        )
                    ).all()
            finally:
                database.dispose()

            self.assertEqual(initial_skills, [])
            self.assertEqual(
                [record.skill_id for record in stored_skills],
                ['example-skill'],
            )
