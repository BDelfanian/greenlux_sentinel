"""Tier 1 loader — European Funds dataset from Morningstar (Kaggle CSV) -> Postgres.

Source: https://www.kaggle.com/datasets/stefanoleone992/european-funds-dataset-from-morningstar
Ships as two files (57,603 mutual funds + 9,495 ETFs, disjoint `ticker` namespaces — see
docs/DATA.md#datasets), reconciled here against notebooks/01_data_profiling findings:

    - No `management_company` column. Names mostly follow "<Company> - <Fund> <Share Class>"
      (~47% of mutual fund rows) — parsed on a best-effort basis, null when absent. Don't
      treat it as authoritative; that's what GLEIF legal-name grounding is for.
    - No fund domicile column. Derived from the ISIN's 2-letter country prefix — the
      standard practical proxy (real distribution: mutual funds ~58% LU / ~21% IE / ~19% GB;
      ETFs ~51% IE / ~33% LU).
    - No sharpe_ratio/treynor_ratio/alpha/beta — not present in the real export. Replaced
      with the trailing-return and up/down-quarter fields that actually exist.
    - `sustainability_rank` (1-5 globes) is the claimed rating docs/DATA.md refers to as
      `claimed_sustainability_rating`; `sustainability_score` and the E/S/G subscores are
      Morningstar's own portfolio-level score behind it — still the *claimed* side, not a
      substitute for the Tier 2 holdings-implied comparison.
    - Phase 9: also loads 41 OBJECTIVE portfolio-composition columns (asset-class mix, sector
      allocation, market-cap tiers, credit-quality tiers, controversial-business-involvement
      percentages) that were present in the raw export from day one but not previously loaded —
      these feed `ml/greenwashing_risk_model.py`, not the Tier 2 formula. Raw CSV column names
      already match the target `funds` column names exactly (see db/schema.sql), so
      `COMPOSITION_COLUMNS` below maps identity pairs, not renames.

Does NOT add a literal "sfdr_article" column — see docs/DATA.md#ground-truth-methodology.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from greenlux_sentinel.db.audit import write_audit_log

if TYPE_CHECKING:
    import psycopg

# Objective portfolio-composition columns (Phase 9) — raw CSV name == funds table column name,
# see db/schema.sql's own comment on these. Shared with ml/greenwashing_risk_model.py's
# FEATURE_COLUMNS so the two never drift apart.
COMPOSITION_COLUMNS: list[str] = [
    "asset_stock", "asset_bond", "asset_cash", "asset_other",
    "sector_basic_materials", "sector_consumer_cyclical", "sector_financial_services",
    "sector_real_estate", "sector_consumer_defensive", "sector_healthcare", "sector_utilities",
    "sector_communication_services", "sector_energy", "sector_industrials", "sector_technology",
    "market_cap_giant", "market_cap_large", "market_cap_medium", "market_cap_small",
    "market_cap_micro",
    "credit_aaa", "credit_aa", "credit_a", "credit_bbb", "credit_bb", "credit_b",
    "credit_below_b", "credit_not_rated",
    "involvement_abortive_contraceptive", "involvement_alcohol", "involvement_animal_testing",
    "involvement_controversial_weapons", "involvement_gambling", "involvement_gmo",
    "involvement_military_contracting", "involvement_nuclear", "involvement_palm_oil",
    "involvement_pesticides", "involvement_small_arms", "involvement_thermal_coal",
    "involvement_tobacco",
]

# raw CSV header -> funds table column (db/schema.sql). `fund_type`, `domicile_country`, and
# `management_company` are derived separately, not a 1:1 rename — see transform().
RAW_COLUMN_MAP: dict[str, str] = {
    "ticker": "fund_id",
    "isin": "isin",
    "fund_name": "name",
    "category": "category",
    "fund_size_currency": "currency",
    "fund_size": "total_net_assets",
    "ongoing_cost": "ongoing_cost",
    "sustainability_rank": "sustainability_rating",
    "sustainability_score": "sustainability_score",
    "environmental_score": "environmental_score",
    "social_score": "social_score",
    "governance_score": "governance_score",
    "fund_trailing_return_ytd": "return_ytd",
    "fund_trailing_return_3years": "return_3y",
    "fund_trailing_return_5years": "return_5y",
    "fund_trailing_return_10years": "return_10y",
    "quarters_up": "quarters_up",
    "quarters_down": "quarters_down",
    **{col: col for col in COMPOSITION_COLUMNS},
}

_NUMERIC_COLUMNS = [
    "total_net_assets",
    "ongoing_cost",
    "sustainability_rating",
    "sustainability_score",
    "environmental_score",
    "social_score",
    "governance_score",
    "return_ytd",
    "return_3y",
    "return_5y",
    "return_10y",
    "quarters_up",
    "quarters_down",
    *COMPOSITION_COLUMNS,
]

_COLUMN_ORDER = [
    "fund_id", "isin", "name", "fund_type", "management_company", "domicile_country",
    "category", "currency", "total_net_assets", "ongoing_cost", "sustainability_rating",
    "sustainability_score", "environmental_score", "social_score", "governance_score",
    "return_ytd", "return_3y", "return_5y", "return_10y", "quarters_up", "quarters_down",
    *COMPOSITION_COLUMNS,
]

_UPSERT_SQL = f"""
    INSERT INTO funds ({", ".join(_COLUMN_ORDER)})
    VALUES ({", ".join(f"%({c})s" for c in _COLUMN_ORDER)})
    ON CONFLICT (fund_id) DO UPDATE SET
        {", ".join(f"{c} = EXCLUDED.{c}" for c in _COLUMN_ORDER if c != "fund_id")}
"""


def _derive_domicile_country(isin: pd.Series) -> pd.Series:
    return isin.str[:2].str.upper()


def _derive_management_company(name: pd.Series) -> pd.Series:
    has_separator = name.str.contains(" - ", regex=False)
    company = pd.Series(pd.NA, index=name.index, dtype="object")
    company[has_separator] = name[has_separator].str.split(" - ", n=1).str[0].str.strip()
    return company


def transform(raw: pd.DataFrame, fund_type: str) -> pd.DataFrame:
    """Map one raw Morningstar file (mutual funds OR ETFs) onto the `funds` schema.

    `fund_type` ('mutual_fund' | 'etf') is supplied by the caller since it comes from which
    file the rows are from, not a column in either file. Pure function — no I/O.
    """
    missing = set(RAW_COLUMN_MAP) - set(raw.columns)
    if missing:
        raise ValueError(f"morningstar funds CSV is missing expected columns: {sorted(missing)}")

    out = raw.rename(columns=RAW_COLUMN_MAP)[list(RAW_COLUMN_MAP.values())].copy()
    out["fund_type"] = fund_type
    out["domicile_country"] = _derive_domicile_country(raw["isin"])
    out["management_company"] = _derive_management_company(raw["fund_name"])
    for col in _NUMERIC_COLUMNS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out[_COLUMN_ORDER]


def load(mutual_funds_csv: Path, etfs_csv: Path, conn: psycopg.Connection | None = None) -> int:
    """Load both Morningstar fund files into Postgres. Returns total row count.

    Accepts an optional open psycopg connection for testability/DI; opens (and closes) one
    from config.get_settings() when not provided.
    """
    mutual_funds = transform(pd.read_csv(mutual_funds_csv, low_memory=False), "mutual_fund")
    etfs = transform(pd.read_csv(etfs_csv, low_memory=False), "etf")
    combined = pd.concat([mutual_funds, etfs], ignore_index=True)
    records = combined.where(pd.notnull(combined), None).to_dict(orient="records")

    owns_conn = conn is None
    if owns_conn:
        import psycopg

        from greenlux_sentinel.config import get_settings

        conn = psycopg.connect(get_settings().postgres_dsn)

    try:
        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, records)
        write_audit_log(
            conn,
            agent_name="etl_agent",
            tool_name="load_funds_postgres",
            input_summary=f"{mutual_funds_csv}, {etfs_csv}",
            output_summary=f"upserted {len(records)} funds",
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()

    return len(records)
