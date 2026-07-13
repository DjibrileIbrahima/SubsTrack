"""add subscriptions.linked_account_id

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-13 00:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column(
            "linked_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("linked_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_subscriptions_linked_account_id", "subscriptions", ["linked_account_id"]
    )
    # Backfill: when a user has exactly one linked account, their plaid
    # subscriptions can only have come from it. Multi-account users are left
    # NULL and get attributed on the next sync.
    op.execute(
        """
        UPDATE subscriptions SET linked_account_id = (
            SELECT la.id FROM linked_accounts la WHERE la.user_id = subscriptions.user_id
        )
        WHERE source = 'plaid' AND (
            SELECT COUNT(*) FROM linked_accounts la WHERE la.user_id = subscriptions.user_id
        ) = 1
        """
    )


def downgrade() -> None:
    op.drop_index("ix_subscriptions_linked_account_id", table_name="subscriptions")
    op.drop_column("subscriptions", "linked_account_id")
