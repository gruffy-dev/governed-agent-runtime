from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .mosaic_database_record import MosaicDatabaseRecord


class ConversationMetadataRecord(MosaicDatabaseRecord):
    __tablename__ = 'conversation_metadata'
    __table_args__ = (
        sa.CheckConstraint(
            'length(conversation_id) = 36',
            name='ck_conversation_metadata_id_length',
        ),
        sa.CheckConstraint(
            'length(app_name) BETWEEN 1 AND 255',
            name='ck_conversation_metadata_app_name_length',
        ),
        sa.PrimaryKeyConstraint('conversation_id', name='pk_conversation_metadata'),
        sa.Index('ix_conversation_metadata_owner', 'app_name', 'user_id'),
    )

    conversation_id: Mapped[str] = mapped_column(sa.String(length=36))
    app_name: Mapped[str] = mapped_column(sa.String(length=255), nullable=False)
    user_id: Mapped[str] = mapped_column(
        sa.String(length=255),
        sa.ForeignKey(
            'users.user_id',
            name='fk_conversation_metadata_user_id_users',
            ondelete='RESTRICT',
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    invocation_in_progress: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, default=False, server_default=sa.false()
    )
    is_interrupted: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, default=False, server_default=sa.false()
    )
