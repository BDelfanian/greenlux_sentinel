# Data

## Why this topic

The CSSF's 2026 supervisory priorities explicitly flag anti-greenwashing controls and consistency
between SFDR pre-contractual disclosures, periodic reports, and marketing materials as a top
focus for Luxembourg-supervised entities, and Luxembourg remains Europe's largest hub for
sustainable fund assets (ALFI/LSFI). This project builds a lightweight, data-driven version of
that same consistency check.

## Ground-truth methodology

**Important — read before implementing the risk model.** No free/public dataset was confirmed to
carry the legal SFDR Article 6/8/9 classification (that field lives in commercial data —
Morningstar Direct, CSSF regulatory filings — not open Kaggle data). The **Greenwashing Risk
Score** is therefore computed as:

```
risk_score(fund) = f(claimed_sustainability_rating, holdings_implied_esg_profile)
```

where `claimed_sustainability_rating` is the fund's Morningstar Sustainability Rating and
`holdings_implied_esg_profile` is the weighted-average ESG rating of the fund's real disclosed
constituents. This mirrors published academic methodology comparing Morningstar sustainability
data to underlying holdings — it is a **data-driven proxy indicator**, not a determination of
regulatory non-compliance. Every report/dashboard surface must state this caveat. Do not
introduce a fabricated "sfdr_article" column anywhere in the schema.

## Two-tier data architecture

The Morningstar fund dataset only has *sector/asset-class* allocation (cash/stocks/bonds/sectors),
not security-level holdings — so a direct fund → individual-company → company-ESG-score join is
not possible at full scale. Rather than pretend otherwise:

- **Tier 1 — breadth (Postgres):** the full Morningstar fund universe. Powers the BI dashboard and
  the agentic NL2SQL / query-optimizer layer, where volume matters more than holdings depth.
- **Tier 2 — depth (Cosmos DB):** a narrower set of ETFs that do publish real constituent
  holdings, joined to company-level ESG ratings. This is where the greenwashing-risk model
  actually runs. Its results (per-ETF risk score) get written back into a Postgres table so the
  BI/report layer can reference them alongside the broader fund universe.

## Datasets

| Dataset | Source | Size | Format | Role |
|---|---|---|---|---|
| European Funds dataset from Morningstar | [Kaggle](https://www.kaggle.com/datasets/stefanoleone992/european-funds-dataset-from-morningstar) | ~57.6k mutual funds + ~9.5k ETFs | CSV → Postgres | Tier 1: fund universe, returns, fees, category, Morningstar Sustainability Rating |
| Full Holdings Data for the Top 100 ETFs | [Kaggle](https://www.kaggle.com/datasets/jackstev298/full-holdings-data-for-the-top-100-etfs) | Top 100 ETFs, constituent-level | CSV → Cosmos DB (reshaped to JSON) | Tier 2: real security-level holdings |
| Public Company ESG Ratings Dataset | [Kaggle](https://www.kaggle.com/datasets/alistairking/public-company-esg-ratings-dataset) | ~700 companies | CSV → reshaped to nested JSON → Cosmos DB | Tier 2: company-level ESG scores joined to holdings by ticker |
| GLEIF LEI data | [GLEIF API](https://www.gleif.org/en/lei-data/gleif-api) (live, no key) | Luxembourg-registered entities (SICAV/FCP, country=LU) | JSON via REST, called at runtime | Authentic Luxembourg legal-entity grounding — proves domicile claims against a real public register |

## Multilingual layer

No raw multilingual source data was found (Morningstar UK data is English-only). The EN/FR/DE
layer is therefore a **pipeline output**: the Report Agent generates and maintains fund-summary
text in all three languages, mirroring how Luxembourg KIID/PRIIPs documents are actually produced
in practice. Document this as agent-generated content in any write-up — don't imply it was
scraped pre-translated. Persisted in Postgres as `fund_reports` (one row per report/language,
`draft` → `approved` → `published` lifecycle) — see `src/greenlux_sentinel/db/schema.sql`.

## First milestone: data profiling

Before any schema is finalized, profile the real downloaded files (row counts, actual column
names, null rates, ticker overlap between the holdings dataset and the ESG ratings dataset) in
`notebooks/`. Treat everything above as the intended design, not a confirmed final schema — Kaggle
dataset descriptions can drift from what's actually in the CSV.
