"""Tests for services/subscription_detector.py"""
import pytest
from datetime import date, timedelta
from services.subscription_detector import (
    normalize_merchant,
    amount_consistency_score,
    interval_consistency_score,
    infer_frequency,
    detect_subscriptions,
    detect_subscription_candidates,
    has_non_subscription_hint,
    has_subscription_keyword,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_txns(merchant_name, amount, start, interval_days, count):
    """Generate a list of synthetic transactions for a single merchant."""
    txns = []
    for i in range(count):
        d = start + timedelta(days=i * interval_days)
        txns.append({
            "merchant_name": merchant_name,
            "name": merchant_name,
            "amount": amount,
            "date": d.isoformat(),
            "category": ["Entertainment"],
        })
    return txns


# ---------------------------------------------------------------------------
# normalize_merchant
# ---------------------------------------------------------------------------

class TestNormalizeMerchant:
    def test_spotify_alias(self):
        assert normalize_merchant({"merchant_name": "SPOTIFY USA", "name": "SPOTIFY USA"}) == "SPOTIFY"

    def test_chatgpt_maps_to_openai(self):
        assert normalize_merchant({"merchant_name": "CHATGPT SUBSCRIPTION", "name": "CHATGPT SUBSCRIPTION"}) == "OPENAI"

    def test_prime_video_maps_to_amazon_prime(self):
        assert normalize_merchant({"merchant_name": "PRIME VIDEO", "name": "PRIME VIDEO"}) == "AMAZON PRIME"

    def test_disney_maps_to_disney_plus(self):
        assert normalize_merchant({"merchant_name": "DISNEY PLUS", "name": "DISNEY PLUS"}) == "DISNEY+"

    def test_strips_numbers_and_symbols(self):
        result = normalize_merchant({"merchant_name": "SOME*SERVICE#1234", "name": "SOME*SERVICE#1234"})
        assert "1234" not in result and "*" not in result and "#" not in result

    def test_strips_noise_words(self):
        assert normalize_merchant({"merchant_name": "ACH DEBIT ONLINE NETFLIX", "name": "ACH DEBIT ONLINE NETFLIX"}) == "NETFLIX"

    def test_falls_back_to_name_if_no_merchant_name(self):
        assert normalize_merchant({"merchant_name": None, "name": "SPOTIFY"}) == "SPOTIFY"

    def test_unknown_fallback(self):
        assert normalize_merchant({"merchant_name": None, "name": None}) == "UNKNOWN"


# ---------------------------------------------------------------------------
# amount_consistency_score
# ---------------------------------------------------------------------------

class TestAmountConsistencyScore:
    def test_identical_amounts_score_1(self):
        assert amount_consistency_score([9.99, 9.99, 9.99]) == 1.0

    def test_within_5_pct_score_1(self):
        assert amount_consistency_score([10.0, 10.4, 9.7]) == 1.0

    def test_within_10_pct_score_high(self):
        assert amount_consistency_score([10.0, 10.9]) == 0.9

    def test_large_variance_score_zero(self):
        assert amount_consistency_score([10.0, 50.0]) == 0.0

    def test_single_amount_returns_zero(self):
        assert amount_consistency_score([9.99]) == 0.0

    def test_zero_avg_returns_zero(self):
        assert amount_consistency_score([0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# interval_consistency_score
# ---------------------------------------------------------------------------

class TestIntervalConsistencyScore:
    def test_perfect_intervals_score_1(self):
        assert interval_consistency_score([30, 30, 30]) == 1.0

    def test_small_deviation_score_high(self):
        assert interval_consistency_score([28, 30, 32]) == 1.0  # max deviation = 2

    def test_moderate_deviation(self):
        assert interval_consistency_score([26, 30, 34]) == 0.85  # max deviation = 4

    def test_large_deviation_score_zero(self):
        assert interval_consistency_score([15, 30, 60]) == 0.0  # max deviation = 22.5

    def test_empty_intervals_returns_zero(self):
        assert interval_consistency_score([]) == 0.0


# ---------------------------------------------------------------------------
# infer_frequency
# ---------------------------------------------------------------------------

class TestInferFrequency:
    def test_monthly(self):           assert infer_frequency(30) == "monthly"
    def test_monthly_low_bound(self): assert infer_frequency(25) == "monthly"
    def test_monthly_high_bound(self):assert infer_frequency(35) == "monthly"
    def test_weekly(self):            assert infer_frequency(7) == "weekly"
    def test_biweekly(self):          assert infer_frequency(14) == "biweekly"
    def test_quarterly(self):         assert infer_frequency(91) == "quarterly"
    def test_yearly(self):            assert infer_frequency(365) == "yearly"
    def test_unknown_returns_none(self): assert infer_frequency(45) is None
    def test_zero_returns_none(self): assert infer_frequency(0) is None


# ---------------------------------------------------------------------------
# Hints / keywords
# ---------------------------------------------------------------------------

class TestHints:
    def test_rent_is_non_sub_hint(self):    assert has_non_subscription_hint("RENT PAYMENT") is True
    def test_netflix_not_non_sub_hint(self):assert has_non_subscription_hint("NETFLIX") is False
    def test_netflix_is_keyword(self):      assert has_subscription_keyword("NETFLIX") is True
    def test_grocery_not_keyword(self):     assert has_subscription_keyword("WHOLE FOODS MARKET") is False


# ---------------------------------------------------------------------------
# detect_subscriptions — end-to-end
# ---------------------------------------------------------------------------

class TestDetectSubscriptions:
    def test_detects_monthly_subscription(self):
        txns = make_txns("NETFLIX", 15.99, date(2024, 1, 1), 30, 4)
        results = detect_subscriptions(txns)
        assert len(results) == 1
        r = results[0]
        assert r["merchant"] == "Netflix"
        assert r["frequency"] == "monthly"
        assert r["amount"] == 15.99
        assert r["source"] == "plaid"

    def test_detects_yearly_subscription(self):
        txns = make_txns("AMAZON PRIME", 139.0, date(2022, 1, 1), 365, 3)
        results = detect_subscriptions(txns)
        assert len(results) == 1
        assert results[0]["frequency"] == "yearly"

    def test_rejects_single_transaction(self):
        txns = make_txns("SPOTIFY", 9.99, date(2024, 1, 1), 30, 1)
        assert detect_subscriptions(txns) == []

    def test_rejects_inconsistent_amounts(self):
        txns = [
            {"merchant_name": "RANDOM", "name": "RANDOM", "amount": 5.0,  "date": "2024-01-01", "category": []},
            {"merchant_name": "RANDOM", "name": "RANDOM", "amount": 95.0, "date": "2024-02-01", "category": []},
            {"merchant_name": "RANDOM", "name": "RANDOM", "amount": 50.0, "date": "2024-03-01", "category": []},
        ]
        assert detect_subscriptions(txns) == []

    def test_rejects_non_subscription_hints(self):
        txns = make_txns("RENT PAYMENT", 1200.0, date(2024, 1, 1), 30, 4)
        assert detect_subscriptions(txns) == []

    def test_ignores_negative_amounts(self):
        txns = make_txns("SPOTIFY", -9.99, date(2024, 1, 1), 30, 4)
        assert detect_subscriptions(txns) == []

    def test_mixed_merchants_detected_separately(self):
        txns = (
            make_txns("NETFLIX", 15.99, date(2024, 1, 1), 30, 4) +
            make_txns("SPOTIFY", 9.99,  date(2024, 1, 3), 30, 4)
        )
        results = detect_subscriptions(txns)
        merchants = {r["merchant"] for r in results}
        assert "Netflix" in merchants
        assert "Spotify" in merchants

    def test_result_has_all_required_fields(self):
        txns = make_txns("GITHUB", 4.0, date(2024, 1, 1), 30, 4)
        results = detect_subscriptions(txns)
        assert len(results) == 1
        required = {"merchant", "amount", "frequency", "last_charged", "next_expected",
                    "category", "occurrences", "confidence", "detection_method", "reason", "source"}
        assert required.issubset(results[0].keys())

    def test_confidence_threshold_excludes_weak_candidates(self):
        txns = make_txns("OBSCURE SERVICE", 12.0, date(2024, 1, 1), 30, 2)
        assert detect_subscriptions(txns, min_confidence=0.99) == []

    def test_next_expected_is_after_last_charged(self):
        txns = make_txns("NOTION", 8.0, date(2024, 1, 1), 30, 4)
        results = detect_subscriptions(txns)
        assert len(results) == 1
        assert results[0]["next_expected"] > results[0]["last_charged"]
