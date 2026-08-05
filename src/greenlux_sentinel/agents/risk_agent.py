"""Greenwashing-Risk Agent — computes and explains the per-fund Greenwashing Risk Score.

Responsibility (docs/ARCHITECTURE.md#agent-graph-langgraph):
    Reads Tier 2 data (ETF holdings + company ESG ratings from Cosmos DB) and the fund's
    own Morningstar Sustainability Rating (Postgres), computes the consistency gap, and
    produces an explanation of which holdings drive the score.

    IMPORTANT: this score is a data-driven proxy indicator, not a determination of legal
    SFDR non-compliance. See docs/DATA.md#ground-truth-methodology — do not present it as
    a compliance finding anywhere downstream (dashboard, report).

Read-only — no human-in-the-loop gate.

TODO(Phase 2):
    - Implement risk_score(fund) = f(claimed_rating, holdings_implied_esg) per docs/DATA.md
    - Wire the ML model in ml/greenwashing_risk_model.py
    - Write result back to a Postgres table the BI/report layer can read
"""

from __future__ import annotations


def score_fund(fund_id: str) -> dict:
    """Return {"risk_score": float, "explanation": str, "caveat": str}. Not yet implemented."""
    raise NotImplementedError("Phase 2 — see docs/ROADMAP.md")
