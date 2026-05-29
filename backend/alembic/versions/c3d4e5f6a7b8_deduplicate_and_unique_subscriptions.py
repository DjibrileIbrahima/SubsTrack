"""deduplicate and unique constraint on subscriptions

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-05-29 00:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remove duplicate plaid subscriptions, keeping the most recently updated row
    op.execute("""
        DELETE FROM subscriptions
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                    ROW_NUMBER() OVER (
                        PARTITION BY user_id, LOWER(merchant), source
                        ORDER BY updated_at DESC NULLS LAST, id DESC
                    ) AS rn
                FROM subscriptions
            ) t
            WHERE rn > 1
        )
    """)

    # Unique index prevents duplicates at the DB level going forward
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_subscriptions_user_merchant_source
        ON subscriptions (user_id, LOWER(merchant), source)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_subscriptions_user_merchant_source")
