from collections import defaultdict
from datetime import datetime, timedelta, date
import re


SUBSCRIPTION_KEYWORDS = {
    "NETFLIX",
    "SPOTIFY",
    "HULU",
    "DISNEY",
    "DISNEY+",
    "YOUTUBE",
    "APPLE",
    "APPLE.COM",
    "GOOGLE",
    "AMAZON PRIME",
    "PRIME VIDEO",
    "CHATGPT",
    "OPENAI",
    "MICROSOFT",
    "ADOBE",
    "CANVA",
    "DROPBOX",
    "ICLOUD",
    "NOTION",
    "SLACK",
    "CAPCUT",
    "HBOMAX",
    "MAX",
    "PEACOCK",
    "PARAMOUNT",
    "CRUNCHYROLL",
    "TIDAL",
    "AUDIBLE",
    "DUOLINGO",
    "GITHUB",
    "FIGMA",
}


NON_SUBSCRIPTION_HINTS = {
    "RENT",
    "MORTGAGE",
    "PAYMENT",
    "CREDIT CARD",
    "AUTOPAY",
    "LOAN",
    "INSURANCE",
    "UTILITY",
    "ELECTRIC",
    "WATER",
    "GAS",
    "TRANSFER",
    "VENMO",
    "ZELLE",
    "CASH APP",
    "PAYROLL",
    "ATM",
}


def normalize_merchant(txn: dict) -> str:
    raw = (txn.get("merchant_name") or txn.get("name") or "Unknown").strip().upper()

    raw = re.sub(r"[*#0-9]+", " ", raw)
    raw = re.sub(r"\b(PENDING|DEBIT|CARD|PURCHASE|POS|ACH|CHECKCARD|ONLINE|PMT|SQ)\b", " ", raw)
    raw = re.sub(r"\s+", " ", raw).strip()

    alias_rules = [
        ("SPOTIFY", "SPOTIFY"),
        ("NETFLIX", "NETFLIX"),
        ("HULU", "HULU"),
        ("DISNEY", "DISNEY+"),
        ("YOUTUBE", "YOUTUBE"),
        ("APPLE", "APPLE"),
        ("GOOGLE", "GOOGLE"),
        ("AMAZON PRIME", "AMAZON PRIME"),
        ("PRIME VIDEO", "AMAZON PRIME"),
        ("OPENAI", "OPENAI"),
        ("CHATGPT", "OPENAI"),
        ("ADOBE", "ADOBE"),
        ("DROPBOX", "DROPBOX"),
        ("NOTION", "NOTION"),
        ("CANVA", "CANVA"),
        ("FIGMA", "FIGMA"),
        ("GITHUB", "GITHUB"),
    ]
    for needle, canonical in alias_rules:
        if needle in raw:
            return canonical

    return raw


def has_non_subscription_hint(merchant: str) -> bool:
    return any(hint in merchant for hint in NON_SUBSCRIPTION_HINTS)


def has_subscription_keyword(merchant: str) -> bool:
    return any(keyword in merchant for keyword in SUBSCRIPTION_KEYWORDS)


def amount_consistency_score(amounts: list[float]) -> float:
    if len(amounts) < 2:
        return 0.0
    avg_amount = sum(amounts) / len(amounts)
    if avg_amount <= 0:
        return 0.0

    max_pct_diff = max(abs(a - avg_amount) / avg_amount for a in amounts)
    if max_pct_diff <= 0.05:
        return 1.0
    if max_pct_diff <= 0.10:
        return 0.9
    if max_pct_diff <= 0.20:
        return 0.75
    if max_pct_diff <= 0.30:
        return 0.5
    return 0.0


def interval_consistency_score(intervals: list[int]) -> float:
    if not intervals:
        return 0.0
    avg_interval = sum(intervals) / len(intervals)
    max_deviation = max(abs(i - avg_interval) for i in intervals)

    if max_deviation <= 2:
        return 1.0
    if max_deviation <= 4:
        return 0.85
    if max_deviation <= 7:
        return 0.65
    if max_deviation <= 10:
        return 0.45
    return 0.0


def infer_frequency(avg_interval: float) -> str | None:
    if 25 <= avg_interval <= 35:
        return "monthly"
    if 6 <= avg_interval <= 8:
        return "weekly"
    if 12 <= avg_interval <= 16:
        return "biweekly"
    if 85 <= avg_interval <= 98:
        return "quarterly"
    if 350 <= avg_interval <= 380:
        return "yearly"
    return None


def build_candidate(merchant: str, txns: list[dict]) -> dict | None:
    if len(txns) < 2:
        return None

    txns = sorted(txns, key=lambda x: x["date"])
    amounts = [abs(float(t["amount"])) for t in txns if t.get("amount") is not None]
    if len(amounts) < 2:
        return None

    dates = [datetime.strptime(t["date"], "%Y-%m-%d").date() for t in txns]
    intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    if not intervals:
        return None

    avg_interval = sum(intervals) / len(intervals)
    frequency = infer_frequency(avg_interval)
    if not frequency:
        return None

    avg_amount = sum(amounts) / len(amounts)
    last_date = dates[-1]
    next_date = last_date + timedelta(days=round(avg_interval))

    amount_score = amount_consistency_score(amounts)
    interval_score = interval_consistency_score(intervals)
    occurrence_score = min(len(txns) / 4, 1.0)

    keyword_bonus = 0.1 if has_subscription_keyword(merchant) else 0.0
    penalty = 0.25 if has_non_subscription_hint(merchant) else 0.0

    confidence = (
        (0.4 * amount_score) +
        (0.35 * interval_score) +
        (0.15 * occurrence_score) +
        keyword_bonus -
        penalty
    )
    confidence = max(0.0, min(confidence, 0.99))

    category = txns[-1].get("category", ["Unknown"])[0] if txns[-1].get("category") else "Unknown"

    return {
        "merchant": merchant.title(),
        "merchant_raw_samples": list(dict.fromkeys(
            (t.get("merchant_name") or t.get("name") or "Unknown") for t in txns
        ))[:5],
        "amount": round(avg_amount, 2),
        "amounts": [round(a, 2) for a in amounts[-6:]],
        "frequency": frequency,
        "interval_days": intervals[-6:],
        "avg_interval_days": round(avg_interval, 1),
        "last_charged": last_date,
        "next_expected": next_date,
        "category": category,
        "occurrences": len(txns),
        "confidence": round(confidence, 2),
        "detection_method": "rules",
        "reason": (
            f"Detected {len(txns)} recurring charges about every "
            f"{round(avg_interval)} days with average amount ${avg_amount:.2f}."
        ),
    }


def detect_subscription_candidates(transactions: list[dict]) -> list[dict]:
    merchant_groups = defaultdict(list)

    for txn in transactions:
        amount = txn.get("amount", 0)
        if amount is None or amount <= 0:
            continue

        merchant = normalize_merchant(txn)
        merchant_groups[merchant].append(txn)

    candidates = []
    for merchant, txns in merchant_groups.items():
        candidate = build_candidate(merchant, txns)
        if candidate:
            candidates.append(candidate)

    candidates.sort(key=lambda x: (-x["confidence"], -x["amount"]))
    return candidates


def detect_subscriptions(transactions: list[dict], min_confidence: float = 0.75) -> list[dict]:
    candidates = detect_subscription_candidates(transactions)
    accepted = [c for c in candidates if c["confidence"] >= min_confidence]

    return [
        {
            "merchant": c["merchant"],
            "amount": c["amount"],
            "frequency": c["frequency"],
            "last_charged": c["last_charged"],
            "next_expected": c["next_expected"],
            "category": c["category"],
            "occurrences": c["occurrences"],
            "confidence": c["confidence"],
            "detection_method": c["detection_method"],
            "reason": c["reason"],
            "source": "plaid",
        }
        for c in accepted
    ]