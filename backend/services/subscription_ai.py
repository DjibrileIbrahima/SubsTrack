import json
from typing import Any


SYSTEM_PROMPT = """
You classify recurring bank charges.

Return strict JSON only with this shape:
{
  "is_subscription": true,
  "normalized_merchant": "Spotify",
  "category": "Music Streaming",
  "frequency": "monthly",
  "confidence": 0.91,
  "reason": "Recurring digital service charge with stable monthly cadence."
}

Rules:
- confidence must be a number from 0 to 1
- frequency must be one of: weekly, biweekly, monthly, quarterly, yearly, unknown
- if not likely a subscription, set is_subscription to false
- prefer concise merchant names
- do not include markdown
""".strip()


def build_candidate_prompt(candidate: dict) -> str:
    payload = {
        "merchant": candidate.get("merchant"),
        "merchant_raw_samples": candidate.get("merchant_raw_samples", []),
        "amount": candidate.get("amount"),
        "amounts": candidate.get("amounts", []),
        "frequency_hint": candidate.get("frequency"),
        "avg_interval_days": candidate.get("avg_interval_days"),
        "interval_days": candidate.get("interval_days", []),
        "category_hint": candidate.get("category"),
        "occurrences": candidate.get("occurrences"),
        "rules_confidence": candidate.get("confidence"),
        "rules_reason": candidate.get("reason"),
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_ai_response(text: str) -> dict[str, Any]:
    data = json.loads(text)

    return {
        "is_subscription": bool(data.get("is_subscription", False)),
        "normalized_merchant": str(data.get("normalized_merchant") or "").strip(),
        "category": str(data.get("category") or "Unknown").strip(),
        "frequency": str(data.get("frequency") or "unknown").strip().lower(),
        "confidence": float(data.get("confidence", 0)),
        "reason": str(data.get("reason") or "").strip(),
    }


def classify_candidate_with_ai(candidate: dict, model_call=None) -> dict:
    """
    model_call should be a callable like:
        model_call(system_prompt: str, user_prompt: str) -> str

    Return shape:
    {
      "is_subscription": bool,
      "normalized_merchant": str,
      "category": str,
      "frequency": str,
      "confidence": float,
      "reason": str,
    }
    """
    if model_call is None:
        # Safe fallback for now until you wire a real model
        return {
            "is_subscription": False,
            "normalized_merchant": candidate.get("merchant", ""),
            "category": candidate.get("category", "Unknown"),
            "frequency": candidate.get("frequency", "unknown"),
            "confidence": 0.0,
            "reason": "AI model not configured.",
        }

    raw = model_call(SYSTEM_PROMPT, build_candidate_prompt(candidate))
    parsed = parse_ai_response(raw)

    parsed["confidence"] = max(0.0, min(parsed["confidence"], 0.99))
    if parsed["frequency"] not in {"weekly", "biweekly", "monthly", "quarterly", "yearly", "unknown"}:
        parsed["frequency"] = "unknown"

    return parsed