"""add item_id to linked_accounts

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-28 00:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE linked_accounts ADD COLUMN IF NOT EXISTS item_id VARCHAR(256)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_linked_accounts_item_id ON linked_accounts (item_id)"
    )


def downgrade() -> None:
    op.drop_index("ix_linked_accounts_item_id", table_name="linked_accounts")
    op.drop_column("linked_accounts", "item_id")
