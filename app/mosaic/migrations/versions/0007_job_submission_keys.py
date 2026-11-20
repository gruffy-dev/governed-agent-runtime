from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0007_job_submission_keys'
down_revision: str | Sequence[str] | None = '0006_create_conversation_jobs'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    Add an optional submission key unique to each conversation.
    """
    op.add_column('conversation_jobs', sa.Column('submission_key', sa.String(36), nullable=True))
    op.create_index(
        'ux_conversation_jobs_submission_key', 'conversation_jobs',
        ['conversation_id', 'submission_key'], unique=True,
    )


def downgrade() -> None:
    """
    Remove submission keys while retaining jobs and their results.
    """
    op.drop_index('ux_conversation_jobs_submission_key', table_name='conversation_jobs')
    with op.batch_alter_table('conversation_jobs') as batch:
        batch.drop_column('submission_key')
