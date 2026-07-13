"""add subscriptions.merchant_key and deactivate price-drift duplicates

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-13 00:00:00.000000

Detected subscriptions used the display label (which may embed an average
amount, e.g. "Netflix ($15.49)") as their identity, so price changes created
duplicate rows. merchant_key is the stable identity: the normalized base
merchant with no amount.

The dedup step deactivates older ACTIVE plaid rows that have a fresher
sibling with the same merchant_key and an amount within the 40% match
tolerance used by the sync upsert. Genuinely distinct plans (amounts further
apart than the tolerance) are left alone.
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("merchant_key", sa.String(), nullable=True))
    op.create_index(
        "ix_subscriptions_user_merchant_key", "subscriptions", ["user_id", "merchant_key"]
    )

    # Backfill: strip the " ($12.34)" suffix old cluster labels embedded.
    op.execute(
        r"""
        UPDATE subscriptions
        SET merchant_key = lower(regexp_replace(merchant, ' \(\$[0-9.]+\)$', ''))
        WHERE source = 'plaid'
        """
    )

    # Deactivate accumulated price-drift duplicates: an active plaid row is
    # stale if a strictly fresher active row shares its merchant_key with an
    # amount within the 40% tolerance.
    op.execute(
        """
        UPDATE subscriptions SET is_active = false
        WHERE id IN (
            SELECT s_old.id
            FROM subscriptions s_old
            JOIN subscriptions s_new
              ON s_new.user_id = s_old.user_id
             AND s_new.merchant_key = s_old.merchant_key
             AND s_new.id != s_old.id
             AND s_new.source = 'plaid'
             AND s_new.is_active = true
             AND abs(s_new.amount - s_old.amount)
                 / greatest(s_new.amount, s_old.amount) <= 0.40
             AND (
                 s_old.updated_at < s_new.updated_at
                 OR (s_old.updated_at = s_new.updated_at AND s_old.id < s_new.id)
             )
            WHERE s_old.source = 'plaid' AND s_old.is_active = true
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_user_merchant_key", table_name="subscriptions")
    op.drop_column("subscriptions", "merchant_key")
