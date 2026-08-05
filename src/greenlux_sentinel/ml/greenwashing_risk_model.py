"""Greenwashing Risk Score model.

risk_score(fund) = f(claimed_sustainability_rating, holdings_implied_esg_profile)

See docs/DATA.md#ground-truth-methodology for why this is the ground truth (no free
dataset confirmed to carry a legal SFDR Article 6/8/9 label) and why this must always be
presented as a data-driven proxy indicator, never a compliance finding.

Consumed by agents/risk_agent.py — this module holds the actual scoring logic so it can
be unit-tested independently of the agent/tool-calling layer.

TODO(Phase 2):
    - Start with a simple, explainable weighted-gap score (not a black-box model) so the
      risk agent can produce a holdings-level explanation, not just a number
    - Only consider a learned model once the simple version has a labeled eval set
"""

from __future__ import annotations


def compute_risk_score(claimed_rating: float, holdings_esg_scores: list[float]) -> dict:
    """Return {"risk_score": float, "gap": float, "driving_holdings": list}. Not yet implemented."""
    raise NotImplementedError("Phase 2 — see docs/ROADMAP.md")
