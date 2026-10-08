from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .mosaic_database_record import MosaicDatabaseRecord


class WorkspaceRecord(MosaicDatabaseRecord):
    __tablename__ = 'workspaces'
    __table_args__ = (
        sa.CheckConstraint(
            'length(workspace_id) = 36',
            name='ck_workspaces_workspace_id_length',
        ),
        sa.CheckConstraint(
            'version >= 1',
            name='ck_workspaces_version_positive',
        ),
        sa.PrimaryKeyConstraint(
            'workspace_id',
            name='pk_workspaces',
        ),
        sa.UniqueConstraint(
            'user_id',
            name='uq_workspaces_user_id',
        ),
    )

    workspace_id: Mapped[str] = mapped_column(
        sa.String(length=36),
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(length=255),
        sa.ForeignKey(
            'users.user_id',
            name='fk_workspaces_user_id_users',
            ondelete='RESTRICT',
        ),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(
        sa.Integer(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
