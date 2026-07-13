"""normalize emails to lowercase and enforce case-insensitive uniqueness

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-13 00:00:00.000000

Foo@x.com and foo@x.com were two accounts, which also broke the Google
OAuth match-by-email path (Google may return different casing, silently
creating a second empty account).

Case-duplicate accounts can't be merged automatically: the OLDEST account
per address keeps the email (it most likely holds the user's data); newer
duplicates get a ".duplicate.<id-prefix>" suffix so nothing is deleted and
the affected rows are easy to find and resolve by hand.
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rename newer case-duplicates out of the way (oldest account wins)
    op.execute(
        """
        UPDATE users u
        SET email = u.email || '.duplicate.' || substr(u.id::text, 1, 8)
        WHERE EXISTS (
            SELECT 1 FROM users v
            WHERE lower(v.email) = lower(u.email)
              AND v.id != u.id
              AND (v.created_at < u.created_at
                   OR (v.created_at = u.created_at AND v.id < u.id))
        )
        """
    )
    op.execute("UPDATE users SET email = lower(email) WHERE email != lower(email)")
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_email_lower", table_name="users")
