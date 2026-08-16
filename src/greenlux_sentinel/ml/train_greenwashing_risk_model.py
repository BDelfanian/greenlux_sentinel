"""Runnable training entry point for ml/greenwashing_risk_model.py (Phase 9).

    python -m greenlux_sentinel.ml.train_greenwashing_risk_model

Loads Tier 1 fund data (live Postgres if credentials are configured, else the local
`data/raw/*.csv` files directly — same DI pattern as etl/etl_agent.py), trains the classifier,
prints the full metrics report, and saves the artifact via `greenwashing_risk_model.save_model()`.

`score_all_funds()` batch-scores every fund with a claimed rating and persists results to
`fund_sustainability_anomaly_scores` — this is what a future pass would call from
`etl_agent.run_ingestion()`; deliberately NOT wired in there yet (see docs/PROGRESS_LOG.md's
Phase 9 entry for why this stays a standalone script for now).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from greenlux_sentinel.db.audit import write_audit_log
from greenlux_sentinel.etl import load_funds_postgres
from greenlux_sentinel.ml import greenwashing_risk_model as model

if TYPE_CHECKING:
    import psycopg

_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"

_SELECT_COLUMNS = ["fund_id", "isin", "sustainability_rating", *model.FEATURE_COLUMNS]


def load_training_data(conn: psycopg.Connection | None = None, data_dir: Path | None = None) -> pd.DataFrame:
    """Load the columns the model needs. If `conn` is given, SELECTs from live Postgres `funds`
    (the production path — not live-verified as of Phase 9, no Azure Postgres credentials were
    available in that session; see docs/PROGRESS_LOG.md). Otherwise transforms the local
    `data/raw/*.csv` files directly via etl.load_funds_postgres.transform() — the exact same
    column mapping the live loader uses, not a second parallel implementation."""
    if conn is not None:
        query = f"SELECT {', '.join(_SELECT_COLUMNS)} FROM funds"
        return pd.read_sql(query, conn)

    data_dir = data_dir or _DEFAULT_DATA_DIR
    mutual_funds = load_funds_postgres.transform(
        pd.read_csv(data_dir / "morningstar_european_mutual_funds.csv", low_memory=False), "mutual_fund"
    )
    etfs = load_funds_postgres.transform(
        pd.read_csv(data_dir / "morningstar_european_etfs.csv", low_memory=False), "etf"
    )
    return pd.concat([mutual_funds, etfs], ignore_index=True)


def score_all_funds(
    result: model.TrainResult, df: pd.DataFrame, conn: psycopg.Connection | None = None
) -> int:
    """Batch-score every fund with a claimed sustainability_rating, write one
    fund_sustainability_anomaly_scores row per fund, and audit-log the write. Caller controls
    commit (same convention as agents/risk_agent.py's persist())."""
    scorable = df.loc[df["sustainability_rating"].notna()]
    rows = []
    for record in scorable.to_dict(orient="records"):
        out = model.score(result, record)
        rows.append((record["fund_id"], out["predicted_rating_bucket"], out["actual_rating_bucket"],
                      out["composition_anomaly_score"], out["composition_anomaly_tier"], out["model_version"]))

    if conn is not None:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO fund_sustainability_anomaly_scores "
                "(fund_id, predicted_rating_bucket, actual_rating_bucket, "
                " composition_anomaly_score, composition_anomaly_tier, model_version) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                rows,
            )
        write_audit_log(
            conn,
            agent_name="ml_greenwashing_risk_model",
            tool_name="score_all_funds",
            input_summary=f"{len(rows)} funds scored, model_version={result.model_version}",
            output_summary=f"wrote {len(rows)} fund_sustainability_anomaly_scores rows",
        )
    return len(rows)


def _print_metrics(metrics: dict[str, Any]) -> None:
    print(f"n_train={metrics['n_train']}  n_test={metrics['n_test']}")
    print(f"accuracy={metrics['accuracy']:.4f}  macro_f1={metrics['macro_f1']:.4f}")
    print(f"confusion_matrix {metrics['confusion_matrix_labels']}:")
    for label, row in zip(metrics["confusion_matrix_labels"], metrics["confusion_matrix"], strict=True):
        print(f"  {label:>8}: {row}")
    print("classification_report:")
    print(json.dumps(metrics["classification_report"], indent=2))


def main(data_dir: Path | None = None) -> model.TrainResult:
    df = load_training_data(data_dir=data_dir)
    print(f"loaded {len(df)} funds ({df['sustainability_rating'].notna().sum()} with a claimed rating)")

    result = model.train(df)
    _print_metrics(result.metrics)

    model.save_model(result)
    print(f"saved model to {model.MODEL_ARTIFACT_PATH}")
    return result


if __name__ == "__main__":
    main()
