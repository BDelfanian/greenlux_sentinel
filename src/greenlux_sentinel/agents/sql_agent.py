"""NL2SQL Agent — translates an analyst's natural-language question into SQL.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Generates SQL against the Tier 1 Postgres fund schema, executes it read-only via the
    Postgres MCP server's run_readonly_query tool, and returns tabular results plus the
    SQL used (so the report/dashboard agents can cite it and guardrails can verify
    numeric claims trace back to this call).

Read-only — no human-in-the-loop gate. Must never execute DDL; that's the
query-optimizer agent's job, and it IS gated.

TODO(Phase 2):
    - Prompt template constrained to the confirmed schema in db/schema.sql
    - Reject/flag any generated statement that isn't a SELECT
"""

from __future__ import annotations


def ask(question: str) -> dict:
    """Return {"sql": str, "rows": list}. Not yet implemented."""
    raise NotImplementedError("Phase 2 — see docs/ROADMAP.md")
