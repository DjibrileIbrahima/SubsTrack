from collections import defaultdict
from datetime import datetime, timedelta, date


def detect_subscriptions(transactions: list[dict]) -> list[dict]:
    merchant_groups = defaultdict(list)

    for txn in transactions:
        name = txn.get("merchant_name") or txn.get("name", "Unknown")
        merchant_groups[name].append(txn)

    subscriptions = []

    for merchant, txns in merchant_groups.items():
        if len(txns) < 2:
            continue

        txns.sort(key=lambda x: x["date"])

        amounts = [abs(t["amount"]) for t in txns]
        avg_amount = sum(amounts) / len(amounts)

        consistent = all(abs(a - avg_amount) / avg_amount < 0.05 for a in amounts)
        if not consistent:
            continue

        dates = [datetime.strptime(t["date"], "%Y-%m-%d").date() for t in txns]
        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates) - 1)]
        avg_interval = sum(intervals) / len(intervals)

        if 25 <= avg_interval <= 35:
            frequency = "monthly"
        elif 6 <= avg_interval <= 8:
            frequency = "weekly"
        elif 85 <= avg_interval <= 95:
            frequency = "quarterly"
        elif 350 <= avg_interval <= 380:
            frequency = "yearly"
        else:
            frequency = f"every ~{int(avg_interval)} days"

        last_date = dates[-1]
        next_date = last_date + timedelta(days=avg_interval)

        subscriptions.append({
            "merchant": merchant,
            "amount": round(avg_amount, 2),
            "frequency": frequency,
            "last_charged": last_date,        # date object, not string
            "next_expected": next_date.date() if hasattr(next_date, 'date') else next_date,
            "category": txns[-1].get("category", ["Unknown"])[0] if txns[-1].get("category") else "Unknown",
            "occurrences": len(txns),
        })

    subscriptions.sort(key=lambda x: x["amount"], reverse=True)
    return subscriptions