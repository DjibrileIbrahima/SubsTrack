"""dedupe alerts and add unique (subscription_id, due_date) index

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-13 00:00:00.000000

Alert generation was check-then-insert with no constraint, so concurrent
runs (daily cron + manual trigger, or worker replicas) could create
duplicate alerts and duplicate emails. Keep the newest of any duplicates,
then let the DB enforce one alert per subscription per due date.
"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM alerts WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY subscription_id, due_date
                    ORDER BY created_at DESC, id
                ) AS rn
                FROM alerts
                WHERE subscription_id IS NOT NULL AND due_date IS NOT NULL
            ) ranked WHERE rn > 1
        )
        """
    )
    op.create_index(
        "ix_alerts_subscription_due",
        "alerts",
        ["subscription_id", "due_date"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_alerts_subscription_due", table_name="alerts")
