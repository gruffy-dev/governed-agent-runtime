from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .mosaic_database_record import MosaicDatabaseRecord


class AccessTokenRecord(MosaicDatabaseRecord):
    __tablename__ = 'access_tokens'
    __table_args__ = (
        sa.CheckConstraint(
            'length(token_id) = 36',
            name='ck_access_tokens_token_id_length',
        ),
        sa.CheckConstraint(
            'length(token_hash) = 64',
            name='ck_access_tokens_token_hash_length',
        ),
        sa.CheckConstraint(
            '(is_enabled AND disabled_at IS NULL '
            'AND rotated_at IS NULL) OR '
            '(NOT is_enabled AND disabled_at IS NOT NULL '
            'AND rotated_at IS NULL) OR '
            '(NOT is_enabled AND disabled_at IS NULL '
            'AND rotated_at IS NOT NULL)',
            name='ck_access_tokens_enabled_timestamp',
        ),
        sa.Index(
            'ix_access_tokens_token_hash',
            'token_hash',
            unique=True,
        ),
        sa.Index(
            'ix_access_tokens_user_id_is_enabled',
            'user_id',
            'is_enabled',
        ),
    )

    token_id: Mapped[str] = mapped_column(
        sa.String(length=36),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        sa.String(length=255),
        sa.ForeignKey(
            'users.user_id',
            name='fk_access_tokens_user_id_users',
            ondelete='RESTRICT',
        ),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(
        sa.String(length=64),
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(
        sa.Boolean(
            create_constraint=True,
            name='ck_access_tokens_is_enabled',
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    disabled_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    rotated_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
