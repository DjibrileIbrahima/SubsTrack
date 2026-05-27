"""Unit tests for services/subscription_ai.py"""

import json
import pytest

from services.subscription_ai import (
    build_candidate_prompt,
    parse_ai_response,
    classify_candidate_with_ai,
    SYSTEM_PROMPT,
)


SAMPLE_CANDIDATE = {
    "merchant": "Spotify",
    "merchant_raw_samples": ["SPOTIFY USA", "SPOTIFY"],
    "amount": 9.99,
    "amounts": [9.99, 9.99, 9.99],
    "frequency": "monthly",
    "avg_interval_days": 30,
    "interval_days": [30, 30, 31],
    "category": "Music",
    "occurrences": 4,
    "confidence": 0.72,
    "reason": "Consistent monthly charges",
}


# ─── build_candidate_prompt ───────────────────────────────────────────────────

class TestBuildCandidatePrompt:
    def test_returns_valid_json_string(self):
        prompt = build_candidate_prompt(SAMPLE_CANDIDATE)
        # Must be parseable JSON
        data = json.loads(prompt)
        assert isinstance(data, dict)

    def test_includes_merchant_name(self):
        prompt = build_candidate_prompt(SAMPLE_CANDIDATE)
        assert "Spotify" in prompt

    def test_includes_amount(self):
        prompt = build_candidate_prompt(SAMPLE_CANDIDATE)
        data = json.loads(prompt)
        assert data["amount"] == 9.99

    def test_handles_missing_optional_fields(self):
        minimal = {"merchant": "Test", "amount": 5.0}
        prompt = build_candidate_prompt(minimal)
        data = json.loads(prompt)
        assert data["amounts"] == []
        assert data["interval_days"] == []


# ─── parse_ai_response ────────────────────────────────────────────────────────

class TestParseAiResponse:
    def test_parses_valid_response(self):
        raw = json.dumps({
            "is_subscription": True,
            "normalized_merchant": "Spotify",
            "category": "Music Streaming",
            "frequency": "monthly",
            "confidence": 0.91,
            "reason": "Regular monthly charge",
        })
        result = parse_ai_response(raw)
        assert result is not None
        assert result["is_subscription"] is True
        assert result["normalized_merchant"] == "Spotify"
        assert result["confidence"] == 0.91

    def test_returns_none_for_invalid_json(self):
        assert parse_ai_response("not json at all") is None

    def test_returns_none_for_json_array(self):
        # Unexpected shape (array instead of object)
        assert parse_ai_response("[1, 2, 3]") is None

    def test_defaults_for_missing_optional_fields(self):
        raw = json.dumps({"is_subscription": True, "confidence": 0.8})
        result = parse_ai_response(raw)
        assert result is not None
        assert result["normalized_merchant"] == ""
        assert result["category"] == "Unknown"
        assert result["frequency"] == "unknown"

    def test_is_subscription_false(self):
        raw = json.dumps({"is_subscription": False, "confidence": 0.1})
        result = parse_ai_response(raw)
        assert result["is_subscription"] is False

    def test_strips_whitespace_from_strings(self):
        raw = json.dumps({"normalized_merchant": "  Spotify  ", "confidence": 0.9})
        result = parse_ai_response(raw)
        assert result["normalized_merchant"] == "Spotify"


# ─── classify_candidate_with_ai ──────────────────────────────────────────────

class TestClassifyCandidateWithAi:
    def test_no_model_call_returns_fallback(self):
        result = classify_candidate_with_ai(SAMPLE_CANDIDATE, model_call=None)
        assert result["is_subscription"] is False
        assert result["confidence"] == 0.0
        assert "not configured" in result["reason"].lower()

    def test_with_valid_model_call(self):
        ai_json = json.dumps({
            "is_subscription": True,
            "normalized_merchant": "Spotify",
            "category": "Music",
            "frequency": "monthly",
            "confidence": 0.95,
            "reason": "Recurring digital subscription",
        })
        model_call = lambda system, user: ai_json
        result = classify_candidate_with_ai(SAMPLE_CANDIDATE, model_call=model_call)
        assert result["is_subscription"] is True
        assert result["normalized_merchant"] == "Spotify"
        assert result["confidence"] <= 0.99  # capped

    def test_with_model_call_returning_bad_json(self):
        model_call = lambda system, user: "```not valid json```"
        result = classify_candidate_with_ai(SAMPLE_CANDIDATE, model_call=model_call)
        assert result["is_subscription"] is False
        assert result["reason"] == "AI returned an unparseable response."

    def test_confidence_is_capped_at_0_99(self):
        ai_json = json.dumps({
            "is_subscription": True,
            "normalized_merchant": "Test",
            "confidence": 1.5,  # over 1.0
            "frequency": "monthly",
        })
        model_call = lambda system, user: ai_json
        result = classify_candidate_with_ai(SAMPLE_CANDIDATE, model_call=model_call)
        assert result["confidence"] <= 0.99

    def test_confidence_floor_is_0(self):
        ai_json = json.dumps({
            "is_subscription": False,
            "confidence": -0.5,  # below 0
            "frequency": "monthly",
        })
        model_call = lambda system, user: ai_json
        result = classify_candidate_with_ai(SAMPLE_CANDIDATE, model_call=model_call)
        assert result["confidence"] >= 0.0

    def test_invalid_frequency_normalized_to_unknown(self):
        ai_json = json.dumps({
            "is_subscription": True,
            "confidence": 0.8,
            "frequency": "semi-annual",  # not a valid value
        })
        model_call = lambda system, user: ai_json
        result = classify_candidate_with_ai(SAMPLE_CANDIDATE, model_call=model_call)
        assert result["frequency"] == "unknown"

    def test_system_prompt_is_non_empty(self):
        assert len(SYSTEM_PROMPT) > 50
        assert "JSON" in SYSTEM_PROMPT
