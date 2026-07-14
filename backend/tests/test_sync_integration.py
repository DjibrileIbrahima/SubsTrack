"""End-to-end test of the detection → AI → upsert seam.

Unit tests mock each layer; this test runs real transactions through the full
pipeline with a fake AI (behaving like prod Groq: normalizing every cluster
label to the plain merchant name) and upserts into a real DB session — the
combination that produced the 2026-07-14 UniqueViolationError in production.
"""

import json
from datetime import date, timedelta

from sqlalchemy import select

from db.models import Subscription
from services.subscription_pipeline import run_subscription_pipeline
from services.subscription_sync import upsert_detected_subscriptions


def _txn(merchant, amount, days_back):
    return {
        "merchant_name": merchant,
        "name": merchant,
        "amount": amount,
        "date": (date.today() - timedelta(days=days_back)).isoformat(),
        "category": ["Software"],
    }


def _two_cluster_txns():
    """One merchant, two price tiers, three monthly charges each."""
    return (
        [_txn("TECTRA", 4.99, n) for n in (80, 50, 20)]
        + [_txn("TECTRA", 9.99, n) for n in (78, 48, 18)]
    )


def _label_collapsing_ai(system_prompt: str, user_prompt: str) -> str:
    """Fake Groq: always normalizes to the plain base name, like prod did."""
    return json.dumps({
        "is_subscription": True,
        "normalized_merchant": "Tectra",
        "category": "Software",
        "frequency": "monthly",
        "confidence": 0.9,
        "reason": "recurring software charge",
    })


class TestPipelineToUpsertIntegration:
    async def test_ai_collapsed_clusters_upsert_without_collision(self, db, test_user):
        """The prod scenario end to end: a pre-existing plain-labeled row plus
        two AI-renamed clusters must upsert cleanly with distinct labels."""
        db.add(Subscription(user_id=test_user.id, merchant="Tectra",
                            merchant_key="tectra", amount=4.99,
                            frequency="monthly", source="plaid"))
        await db.flush()

        detected = run_subscription_pipeline(_two_cluster_txns(), model_call=_label_collapsing_ai)

        # Sanity: both clusters survived detection via the AI path with
        # distinct, amount-suffixed labels and a shared identity key
        assert len(detected) == 2
        assert all(d["detection_method"] == "hybrid" for d in detected)
        assert all(d["merchant_key"] == "tectra" for d in detected)
        assert len({d["merchant"].lower() for d in detected}) == 2

        await upsert_detected_subscriptions(db, test_user.id, detected)

        rows = (await db.execute(
            select(Subscription).where(Subscription.merchant_key == "tectra")
        )).scalars().all()
        assert len(rows) == 2
        assert {float(r.amount) for r in rows} == {4.99, 9.99}
        assert len({r.merchant.lower() for r in rows}) == 2
        assert all(r.is_active for r in rows)

    async def test_second_sync_is_idempotent(self, db, test_user):
        """Re-running the identical pipeline+upsert updates in place: same row
        ids, no duplicates, no collisions."""
        detected = run_subscription_pipeline(_two_cluster_txns(), model_call=_label_collapsing_ai)
        await upsert_detected_subscriptions(db, test_user.id, detected)

        first_ids = {
            r.id for r in (await db.execute(
                select(Subscription).where(Subscription.merchant_key == "tectra")
            )).scalars()
        }
        assert len(first_ids) == 2

        detected_again = run_subscription_pipeline(_two_cluster_txns(), model_call=_label_collapsing_ai)
        await upsert_detected_subscriptions(db, test_user.id, detected_again)

        rows = (await db.execute(
            select(Subscription).where(Subscription.merchant_key == "tectra")
        )).scalars().all()
        assert {r.id for r in rows} == first_ids
