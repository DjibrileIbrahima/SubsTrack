"""add sync_status and last_synced_at to linked_accounts

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-27 00:00:00.000000

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, None] = "d0e1f2a3b4c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "linked_accounts",
        sa.Column("sync_status", sa.String(16), nullable=False, server_default="idle"),
    )
    op.add_column(
        "linked_accounts",
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("linked_accounts", "last_synced_at")
    op.drop_column("linked_accounts", "sync_status")
