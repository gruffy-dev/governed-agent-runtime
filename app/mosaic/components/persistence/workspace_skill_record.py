import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .mosaic_database_record import MosaicDatabaseRecord


class WorkspaceSkillRecord(MosaicDatabaseRecord):
    __tablename__ = 'workspace_skills'
    __table_args__ = (
        sa.CheckConstraint(
            'length(skill_id) BETWEEN 1 AND 255',
            name='ck_workspace_skills_skill_id_length',
        ),
        sa.PrimaryKeyConstraint(
            'workspace_id',
            'skill_id',
            name='pk_workspace_skills',
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        sa.String(length=36),
        sa.ForeignKey(
            'workspaces.workspace_id',
            name='fk_workspace_skills_workspace_id_workspaces',
            ondelete='CASCADE',
        ),
        nullable=False,
    )
    skill_id: Mapped[str] = mapped_column(
        sa.String(length=255),
        nullable=False,
    )
