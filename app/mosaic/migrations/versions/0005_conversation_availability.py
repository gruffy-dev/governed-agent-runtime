from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0005_conversation_availability'
down_revision: str | Sequence[str] | None = '0004_conversation_metadata'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    Add durable availability markers without modifying ADA sessions or history.
    """
    op.add_column(
        'conversation_metadata',
        sa.Column(
            'invocation_in_progress',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        'conversation_metadata',
        sa.Column(
            'is_interrupted', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    """
    Remove availability markers while retaining owned metadata and ADA history.
    """
    with op.batch_alter_table('conversation_metadata') as batch:
        batch.drop_column('is_interrupted')
        batch.drop_column('invocation_in_progress')
