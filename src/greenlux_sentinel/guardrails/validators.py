"""Guardrail validators (docs/RESPONSIBLE_AI.md#principles).

Two responsibilities, kept separate so each is independently testable:

    1. tool_sourced_numbers(draft_text, trace_tool_results) -> bool
       Every number in generated report/dashboard text must appear among the values
       actually returned by tool calls in the same run's trace. Used to gate the Report
       Agent and Dashboard Agent before their output is shown.

    2. redact_pii(text) -> str
       Defensive redaction pass on any ingested free-text field, even though current
       datasets are company/fund-level, not individual-level.

TODO(Phase 2):
    - Implement numeric extraction (regex/NER) + trace cross-check for (1)
    - Implement (2), likely via a regex/Presidio-style pass
"""

from __future__ import annotations


def tool_sourced_numbers(draft_text: str, trace_tool_results: list[float]) -> bool:
    """Return True if every number in draft_text traces back to trace_tool_results. Not yet implemented."""
    raise NotImplementedError("Phase 2 — see docs/ROADMAP.md")


def redact_pii(text: str) -> str:
    """Return text with any PII redacted. Not yet implemented."""
    raise NotImplementedError("Phase 2 — see docs/ROADMAP.md")
