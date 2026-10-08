from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from .mosaic_database_record import MosaicDatabaseRecord


class UserRecord(MosaicDatabaseRecord):
    __tablename__ = 'users'
    __table_args__ = (
        sa.CheckConstraint(
            '(is_enabled AND disabled_at IS NULL) OR '
            '(NOT is_enabled AND disabled_at IS NOT NULL)',
            name='ck_users_enabled_timestamp',
        ),
        sa.CheckConstraint(
            'length(user_id) BETWEEN 1 AND 255',
            name='ck_users_user_id_length',
        ),
    )

    user_id: Mapped[str] = mapped_column(
        sa.String(length=255),
        primary_key=True,
    )
    is_enabled: Mapped[bool] = mapped_column(
        sa.Boolean(
            create_constraint=True,
            name='ck_users_is_enabled',
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
