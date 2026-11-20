from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .mosaic_database_record import MosaicDatabaseRecord


class ConversationJobRecord(MosaicDatabaseRecord):
    __tablename__ = 'conversation_jobs'
    __table_args__ = (
        sa.PrimaryKeyConstraint('job_id', name='pk_conversation_jobs'),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'stopping', 'awaiting_clarification', 'succeeded', 'failed', 'cancelled')",
            name='ck_conversation_jobs_status',
        ),
        sa.Index('ix_conversation_jobs_conversation', 'conversation_id', 'created_at'),
        sa.Index('ux_conversation_jobs_submission_key', 'conversation_id', 'submission_key', unique=True),
    )

    job_id: Mapped[str] = mapped_column(sa.String(36))
    conversation_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            'conversation_metadata.conversation_id',
            name='fk_conversation_jobs_conversation_id', ondelete='RESTRICT',
        ),
        nullable=False,
    )
    request_text: Mapped[str] = mapped_column(sa.Text(), nullable=False)
    submission_key: Mapped[str | None] = mapped_column(sa.String(36))
    status: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    result_text: Mapped[str | None] = mapped_column(sa.Text())
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
