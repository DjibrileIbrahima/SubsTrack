from services.subscription_detector import detect_subscription_candidates
from services.subscription_ai import classify_candidate_with_ai


def merge_candidate_and_ai(candidate: dict, ai_result: dict) -> dict | None:
    if not ai_result.get("is_subscription"):
        return None

    confidence = max(candidate.get("confidence", 0), ai_result.get("confidence", 0))

    return {
        "merchant": ai_result.get("normalized_merchant") or candidate["merchant"],
        "amount": candidate["amount"],
        "frequency": ai_result.get("frequency") if ai_result.get("frequency") != "unknown" else candidate["frequency"],
        "last_charged": candidate["last_charged"],
        "next_expected": candidate["next_expected"],
        "category": ai_result.get("category") or candidate["category"],
        "occurrences": candidate["occurrences"],
        "confidence": round(confidence, 2),
        "detection_method": "hybrid",
        "reason": ai_result.get("reason") or candidate.get("reason"),
    }


def run_subscription_pipeline(transactions: list[dict], model_call=None) -> list[dict]:
    candidates = detect_subscription_candidates(transactions)

    accepted = []
    for candidate in candidates:
        rules_conf = candidate["confidence"]

        if rules_conf >= 0.85:
            accepted.append({
                "merchant": candidate["merchant"],
                "amount": candidate["amount"],
                "frequency": candidate["frequency"],
                "last_charged": candidate["last_charged"],
                "next_expected": candidate["next_expected"],
                "category": candidate["category"],
                "occurrences": candidate["occurrences"],
                "confidence": candidate["confidence"],
                "detection_method": "rules",
                "reason": candidate["reason"],
            })
            continue

        if rules_conf < 0.55:
            continue

        ai_result = classify_candidate_with_ai(candidate, model_call=model_call)
        merged = merge_candidate_and_ai(candidate, ai_result)
        if merged and merged["confidence"] >= 0.70:
            accepted.append(merged)

    accepted.sort(key=lambda x: (-x["confidence"], -x["amount"]))
    return accepted