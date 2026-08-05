"""Report Agent — compiles a final, cited, multilingual (EN/FR/DE) fund report.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Pulls the greenwashing risk score + explanation (risk_agent) and any ad-hoc SQL
    findings (sql_agent), drafts a report in English, French, and German (see
    docs/DATA.md#multilingual-layer — this text is agent-generated, not sourced
    pre-translated data), and attaches the methodology caveat from
    docs/DATA.md#ground-truth-methodology.

    Every numeric claim in the draft must trace back to a tool call result from this run
    (docs/RESPONSIBLE_AI.md#principles, guardrail #2) — enforced by guardrails/validators.py.

HUMAN-IN-THE-LOOP GATE (docs/RESPONSIBLE_AI.md#human-in-the-loop-gates):
    The draft is not exposed as final output until a human explicitly approves it.

Persistence: one row per (report_id, language) in the `fund_reports` table
(db/schema.sql) — draft_report() inserts rows with status='draft'; publish_report()
flips matching rows to status='published' after human approval. `report_id` is shared
across the three language rows of one report.

TODO(Phase 4):
    - Draft-generation prompt per language
    - Wire the tool-sourced-numbers validator before returning a draft
    - Implement the approve/publish state transition + audit log entry
"""

from __future__ import annotations


def draft_report(fund_id: str) -> dict:
    """Insert draft rows into fund_reports; return {"report_id": str, "en": str, "fr": str,
    "de": str, "citations": list}. Not yet implemented."""
    raise NotImplementedError("Phase 4 — see docs/ROADMAP.md")


def publish_report(report_id: str, approved_by: str) -> None:
    """Set fund_reports.status='published' for all languages of report_id, after human
    approval. Not yet implemented."""
    raise NotImplementedError("Phase 4 — see docs/ROADMAP.md")
