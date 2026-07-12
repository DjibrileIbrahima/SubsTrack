"""add linked_accounts.status and convert subscriptions.amount to numeric

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-12 00:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "linked_accounts",
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
    )
    op.alter_column(
        "subscriptions",
        "amount",
        existing_type=sa.Float(),
        type_=sa.Numeric(10, 2),
        existing_nullable=False,
        postgresql_using="round(amount::numeric, 2)",
    )


def downgrade() -> None:
    op.alter_column(
        "subscriptions",
        "amount",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Float(),
        existing_nullable=False,
    )
    op.drop_column("linked_accounts", "status")
