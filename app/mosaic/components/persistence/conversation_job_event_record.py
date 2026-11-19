import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .mosaic_database_record import MosaicDatabaseRecord


class ConversationJobEventRecord(MosaicDatabaseRecord):
    __tablename__ = 'conversation_job_events'

    job_id: Mapped[str] = mapped_column(
        sa.String(36), sa.ForeignKey('conversation_jobs.job_id', ondelete='CASCADE'),
        primary_key=True,
    )
    sequence: Mapped[int] = mapped_column(sa.Integer(), primary_key=True)
    frame: Mapped[bytes] = mapped_column(sa.LargeBinary(), nullable=False)
