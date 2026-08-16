"""Tier 2 (verified subset) loader — real issuer-published holdings for five UCITS ETFs that are
confirmed present in Tier 1's Morningstar funds table (see etl/fetch_verified_holdings.py for why
this exists: the original Kaggle "Top 100 ETFs" holdings dataset has zero overlap with Tier 1 and
no fund of its own carries a sustainability claim, so no risk score could ever be computed from
it — see docs/DATA.md#tier-2-verified-holdings).

Every document here carries an `isin` that resolves to a real row in Tier 1's `funds` table, so
risk_agent.py can look up the claimed sustainability rating and compute a real gap. Distinct from
load_esg_cosmos.py's Top 100 set (kept as a separate, clearly-unlinked descriptive dataset — see
that module's docstring) — written to the same Cosmos container but tagged `source`.

Reconciled quirks specific to the iShares holdings export format (different from the Kaggle
Top 100 CSV shape):
    - Two metadata rows before the real header (`Fund Holdings as of,<date>` then a blank line).
    - `Weight (%)` is already a percentage (e.g. "7.85" = 7.85%), NOT a 0-1 fraction like the
      Kaggle holdings file — do not rescale it again.
    - Numbers use a Unicode right-quote (’) as the thousands separator, not a comma.
    - Includes non-equity rows (cash, FX forwards, futures) — filtered to `Asset Class == "Equity"`
      before joining to the (equity-only) company ESG ratings dataset.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from greenlux_sentinel.etl.fetch_verified_holdings import VERIFIED_ETFS

if TYPE_CHECKING:
    from azure.cosmos import ContainerProxy

_ESG_RAW_TO_INTERNAL: dict[str, str] = {
    "environment_score": "environment_score",
    "social_score": "social_score",
    "governance_score": "governance_score",
    "total_score": "total_esg_score",
    "industry": "sector",
    "total_level": "esg_level",
}


def _read_one_fund_csv(path: Path) -> pd.DataFrame:
    """Parse one iShares per-fund holdings export into equity rows only."""
    df = pd.read_csv(path, skiprows=2, thousands="’")
    df = df[df["Asset Class"] == "Equity"].copy()
    df["Ticker"] = df["Ticker"].str.upper()
    return df


def load_raw_holdings(holdings_dir: Path) -> pd.DataFrame:
    """Read all five verified-fund CSVs from holdings_dir into one combined frame, tagged with
    each fund's ISIN/ticker/name from the VERIFIED_ETFS manifest. I/O — not the pure transform."""
    frames = []
    for filename, isin, ticker, _url in VERIFIED_ETFS:
        fund_df = _read_one_fund_csv(holdings_dir / filename)
        fund_df["isin"] = isin
        fund_df["etf_ticker"] = ticker
        frames.append(fund_df)
    return pd.concat(frames, ignore_index=True)


def transform(holdings: pd.DataFrame, esg: pd.DataFrame) -> list[dict[str, Any]]:
    """Join verified holdings to company ESG ratings by ticker, one doc per fund. Pure function.

    `holdings` must have the shape produced by load_raw_holdings(): Ticker, Name, Sector,
    Weight (%), isin, etf_ticker (already equity-only, already uppercased tickers).
    """
    esg_fields = list(_ESG_RAW_TO_INTERNAL.values())
    esg_indexed = esg.rename(columns=_ESG_RAW_TO_INTERNAL).assign(ticker=esg["ticker"].str.upper())
    # .astype(object) first -- a float64 column can't hold Python None (silently coerced back to
    # NaN otherwise), which would then fail json.dumps() with an invalid-JSON NaN token; see
    # load_funds_postgres.load()'s same fix for the confirmed-live version of this bug.
    esg_indexed = esg_indexed.astype(object).where(pd.notnull(esg_indexed), None)
    esg_by_ticker = esg_indexed.set_index("ticker")[esg_fields].to_dict(orient="index")

    docs: list[dict[str, Any]] = []
    for isin, group in holdings.groupby("isin", sort=False):
        group = group.rename(columns={"Weight (%)": "weight_pct"})
        etf_ticker = group["etf_ticker"].iloc[0]

        holding_docs = []
        matched_weight, matched_score_weight = 0.0, 0.0
        for row in group.itertuples(index=False):
            # A handful of foreign (non-US-listed) constituents have no ticker in the iShares
            # export at all (blank cell -> pandas NaN) -- e.g. some Canadian banks in SUSW.
            ticker = row.Ticker if isinstance(row.Ticker, str) else None
            esg_row = esg_by_ticker.get(ticker)
            holding_docs.append(
                {
                    "ticker": ticker,
                    "name": row.Name,
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
                "id": isin,
                "isin": isin,
                "etf_ticker": etf_ticker,
                "source": "issuer_verified",
                "holdings_count": len(holding_docs),
                "esg_coverage_pct": round(100 * sum(1 for h in holding_docs if h["esg"]) / len(holding_docs), 1),
                "holdings_implied_esg_score": holdings_implied_esg,
                "holdings": holding_docs,
            }
        )
    return docs


def load(holdings_dir: Path, esg_csv: Path, container: ContainerProxy | None = None) -> int:
    """Reshape and upsert the five verified funds into Cosmos DB. Returns document count.

    Accepts an optional Cosmos ContainerProxy for testability/DI; builds one from
    config.get_settings() when not provided.
    """
    docs = transform(load_raw_holdings(holdings_dir), pd.read_csv(esg_csv))

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
