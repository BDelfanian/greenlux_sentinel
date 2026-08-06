"""Unit tests for guardrails/validators.py: pure text-processing logic, no DB/LLM needed."""

from __future__ import annotations

from greenlux_sentinel.guardrails import validators


class TestToolSourcedNumbers:
    def test_all_numbers_sourced_returns_true(self):
        text = "The fund scores 53.03, versus a claim of 5."
        assert validators.tool_sourced_numbers(text, [53.03, 5.0]) is True

    def test_unsourced_number_returns_false(self):
        text = "The fund scores 53.03."
        assert validators.tool_sourced_numbers(text, [12.0]) is False

    def test_rounded_number_within_tolerance_passes(self):
        text = "The fund scores 53."
        assert validators.tool_sourced_numbers(text, [53.001]) is True

    def test_no_numbers_in_text_trivially_passes(self):
        assert validators.tool_sourced_numbers("No numeric claims here.", []) is True

    def test_thousands_separator_is_parsed(self):
        text = "Total net assets: 1,536.00"
        assert validators.tool_sourced_numbers(text, [1536.0]) is True


class TestRedactPii:
    def test_redacts_email(self):
        assert validators.redact_pii("contact jane@example.com") == "contact [REDACTED]"

    def test_redacts_long_phone_like_sequence(self):
        assert validators.redact_pii("call +352-621-123-456") == "call [REDACTED]"

    def test_leaves_short_report_numbers_untouched(self):
        text = "Risk score: 53.03, rating: 5, category allocation 12.3%"
        assert validators.redact_pii(text) == text

    def test_leaves_plain_text_untouched(self):
        text = "This fund is domiciled in Luxembourg."
        assert validators.redact_pii(text) == text
