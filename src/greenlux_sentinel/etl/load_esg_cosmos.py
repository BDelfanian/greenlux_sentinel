"""Tier 2 loader — ETF holdings + company ESG ratings -> reshaped JSON -> Cosmos DB.

Sources:
    https://www.kaggle.com/datasets/jackstev298/full-holdings-data-for-the-top-100-etfs
    https://www.kaggle.com/datasets/alistairking/public-company-esg-ratings-dataset

Joins the two by ticker into one nested JSON document per ETF, written to the Cosmos DB
NoSQL/Core API container (NOT Gremlin — see CLAUDE.md decision #3).

Reconciled against notebooks/01_data_profiling findings on the real files:

    - `holding_name` in the holdings CSV is a stringified dict (Kaggle scrape artifact, e.g.
      "{'t': 'span', 'a': {}, 'c': ['Microsoft Corp']}") — parsed out via `_parse_holding_name`.
    - `weight_pct` is a fraction (0-1), rescaled to a 0-100 percentage here for consistency
      with the rest of the schema.
    - ESG ratings tickers are lowercase; holdings tickers are uppercase — joined case-insensitively.
    - The holdings file has no `sector` column of its own; sector comes from the matched
      company's `industry` field when there's an ESG match, else null (real per-ETF ESG
      coverage ranges 0-90%, median ~16% — see docs/DATA.md, most 0%-coverage ETFs are bond
      funds with no equity holdings to match against an equity ESG dataset).
    - `total_score` (-> `total_esg_score`) is NOT a 0-100 score in this dataset — it's the sum
      of three ~0-600ish subscores, observed range ~600-1536. Don't assume a percentile scale
      when comparing against Tier 1's `sustainability_score` (which is 0-100).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from azure.cosmos import ContainerProxy

_ESG_RAW_TO_INTERNAL: dict[str, str] = {
    "environment_score": "environment_score",
    "social_score": "social_score",
    "governance_score": "governance_score",
    "total_score": "total_esg_score",
    "industry": "sector",
    "total_level": "esg_level",  # 'High' | 'Medium' — an ESG-quality level, not a risk label
}


def _parse_holding_name(raw: Any) -> Any:
    """Unwrap the stringified-dict scrape artifact in the real holdings CSV, e.g.
    "{'t': 'span', 'a': {}, 'c': ['Microsoft Corp']}" -> "Microsoft Corp". Falls back to the
    raw value unchanged if it isn't in that shape (defensive — upstream data can drift)."""
    if not isinstance(raw, str):
        return raw
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return raw
    if isinstance(parsed, dict) and parsed.get("c"):
        return parsed["c"][0]
    return raw


def transform(holdings: pd.DataFrame, esg: pd.DataFrame) -> list[dict[str, Any]]:
    """Join holdings to company ESG ratings by ticker, one nested doc per ETF. Pure function."""
    esg_fields = list(_ESG_RAW_TO_INTERNAL.values())
    esg_indexed = esg.rename(columns=_ESG_RAW_TO_INTERNAL).assign(ticker=esg["ticker"].str.upper())
    esg_by_ticker = esg_indexed.set_index("ticker")[esg_fields].to_dict(orient="index")

    holdings = holdings.rename(
        columns={
            "etf_symbol": "etf_ticker",
            "etf_title": "etf_name",
            "holding_symbol": "holding_ticker",
        }
    )
    holdings = holdings.assign(
        holding_name=holdings["holding_name"].map(_parse_holding_name),
        weight_pct=holdings["weight_pct"] * 100,
    )

    docs: list[dict[str, Any]] = []
    for etf_ticker, group in holdings.groupby("etf_ticker", sort=False):
        etf_name = group["etf_name"].iloc[0]

        holding_docs = []
        matched_weight, matched_score_weight = 0.0, 0.0
        for row in group.itertuples(index=False):
            esg_row = esg_by_ticker.get(row.holding_ticker)
            holding_docs.append(
                {
                    "ticker": row.holding_ticker,
                    "name": row.holding_name,
                    "weight_pct": row.weight_pct,
                    "esg": dict(esg_row) if esg_row is not None else None,
                }
            )
            if esg_row is not None:
                matched_weight += row.weight_pct
                matched_score_weight += row.weight_pct * esg_row["total_esg_score"]

        holdings_implied_esg = round(matched_score_weight / matched_weight, 2) if matched_weight > 0 else None

        docs.append(
            {
                "id": etf_ticker,
                "etf_ticker": etf_ticker,
                "etf_name": etf_name,
                "holdings_count": len(holding_docs),
                "esg_coverage_pct": round(100 * sum(1 for h in holding_docs if h["esg"]) / len(holding_docs), 1),
                "holdings_implied_esg_score": holdings_implied_esg,
                "holdings": holding_docs,
            }
        )
    return docs


def load(holdings_csv: Path, esg_csv: Path, container: ContainerProxy | None = None) -> int:
    """Reshape and upsert into Cosmos DB. Returns document count.

    Accepts an optional Cosmos ContainerProxy for testability/DI; builds one from
    config.get_settings() when not provided.
    """
    docs = transform(pd.read_csv(holdings_csv), pd.read_csv(esg_csv))

    owns_container = container is None
    if owns_container:
        from azure.cosmos import CosmosClient

        from greenlux_sentinel.config import get_settings

        settings = get_settings()
        client = CosmosClient(settings.cosmos_endpoint, credential=settings.cosmos_key)
        database = client.get_database_client(settings.cosmos_database)
        container = database.get_container_client(settings.cosmos_container)

    for doc in docs:
        container.upsert_item(doc)

    return len(docs)
