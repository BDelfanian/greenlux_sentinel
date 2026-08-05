"""ETL Agent — ingests Kaggle sources + GLEIF API, resolves schema drift, logs lineage.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Loads the Morningstar European Funds dataset into Postgres (Tier 1) and the
    ETF-holdings/company-ESG join into Cosmos DB (Tier 2) — see docs/DATA.md#two-tier-data-architecture.
    Calls the GLEIF MCP server to cross-check Luxembourg domicile claims against the
    live legal-entity register.

No human-in-the-loop gate — ingestion is additive/read-source, not a destructive write
against production data.

TODO(Phase 1):
    - Implement against confirmed columns from notebooks/01_data_profiling
    - Write lineage/row-count summary to the audit_log table on every run
"""

from __future__ import annotations


def run_ingestion() -> None:
    """Entry point for a full ETL run. Not yet implemented."""
    raise NotImplementedError("Phase 1 — see docs/ROADMAP.md")
