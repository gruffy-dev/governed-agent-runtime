from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0003_workspace_skills'
down_revision: str | Sequence[str] | None = '0002_user_access'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    Create one versioned workspace per user and its atomic Skill references.
    """
    op.create_table(
        'workspaces',
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            'length(workspace_id) = 36',
            name='ck_workspaces_workspace_id_length',
        ),
        sa.CheckConstraint(
            'version >= 1',
            name='ck_workspaces_version_positive',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.user_id'],
            name='fk_workspaces_user_id_users',
            ondelete='RESTRICT',
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
    op.create_table(
        'workspace_skills',
        sa.Column('workspace_id', sa.String(length=36), nullable=False),
        sa.Column('skill_id', sa.String(length=255), nullable=False),
        sa.CheckConstraint(
            'length(skill_id) BETWEEN 1 AND 255',
            name='ck_workspace_skills_skill_id_length',
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces.workspace_id'],
            name='fk_workspace_skills_workspace_id_workspaces',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint(
            'workspace_id',
            'skill_id',
            name='pk_workspace_skills',
        ),
    )


def downgrade() -> None:
    """
    Remove workspace and atomic Skill-reference storage.
    """
    op.drop_table('workspace_skills')
    op.drop_table('workspaces')
