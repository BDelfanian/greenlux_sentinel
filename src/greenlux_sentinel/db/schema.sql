-- Tier 1 schema (docs/DATA.md#two-tier-data-architecture)
-- Reconciled against the real downloaded CSVs in Phase 1 (notebooks/01_data_profiling) —
-- see docs/DATA.md#datasets for what changed vs. the original best-guess shape (no
-- sharpe/treynor/alpha/beta in the real Morningstar export; no management_company or
-- domicile columns either, both derived in etl/load_funds_postgres.py). Do not add an
-- "sfdr_article" column — see docs/DATA.md#ground-truth-methodology.

CREATE TABLE IF NOT EXISTS funds (
    fund_id                 TEXT PRIMARY KEY,       -- Morningstar `ticker` (an internal fund/share-class ID, not a market ticker)
    isin                    TEXT,                    -- not unique across share classes — reference only, not a join key
    name                    TEXT NOT NULL,
    fund_type               TEXT NOT NULL,           -- 'mutual_fund' | 'etf' (from source file, not a raw column)
    management_company      TEXT,                    -- best-effort, parsed from `name` — ~47% coverage, see docs/DATA.md
    domicile_country        TEXT,                    -- derived from ISIN country prefix (no domicile column in source)
    category                TEXT,          -- Morningstar category
    currency                TEXT,
    total_net_assets        NUMERIC,
    ongoing_cost            NUMERIC,
    sustainability_rating   NUMERIC,       -- Morningstar Sustainability Rating, 1-5 globes (claimed profile)
    sustainability_score    NUMERIC,       -- underlying 0-100 portfolio sustainability score behind the globe rating
    environmental_score     NUMERIC,       -- Morningstar's own portfolio-level E/S/G subscores (claimed side —
    social_score            NUMERIC,       -- compare against Tier 2 holdings-implied E/S/G, not a substitute for it)
    governance_score        NUMERIC,
    return_ytd              NUMERIC,
    return_3y                NUMERIC,
    return_5y                NUMERIC,
    return_10y               NUMERIC,
    quarters_up               INTEGER,
    quarters_down             INTEGER,
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
