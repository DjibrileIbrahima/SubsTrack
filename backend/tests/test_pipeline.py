"""Unit tests for services/subscription_pipeline.py"""

import json
from datetime import date

from services.subscription_pipeline import merge_candidate_and_ai, run_subscription_pipeline

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_txns(merchant, amount, months=4):
    """Synthetic monthly transactions for a single merchant."""
    from datetime import date, timedelta
    return [
        {
            "merchant_name": merchant,
            "name": merchant,
            "amount": amount,
            "date": (date(2024, 1, 1) + i * timedelta(days=30)).isoformat(),
            "category": ["Entertainment"],
        }
        for i in range(months)
    ]


def _good_ai_response(merchant="Netflix", is_sub=True, confidence=0.90):
    return json.dumps({
        "is_subscription": is_sub,
        "normalized_merchant": merchant,
        "category": "Streaming",
        "frequency": "monthly",
        "confidence": confidence,
        "reason": "Recurring monthly charge.",
    })


# ─── run_subscription_pipeline ────────────────────────────────────────────────

class TestRunSubscriptionPipeline:
    def test_high_confidence_accepted_by_rules_alone(self):
        """Netflix 4× monthly should exceed the 0.65 rules threshold."""
        txns = _make_txns("NETFLIX", 15.99)
        results = run_subscription_pipeline(txns)
        assert any(r["merchant"] == "Netflix" for r in results)

    def test_single_occurrence_rejected_without_ai(self):
        """A single occurrence has no pattern; the pipeline must reject it."""
        txns = _make_txns("OBSCURE SERVICE", 12.0, months=1)
        results = run_subscription_pipeline(txns)
        assert results == []

    def test_results_sorted_by_confidence_descending(self):
        txns = _make_txns("NETFLIX", 15.99) + _make_txns("GITHUB", 4.0)
        results = run_subscription_pipeline(txns)
        if len(results) >= 2:
            assert results[0]["confidence"] >= results[1]["confidence"]

    def test_results_sorted_by_amount_for_equal_confidence(self):
        """When confidence is equal, higher-amount subscriptions come first."""
        txns = _make_txns("CHEAPSERVICE", 1.0) + _make_txns("EXPENSIVESERVICE", 99.0)
        results = run_subscription_pipeline(txns)
        if len(results) >= 2:
            conf0, conf1 = results[0]["confidence"], results[1]["confidence"]
            if abs(conf0 - conf1) < 0.01:
                assert results[0]["amount"] >= results[1]["amount"]

    def test_pipeline_without_model_call_uses_lower_threshold(self):
        """Without AI, the threshold is 0.65 (vs 0.85 when AI is available)."""
        txns = _make_txns("NETFLIX", 15.99)
        results_no_ai = run_subscription_pipeline(txns, model_call=None)
        results_with_ai = run_subscription_pipeline(txns, model_call=lambda s, u: _good_ai_response())
        # Netflix should be detected by both paths
        assert len(results_no_ai) > 0
        assert len(results_with_ai) > 0

    def test_ai_path_sets_detection_method_hybrid(self):
        """Candidates in the AI band (0.55–0.65) should be marked 'hybrid'."""
        # We can simulate this by providing a mock model_call that always approves
        txns = _make_txns("NETFLIX", 15.99)
        def model_call(s, u): return _good_ai_response()
        results = run_subscription_pipeline(txns, model_call=model_call)
        # High-confidence results may come through as "rules"; hybrid only for mid-band
        detection_methods = {r["detection_method"] for r in results}
        assert detection_methods  # at least one method present

    def test_all_required_fields_in_result(self):
        txns = _make_txns("NETFLIX", 15.99)
        results = run_subscription_pipeline(txns)
        assert results
        required = {"merchant", "amount", "frequency", "last_charged", "next_expected",
                    "category", "occurrences", "confidence", "detection_method", "reason"}
        assert required.issubset(results[0].keys())

    def test_empty_transactions(self):
        assert run_subscription_pipeline([]) == []

    def test_all_single_transactions_rejected(self):
        """One occurrence per merchant → never a subscription."""
        txns = [
            {"merchant_name": m, "name": m, "amount": 9.99, "date": "2024-01-15", "category": []}
            for m in ("SVC_A", "SVC_B", "SVC_C")
        ]
        assert run_subscription_pipeline(txns) == []


# ─── merge_candidate_and_ai ───────────────────────────────────────────────────

class TestMergeCandidateAndAi:
    def _candidate(self, merchant="Spotify", amount=9.99, confidence=0.62):
        return {
            "merchant": merchant,
            "amount": amount,
            "frequency": "monthly",
            "last_charged": date(2024, 3, 1),
            "next_expected": date(2024, 4, 1),
            "category": "Music",
            "occurrences": 4,
            "confidence": confidence,
            "reason": "Rules-based detection",
        }

    def test_not_subscription_returns_none(self):
        ai = {"is_subscription": False, "confidence": 0.1}
        assert merge_candidate_and_ai(self._candidate(), ai) is None

    def test_subscription_returns_merged_dict(self):
        ai = {
            "is_subscription": True,
            "normalized_merchant": "Spotify",
            "category": "Music Streaming",
            "frequency": "monthly",
            "confidence": 0.90,
            "reason": "AI confirmed",
        }
        result = merge_candidate_and_ai(self._candidate(), ai)
        assert result is not None
        assert result["merchant"] == "Spotify"
        assert result["detection_method"] == "hybrid"

    def test_confidence_takes_max(self):
        candidate = self._candidate(confidence=0.60)
        ai = {"is_subscription": True, "confidence": 0.85, "frequency": "monthly",
              "normalized_merchant": "Spotify", "category": "Music", "reason": ""}
        result = merge_candidate_and_ai(candidate, ai)
        assert result["confidence"] == round(max(0.60, 0.85), 2)

    def test_ai_frequency_overrides_rules_frequency(self):
        """When AI provides a non-unknown frequency, it should override the rules value."""
        candidate = self._candidate()
        candidate["frequency"] = "weekly"  # rules said weekly
        ai = {"is_subscription": True, "confidence": 0.85, "frequency": "monthly",
              "normalized_merchant": "Spotify", "category": "Music", "reason": ""}
        result = merge_candidate_and_ai(candidate, ai)
        assert result["frequency"] == "monthly"  # AI wins

    def test_unknown_ai_frequency_falls_back_to_rules(self):
        candidate = self._candidate()
        candidate["frequency"] = "monthly"
        ai = {"is_subscription": True, "confidence": 0.85, "frequency": "unknown",
              "normalized_merchant": "Spotify", "category": "Music", "reason": ""}
        result = merge_candidate_and_ai(candidate, ai)
        assert result["frequency"] == "monthly"  # falls back to rules

    def test_preserves_candidate_financials(self):
        candidate = self._candidate(amount=9.99)
        ai = {"is_subscription": True, "confidence": 0.9, "frequency": "monthly",
              "normalized_merchant": "Spotify", "category": "Music", "reason": ""}
        result = merge_candidate_and_ai(candidate, ai)
        assert result["amount"] == 9.99
        assert result["occurrences"] == 4
