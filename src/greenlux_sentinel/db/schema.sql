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

-- Multilingual report storage (agents/report_agent.py; docs/DATA.md#multilingual-layer;
-- docs/RESPONSIBLE_AI.md#human-in-the-loop-gates). One row per (report, language). The
-- content is agent-generated, not sourced pre-translated data — see DATA.md. A report is
-- not "final" until status = 'published', set only via publish_report() after human approval.
CREATE TABLE IF NOT EXISTS fund_reports (
    report_id               UUID NOT NULL DEFAULT gen_random_uuid(),
    fund_id                 TEXT REFERENCES funds(fund_id),
    language                TEXT NOT NULL,   -- 'en' | 'fr' | 'de'
    content                 TEXT NOT NULL,
    citations               JSONB,           -- tool-call results the numeric claims trace back to
    status                  TEXT NOT NULL DEFAULT 'draft',  -- 'draft' | 'approved' | 'published' | 'rejected'
    created_at              TIMESTAMPTZ DEFAULT now(),
    approved_by             TEXT,
    approved_at             TIMESTAMPTZ,
    PRIMARY KEY (report_id, language)
);
