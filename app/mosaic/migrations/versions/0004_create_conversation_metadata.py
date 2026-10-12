from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0004_conversation_metadata'
down_revision: str | Sequence[str] | None = '0003_workspace_skills'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    Record public conversation creation time without duplicating ADA history.
    """
    op.create_table(
        'conversation_metadata',
        sa.Column('conversation_id', sa.String(length=36), nullable=False),
        sa.Column('app_name', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            'length(conversation_id) = 36',
            name='ck_conversation_metadata_id_length',
        ),
        sa.CheckConstraint(
            'length(app_name) BETWEEN 1 AND 255',
            name='ck_conversation_metadata_app_name_length',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.user_id'],
            name='fk_conversation_metadata_user_id_users',
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('conversation_id', name='pk_conversation_metadata'),
    )
    op.create_index(
        'ix_conversation_metadata_owner',
        'conversation_metadata',
        ['app_name', 'user_id'],
    )


def downgrade() -> None:
    """
    Remove owned metadata while leaving ADA session storage untouched.
    """
    op.drop_index('ix_conversation_metadata_owner', table_name='conversation_metadata')
    op.drop_table('conversation_metadata')
