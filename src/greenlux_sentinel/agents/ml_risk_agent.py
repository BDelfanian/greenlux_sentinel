"""ML Composition-Anomaly Agent — the Postgres-wired callable layer around
`ml/greenwashing_risk_model.py` (Phase 9's trained classifier), for the supervisor's `multi_hop`
pipeline (Phase 9b — see docs/PROGRESS_LOG.md).

Responsibility: given a `fund_id`, fetch its Tier 1 composition columns + claimed
`sustainability_rating` from Postgres, score it with the trained model, persist one
`fund_sustainability_anomaly_scores` row, and audit-log the call — the same
compute-and-record shape as `agents/risk_agent.score_fund()`.

**Deliberately a separate module from `risk_agent.py`, not a second code path inside it** — the
two signals must never be conflated (CLAUDE.md decision #8): `risk_agent.score_fund()` is the Tier
2 real-holdings-based gap (5 issuer-verified ETFs only); this is the Tier 1 population-relative
composition-anomaly score (any fund with a claimed rating and composition data, ~41k funds once
Postgres is backfilled). Read-only from the caller's perspective aside from its own output write —
same autonomy class as `risk_agent`, no human-in-the-loop gate.

The feature-row read and the fund_sustainability_anomaly_scores write stay direct psycopg calls,
not `mcp_servers.postgres_server` tool calls — same convention `risk_agent.py`'s docstring
documents for its own hardcoded, non-analyst-facing reads/writes (not the dynamic LLM-generated
SQL `run_readonly_query` is for). Only the audit-log write goes through the MCP tool.

Loads the trained model artifact via `ml.greenwashing_risk_model.load_model()` and caches it at
module scope for the life of the process — this project has no MLOps
retraining/serving pipeline (docs/RESPONSIBLE_AI.md), so a missing artifact
(`ml/artifacts/greenwashing_rating_classifier.joblib`, gitignored, produced by
`python -m greenlux_sentinel.ml.train_greenwashing_risk_model`) is an operational precondition,
not something this agent trains on the fly inside a request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from greenlux_sentinel.ml import greenwashing_risk_model as model

if TYPE_CHECKING:
    import psycopg

_SELECT_COLUMNS = ["fund_id", "isin", "sustainability_rating", *model.FEATURE_COLUMNS]

_cached_model: model.TrainResult | None = None


def _load_cached_model() -> model.TrainResult:
    global _cached_model
    if _cached_model is None:
        _cached_model = model.load_model()
    return _cached_model


def _fetch_feature_row(fund_id: str, conn: psycopg.Connection) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(_SELECT_COLUMNS)} FROM funds WHERE fund_id = %s", (fund_id,))
        row = cur.fetchone()
        if row is None:
            return None
        columns = [desc.name for desc in cur.description]
    return dict(zip(columns, row, strict=True))


def score_fund_composition(fund_id: str, conn: psycopg.Connection | None = None) -> dict[str, Any]:
    """Public entry point (mirrors risk_agent.score_fund's shape/DI pattern). Returns
    {"predicted_rating_bucket", "actual_rating_bucket", "composition_anomaly_score",
    "composition_anomaly_tier", "model_version", "caveat"}.

    Raises ValueError if fund_id isn't found or has no claimed sustainability_rating; raises
    FileNotFoundError if no trained model artifact exists yet. Neither is swallowed here -- the
    caller (supervisor.dispatch(), same as every other hop) is what turns a raised exception into
    a recorded hop_errors entry instead of a crash.
    """
    from greenlux_sentinel.mcp_servers import postgres_server

    owns_conn = conn is None
    if owns_conn:
        import psycopg

        from greenlux_sentinel.config import get_settings

        conn = psycopg.connect(get_settings().postgres_dsn)

    try:
        row = _fetch_feature_row(fund_id, conn)
        if row is None:
            raise ValueError(f"fund_id={fund_id} not found")

        result = model.score(_load_cached_model(), row)

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO fund_sustainability_anomaly_scores "
                "(fund_id, predicted_rating_bucket, actual_rating_bucket, "
                " composition_anomaly_score, composition_anomaly_tier, model_version) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    fund_id,
                    result["predicted_rating_bucket"],
                    result["actual_rating_bucket"],
                    result["composition_anomaly_score"],
                    result["composition_anomaly_tier"],
                    result["model_version"],
                ),
            )
        postgres_server.write_audit_log(
            conn=conn,
            agent_name="ml_risk_agent",
            tool_name="score_fund_composition",
            input_summary=fund_id,
            output_summary=f"tier={result['composition_anomaly_tier']}, score={result['composition_anomaly_score']}",
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()

    return result
