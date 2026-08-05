"""Dashboard Agent — turns an analyst question into a live Power BI update.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Composes a DAX/Power BI query from the analyst's request and calls the Power BI MCP
    server (run_dax_query / refresh_dataset) so the dashboard reflects the question just
    asked — this is the "dynamic, not static" requirement: no fixed pre-built report.

Read-only against the dataset (a refresh, not a schema/report-definition change) — no
human-in-the-loop gate.

TODO(Phase 4):
    - Implement DAX templates in bi/dax_templates.py
    - Call Power BI MCP server once it exists (Phase 3)
"""

from __future__ import annotations


def update_dashboard(question: str) -> dict:
    """Return {"dax": str, "dataset_id": str}. Not yet implemented."""
    raise NotImplementedError("Phase 4 — see docs/ROADMAP.md")
