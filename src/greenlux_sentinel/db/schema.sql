-- Tier 1 schema (docs/DATA.md#two-tier-data-architecture)
-- Reconciled against the real downloaded CSVs in Phase 1 (notebooks/01_data_profiling) —
-- see docs/DATA.md#datasets for what changed vs. the original best-guess shape (no
-- sharpe/treynor/alpha/beta in the real Morningstar export; no management_company or
-- domicile columns either, both derived in etl/load_funds_postgres.py). Do not add an
-- "sfdr_article" column — see docs/DATA.md#ground-truth-methodology.
-- Phase 9 added the objective portfolio-composition columns on `funds` (sector/asset/market-cap/
-- credit/involvement) and the fund_sustainability_anomaly_scores table — see that table's own
-- comment and docs/DATA.md's Tier 1 composition-anomaly model section.

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

    -- Objective portfolio-composition facts (Phase 9, ml/greenwashing_risk_model.py) — sector/
    -- asset-class/market-cap/credit-quality allocation and controversial-business-involvement
    -- percentages from the raw Morningstar export. Independent of the claimed-side columns above
    -- (sustainability_rating/score, environmental_score/social_score/governance_score) — these are
    -- what the fund's portfolio actually IS, not what it claims. Deliberately excluded from the ML
    -- model's own feature set: environmental_score/social_score/governance_score above (using them
    -- to predict sustainability_rank would be circular, since they're the same claimed signal).
    asset_stock              NUMERIC,
    asset_bond               NUMERIC,
    asset_cash               NUMERIC,
    asset_other              NUMERIC,
    sector_basic_materials         NUMERIC,
    sector_consumer_cyclical       NUMERIC,
    sector_financial_services      NUMERIC,
    sector_real_estate             NUMERIC,
    sector_consumer_defensive      NUMERIC,
    sector_healthcare               NUMERIC,
    sector_utilities                 NUMERIC,
    sector_communication_services     NUMERIC,
    sector_energy                      NUMERIC,
    sector_industrials                  NUMERIC,
    sector_technology                    NUMERIC,
    market_cap_giant          NUMERIC,
    market_cap_large          NUMERIC,
    market_cap_medium         NUMERIC,
    market_cap_small          NUMERIC,
    market_cap_micro          NUMERIC,
    credit_aaa                NUMERIC,
    credit_aa                 NUMERIC,
    credit_a                  NUMERIC,
    credit_bbb                NUMERIC,
    credit_bb                 NUMERIC,
    credit_b                  NUMERIC,
    credit_below_b            NUMERIC,
    credit_not_rated          NUMERIC,
    involvement_abortive_contraceptive  NUMERIC,
    involvement_alcohol                  NUMERIC,
    involvement_animal_testing            NUMERIC,
    involvement_controversial_weapons      NUMERIC,
    involvement_gambling                    NUMERIC,
    involvement_gmo                          NUMERIC,
    involvement_military_contracting          NUMERIC,
    involvement_nuclear                        NUMERIC,
    involvement_palm_oil                        NUMERIC,
    involvement_pesticides                       NUMERIC,
    involvement_small_arms                        NUMERIC,
    involvement_thermal_coal                       NUMERIC,
    involvement_tobacco                             NUMERIC,

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

-- Tier-1-breadth ML signal (Phase 9, ml/greenwashing_risk_model.py) — a RandomForestClassifier
-- predicts each fund's own claimed sustainability_rank bucket from OBJECTIVE portfolio-composition
-- columns above (sector/asset/market-cap/credit/involvement), then composition_anomaly_score =
-- 1 - P(actual bucket): how atypical this fund's real composition looks for the tier it claims.
-- This is NOT the same signal as fund_risk_scores above and the two need not agree — fund_risk_scores
-- compares claim vs. real security-level holdings-implied ESG (Tier 2, 4 funds only); this table
-- compares claim vs. population-typical portfolio composition (Tier 1, ~41k funds with a claim).
-- See docs/DATA.md's Tier 1 composition-anomaly model section for a worked example of the two
-- signals disagreeing on the same fund, and why that's expected rather than a bug.
CREATE TABLE IF NOT EXISTS fund_sustainability_anomaly_scores (
    fund_id                     TEXT REFERENCES funds(fund_id),
    predicted_rating_bucket     TEXT NOT NULL,   -- 'Low' | 'Medium' | 'High', the model's prediction
    actual_rating_bucket        TEXT NOT NULL,   -- 'Low' | 'Medium' | 'High', from the real claimed sustainability_rank
    composition_anomaly_score   NUMERIC NOT NULL,  -- 0-100, higher = composition more atypical for the claimed tier
    composition_anomaly_tier    TEXT NOT NULL,     -- 'Low' | 'Medium' | 'High' anomaly, quantile business rule at train time
    model_version                TEXT NOT NULL,
    computed_at                  TIMESTAMPTZ DEFAULT now(),
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

-- Document-sourced citations for the evidence agent (agents/evidence_agent.py, Phase 8b) — a
-- structurally different citation shape from fund_reports.citations above (that column is a flat
-- JSONB array of tool-sourced *numbers*; this table is one row per retrieved *document passage*
-- an answer actually cited). Kept as a separate table rather than crammed into the existing
-- column so the well-tested numeric-citations report flow stays untouched. report_id is nullable
-- because linking an evidence-agent answer into a *published* report is deferred past Phase 8b —
-- see docs/PROGRESS_LOG.md's Phase 8a/8b entry.
CREATE TABLE IF NOT EXISTS document_citations (
    citation_id             UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    report_id               UUID,            -- nullable; only set if/when linked into a published report
    fund_id                 TEXT REFERENCES funds(fund_id),
    doc_id                  TEXT NOT NULL,   -- Azure AI Search document/chunk id
    doc_type                TEXT NOT NULL CHECK (doc_type IN ('kiid', 'prospectus', 'regulation', 'cssf_guidance')),
    source_url               TEXT,
    passage_excerpt          TEXT,
    relevance_score           NUMERIC,
    created_at               TIMESTAMPTZ DEFAULT now()
);
