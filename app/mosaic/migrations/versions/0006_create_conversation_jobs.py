from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = '0006_create_conversation_jobs'
down_revision: str | Sequence[str] | None = '0005_conversation_availability'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """
    Store background job outcomes separately from ADK conversation history.
    """
    op.create_table(
        'conversation_jobs',
        sa.Column('job_id', sa.String(36), nullable=False),
        sa.Column('conversation_id', sa.String(36), nullable=False),
        sa.Column('request_text', sa.Text(), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('result_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('job_id', name='pk_conversation_jobs'),
        sa.ForeignKeyConstraint(
            ['conversation_id'], ['conversation_metadata.conversation_id'],
            name='fk_conversation_jobs_conversation_id', ondelete='RESTRICT',
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'stopping', 'awaiting_clarification', 'succeeded', 'failed', 'cancelled')",
            name='ck_conversation_jobs_status',
        ),
    )
    op.create_index('ix_conversation_jobs_conversation', 'conversation_jobs', ['conversation_id', 'created_at'])

    op.create_table(
        'conversation_job_events',
        sa.Column('job_id', sa.String(36), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('frame', sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['conversation_jobs.job_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('job_id', 'sequence'),
    )


def downgrade() -> None:
    """
    Remove background job records while retaining conversation metadata and history.
    """
    op.drop_table('conversation_job_events')
    op.drop_index('ix_conversation_jobs_conversation', table_name='conversation_jobs')
    op.drop_table('conversation_jobs')
