"""Local persistence for Plaid transactions.

The transactions table is kept fresh via Plaid /transactions/sync (cursor per
linked account). Dashboard reads (/summary, /transactions) and subscription
detection run against this table instead of calling Plaid on every request.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal

from plaid.exceptions import ApiException
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import LinkedAccount, Transaction
from services import plaid_service
from services.encryption import decrypt

logger = logging.getLogger(__name__)


class ItemReauthRequired(Exception):
    """The linked account's bank connection broke (ITEM_LOGIN_REQUIRED) and
    needs Link update-mode re-authentication. str(exc) is the institution name."""


def _to_money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _txn_date(t: dict) -> date:
    d = t.get("date")
    return d if isinstance(d, date) else date.fromisoformat(str(d))


def _txn_category(t: dict) -> str | None:
    cats = t.get("category")
    if cats:
        return cats[0]
    pfc = t.get("personal_finance_category")
    primary = pfc.get("primary") if isinstance(pfc, dict) else None
    return primary.replace("_", " ").title() if primary else None


async def sync_account_transactions(db: AsyncSession, account: LinkedAccount) -> int:
    """Pull incremental updates for one linked account into the transactions table.

    Commits, so the new cursor is only persisted together with the rows it
    represents. Returns the number of added/modified transactions.

    A transaction-scoped advisory lock serializes syncs per linked account across
    all processes (API + worker), so a manual sync racing a webhook sync can't
    both pull the same cursor and collide on the plaid_transaction_id unique index.
    The lock releases automatically on commit/rollback.
    """
    if db.bind.dialect.name == "postgresql":
        got_lock = (
            await db.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                {"key": f"plaid_sync:{account.id}"},
            )
        ).scalar()
        if not got_lock:
            logger.info("Sync already in progress for account %s — skipping", account.id)
            return 0

    try:
        added, modified, removed, cursor = await plaid_service.sync_transactions(
            decrypt(account.access_token), account.sync_cursor
        )
    except ApiException as exc:
        if plaid_service.plaid_error_code(exc) == "ITEM_LOGIN_REQUIRED":
            # Persist the broken state so Settings shows the Reconnect button
            # even if the ITEM webhook never arrives.
            account.status = "login_required"
            await db.commit()
            raise ItemReauthRequired(account.institution_name or "Your bank") from exc
        raise

    changed = added + modified
    if changed:
        ids = [t["transaction_id"] for t in changed]
        result = await db.execute(
            select(Transaction).where(Transaction.plaid_transaction_id.in_(ids))
        )
        existing = {row.plaid_transaction_id: row for row in result.scalars()}
        for t in changed:
            row = existing.get(t["transaction_id"])
            if row is None:
                row = Transaction(
                    plaid_transaction_id=t["transaction_id"],
                    linked_account_id=account.id,
                    user_id=account.user_id,
                )
                db.add(row)
                existing[t["transaction_id"]] = row
            row.amount = _to_money(t.get("amount") or 0)
            row.date = _txn_date(t)
            row.name = t.get("name")
            row.merchant_name = t.get("merchant_name")
            row.category = _txn_category(t)
            row.pending = bool(t.get("pending", False))

    removed_ids = [r["transaction_id"] for r in removed if r.get("transaction_id")]
    if removed_ids:
        await db.execute(
            delete(Transaction).where(Transaction.plaid_transaction_id.in_(removed_ids))
        )

    account.sync_cursor = cursor
    # A successful sync proves the connection works — recover the status even
    # if the LOGIN_REPAIRED webhook was never delivered.
    if account.status != "active":
        account.status = "active"
    await db.commit()

    logger.info(
        "Transaction sync for account %s: %d changed, %d removed",
        account.id, len(changed), len(removed_ids),
    )
    return len(changed)


async def get_user_transactions(db: AsyncSession, user_id, days: int) -> list[Transaction]:
    """Load a user's stored transactions within the window, newest first."""
    cutoff = date.today() - timedelta(days=days)
    result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user_id, Transaction.date >= cutoff)
        .order_by(Transaction.date.desc())
    )
    return list(result.scalars().all())


async def get_account_transactions(db: AsyncSession, account_id, days: int) -> list[Transaction]:
    """Load one linked account's stored transactions within the window, newest first."""
    cutoff = date.today() - timedelta(days=days)
    result = await db.execute(
        select(Transaction)
        .where(Transaction.linked_account_id == account_id, Transaction.date >= cutoff)
        .order_by(Transaction.date.desc())
    )
    return list(result.scalars().all())


def to_detection_dicts(rows: list[Transaction]) -> list[dict]:
    """Shape stored rows like Plaid transaction dicts for the detection pipeline."""
    return [
        {
            "amount": float(r.amount),
            "date": r.date.isoformat(),
            "name": r.name,
            "merchant_name": r.merchant_name,
            "category": [r.category] if r.category else None,
        }
        for r in rows
    ]


def serialize_transaction(r: Transaction) -> dict:
    return {
        "id": str(r.id),
        "amount": float(r.amount),
        "date": r.date.isoformat(),
        "name": r.name,
        "merchant_name": r.merchant_name,
        "category": r.category,
        "pending": r.pending,
    }
