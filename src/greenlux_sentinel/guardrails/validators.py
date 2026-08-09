"""Guardrail validators (docs/RESPONSIBLE_AI.md#principles).

Two responsibilities, kept separate so each is independently testable:

    1. tool_sourced_numbers(draft_text, trace_tool_results) -> bool
       Every number in generated report/dashboard text must appear among the values
       actually returned by tool calls in the same run's trace. Used to gate the Report
       Agent and Dashboard Agent before their output is shown.

    2. redact_pii(text) -> str
       Defensive redaction pass on any ingested free-text field, even though current
       datasets are company/fund-level, not individual-level.
"""

from __future__ import annotations

import re

# Matches ints/decimals, with optional thousands separators (e.g. "1,536" or "53.03").
_NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
# A tool-returned float may be re-rendered with fewer decimal places in generated text
# (e.g. 53.0 -> "53"); tolerate that without treating it as an unsourced number.
_ROUNDING_TOLERANCE = 0.01

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Deliberately conservative: current datasets are company/fund-level with no phone numbers, so
# this only needs to catch an obvious phone-shaped string -- digit groups joined by phone-style
# separators (dash/dot/space), e.g. "+352-621-123-456" -- without colliding with the short
# numeric citations (risk scores, ratings, percentages) report text is expected to contain, or
# with large *unformatted* financial figures (fund AUM, share counts) that are common in this
# domain and would otherwise look "phone-shaped" to a bare 9+-digit-run check.
_PHONE_RE = re.compile(r"(?<!\d)\+?\d{1,4}(?:[-.\s]\d{2,4}){2,}(?!\d)")


def extract_numbers(text: str) -> list[float]:
    """Return every number found in text, in the same format _NUMBER_RE recognizes. Used both to
    check draft text (tool_sourced_numbers) and to register numbers already present in
    tool-sourced prose (e.g. a risk explanation string) as legitimately citable."""
    return [float(match.group(0).replace(",", "")) for match in _NUMBER_RE.finditer(text)]


def tool_sourced_numbers(draft_text: str, trace_tool_results: list[float]) -> bool:
    """Return True if every number in draft_text traces back to trace_tool_results (within a
    small rounding tolerance)."""
    allowed = [float(v) for v in trace_tool_results]
    for value in extract_numbers(draft_text):
        if not any(abs(value - a) <= _ROUNDING_TOLERANCE for a in allowed):
            return False
    return True


def redact_pii(text: str) -> str:
    """Return text with any PII redacted."""
    text = _EMAIL_RE.sub("[REDACTED]", text)
    text = _PHONE_RE.sub("[REDACTED]", text)
    return text
