-- Tier 1 schema (docs/DATA.md#two-tier-data-architecture)
-- PLACEHOLDER: column names/types below are best-guess from the Kaggle dataset description
-- and MUST be reconciled against the real downloaded CSV in Phase 1 (notebooks/01_data_profiling)
-- before this is treated as final. Do not add an "sfdr_article" column — see
-- docs/DATA.md#ground-truth-methodology.

CREATE TABLE IF NOT EXISTS funds (
    fund_id                 TEXT PRIMARY KEY,
    isin                    TEXT,
    name                    TEXT NOT NULL,
    fund_type               TEXT,          -- 'mutual_fund' | 'etf'
    management_company      TEXT,
    domicile_country        TEXT,          -- expected ISO country code, e.g. 'LU'
    category                TEXT,          -- Morningstar category
    currency                TEXT,
    total_net_assets        NUMERIC,
    ongoing_cost            NUMERIC,
    sustainability_rating   NUMERIC,       -- Morningstar Sustainability Rating (claimed profile)
    return_ytd              NUMERIC,
    sharpe_ratio            NUMERIC,
    treynor_ratio           NUMERIC,
    alpha                   NUMERIC,
    beta                    NUMERIC,
    ingested_at             TIMESTAMPTZ DEFAULT now()
);

-- Tier 2 result, written back by the Greenwashing-Risk Agent (agents/risk_agent.py) after
-- it computes the score from Cosmos DB holdings/ESG data. Only populated for the subset
-- of funds/ETFs with real holdings data (docs/DATA.md#two-tier-data-architecture).
CREATE TABLE IF NOT EXISTS fund_risk_scores (
    fund_id                 TEXT REFERENCES funds(fund_id),
    risk_score              NUMERIC NOT NULL,
    holdings_implied_esg    NUMERIC NOT NULL,
    explanation             TEXT,
    computed_at             TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (fund_id, computed_at)
);

-- Luxembourg entity grounding from the GLEIF API (agents/etl_agent.py)
CREATE TABLE IF NOT EXISTS lu_legal_entities (
    lei                     TEXT PRIMARY KEY,
    legal_name              TEXT NOT NULL,
    entity_legal_form       TEXT,          -- e.g. SICAV, FCP
    entity_status           TEXT,
    country                 TEXT,
    fetched_at              TIMESTAMPTZ DEFAULT now()
);
