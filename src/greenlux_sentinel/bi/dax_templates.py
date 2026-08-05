"""DAX query templates, parameterized and filled in by the Dashboard Agent at request time.

This is what makes the dashboard "dynamic, not static" (docs/REQUIREMENTS_TRACEABILITY.md,
row 7) — the agent picks/parameterizes a template based on the analyst's NL question rather
than the dashboard shipping with a fixed, pre-built report.

TODO(Phase 4):
    - Fill in real DAX once the Power BI dataset schema (from Postgres/Cosmos) is published
    - Keep templates parameterized by fund_id / category / date range, not hardcoded
"""

from __future__ import annotations

# Placeholder — replace with real measures once the Power BI dataset is published.
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
