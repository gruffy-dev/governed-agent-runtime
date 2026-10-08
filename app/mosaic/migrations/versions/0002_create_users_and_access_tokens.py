"""Create pilot users and hashed access-token storage.

Revision ID: 0002_user_access
Revises: 0001_mosaic_baseline
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '0002_user_access'
down_revision: str | Sequence[str] | None = '0001_mosaic_baseline'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create portable user and hashed access-token tables."""
    op.create_table(
        'users',
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column(
            'is_enabled',
            sa.Boolean(
                create_constraint=True,
                name='ck_users_is_enabled',
            ),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            'disabled_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            '(is_enabled AND disabled_at IS NULL) OR '
            '(NOT is_enabled AND disabled_at IS NOT NULL)',
            name='ck_users_enabled_timestamp',
        ),
        sa.CheckConstraint(
            'length(user_id) BETWEEN 1 AND 255',
            name='ck_users_user_id_length',
        ),
        sa.PrimaryKeyConstraint('user_id', name='pk_users'),
    )
    op.create_table(
        'access_tokens',
        sa.Column('token_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column(
            'is_enabled',
            sa.Boolean(
                create_constraint=True,
                name='ck_access_tokens_is_enabled',
            ),
            nullable=False,
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            'disabled_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            'rotated_at',
            sa.DateTime(timezone=True),
            nullable=True,
        ),
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
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['users.user_id'],
            name='fk_access_tokens_user_id_users',
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('token_id', name='pk_access_tokens'),
    )
    op.create_index(
        'ix_access_tokens_token_hash',
        'access_tokens',
        ['token_hash'],
        unique=True,
    )
    op.create_index(
        'ix_access_tokens_user_id_is_enabled',
        'access_tokens',
        ['user_id', 'is_enabled'],
        unique=False,
    )


def downgrade() -> None:
    """Remove pilot user and access-token storage."""
    op.drop_index(
        'ix_access_tokens_user_id_is_enabled',
        table_name='access_tokens',
    )
    op.drop_index(
        'ix_access_tokens_token_hash',
        table_name='access_tokens',
    )
    op.drop_table('access_tokens')
    op.drop_table('users')
