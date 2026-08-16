"""DAX query templates, parameterized and filled in by the Dashboard Agent at request time.

This is what makes the dashboard "dynamic, not static" (docs/REQUIREMENTS_TRACEABILITY.md,
row 7) — the agent picks/parameterizes a template based on the analyst's NL question rather
than the dashboard shipping with a fixed, pre-built report.

Real DAX against the real published Power BI push dataset (`Funds` + `FundRiskScores` tables,
one relationship on `fund_id` — see docs/PROGRESS_LOG.md's Phase 4 entry), not a placeholder —
live-verified end to end via the Dashboard Agent's real `executeQueries` calls.
"""

from __future__ import annotations

RISK_SCORE_BY_CATEGORY = """
EVALUATE
SUMMARIZECOLUMNS(
    Funds[category],
    "avg_risk_score", AVERAGE(FundRiskScores[risk_score])
)
"""

TOP_N_HIGH_RISK_FUNDS = """
EVALUATE
TOPN(
    {n},
    FundRiskScores,
    FundRiskScores[risk_score],
    DESC
)
"""
