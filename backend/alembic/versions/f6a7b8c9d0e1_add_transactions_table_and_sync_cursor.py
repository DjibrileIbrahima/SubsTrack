"""add transactions table and linked_accounts.sync_cursor

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-13 00:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "linked_accounts",
        sa.Column("sync_cursor", sa.String(256), nullable=True),
    )
    op.create_table(
        "transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("plaid_transaction_id", sa.String(256), nullable=False),
        sa.Column(
            "linked_account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("linked_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("merchant_name", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("pending", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_transactions_plaid_transaction_id",
        "transactions",
        ["plaid_transaction_id"],
        unique=True,
    )
    op.create_index("ix_transactions_linked_account_id", "transactions", ["linked_account_id"])
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_user_date", "transactions", ["user_id", "date"])


def downgrade() -> None:
    op.drop_index("ix_transactions_user_date", table_name="transactions")
    op.drop_index("ix_transactions_user_id", table_name="transactions")
    op.drop_index("ix_transactions_linked_account_id", table_name="transactions")
    op.drop_index("ix_transactions_plaid_transaction_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_column("linked_accounts", "sync_cursor")
