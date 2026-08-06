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

## Tier 2 verified holdings (Phase 2 correction)

**The original Tier 2 source cannot support the risk-score formula above.** Phase 2 discovered
that "Full Holdings Data for the Top 100 ETFs" (the dataset in the Datasets table below) is a set
of plain US-listed index/bond trackers (VOO, SPY, VTI, sector SPDRs, Treasury ETFs, etc.) — none
carry a sustainability claim of their own, and **none exist in the Tier 1 Morningstar European
funds table** (0/99 match by ticker, confirmed against live data — different market entirely).
The two-tier design assumed Tier 2 was "a narrower set" of Tier 1 (CLAUDE.md decision #2); that
assumption was never checked in Phase 1 (which only profiled *Tier-2-internal* ticker overlap —
holdings vs. ESG ratings — not Tier1-vs-Tier2 fund identity) and turned out to be false. With no
fund carrying both a claimed rating *and* real holdings, `risk_score()` was uncomputable for any
fund in that dataset.

**Fix:** `etl/fetch_verified_holdings.py` pulls real, current, issuer-published holdings (the same
"Download Holdings" CSV export any visitor can get from the fund's public product page — no auth)
for five UCITS ETFs that *are* real rows in Tier 1, chosen for being large-cap US/global equity
funds so their holdings overlap well with the US-centric `public_company_esg_ratings.csv`:

| ISIN | Fund | Tier 1 sustainability rating | Note |
|---|---|---|---|
| IE00BYVJRR92 | iShares MSCI USA SRI UCITS ETF | 5 globes / 20.00 | |
| IE00BFNM3G45 | iShares MSCI USA ESG Screened UCITS ETF | 3 globes / 22.37 | |
| IE00BDZZTM54 | iShares MSCI World SRI UCITS ETF | 5 globes / 19.85 | |
| IE00BKVL7331 | iShares Edge MSCI USA Min Vol ESG UCITS ETF | 5 globes / 20.81 | |
| IE00B5BMR087 | iShares Core S&P 500 UCITS ETF | 3 globes / 22.54 | No ESG claim — kept as a control, not part of the greenwashing comparison |

Weighted ticker overlap against the ESG ratings dataset is 52-84% per fund (vs. ~14% for the
original Top 100 set) — see `etl/load_verified_holdings_cosmos.py`. `risk_agent.py` (Phase 2)
computes the real Greenwashing Risk Score only for these five (well, four — CSPX has no claim to
compare against), by ISIN. The original Top 100 Kaggle set stays loaded (`load_esg_cosmos.py`) as
a separate, clearly-unlinked *descriptive* holdings-ESG-aggregation dataset — useful for showing
the pipeline technique, not used for the risk score. Re-running `fetch_verified_holdings.py`
re-pulls the current day's holdings; this is not a point-in-time archive.

**Known limitation — none of the five verified funds are Luxembourg-domiciled.** All five ISINs
above start with `IE` (Ireland) — chosen because iShares/BlackRock happens to publish a trivially
scriptable public "Download Holdings" CSV per fund, which is what made this fix tractable at all.
This project's Luxembourg framing (CSSF anti-greenwashing priorities, ALFI/LSFI's sustainable-fund
hub status — see "Why this topic" above) is carried by Tier 1 as a whole (58% of mutual funds /
33% of ETFs are LU-domiciled) and by the GLEIF LU legal-entity grounding, both untouched by this
fix — but the flagship risk-score *demo* specifically doesn't showcase a real Luxembourg fund.

Real LU-domiciled equivalents do exist in Tier 1 with the same strategy profile — e.g.
`LU1861136247` (Amundi Index MSCI USA SRI UCITS ETF DR) and `LU1291103338` (BNP Paribas Easy MSCI
USA SRI UCITS ETF) both showed up in the same 690-fund ESG/SRI search that produced the five above.
Neither Amundi's nor BNP Paribas's public fund pages were found to expose an iShares-style static
CSV export (checked via direct page fetch — Amundi's holdings data appears to load from a private
API not present in the static HTML; no CSV/XLSX link surfaced for BNP Paribas either). Pulling a
real LU-domiciled fund into the verified set would need either a headless browser against one of
those sites, a paid data provider, or contacting the issuer directly — none attempted, given
Phase 2's time budget. Left as a candidate follow-up, not blocking Phase 3.

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

**Postgres, not Cosmos DB, deliberately.** Early planning floated Cosmos as the natural home for
this ("a multilingual document store") since it's schema-flexible text. Decided against it: the
report lifecycle needs transactional draft→approved→published updates and a plain join to
`funds`, both simpler in Postgres than as Cosmos read-modify-write. Cosmos DB's role stays
scoped to Tier 2 ESG holdings documents (see two-tier architecture above) — one clear job, not
two unrelated ones bolted together for the sake of touching Cosmos twice.

## First milestone: data profiling

Before any schema is finalized, profile the real downloaded files (row counts, actual column
names, null rates, ticker overlap between the holdings dataset and the ESG ratings dataset) in
`notebooks/`. Treat everything above as the intended design, not a confirmed final schema — Kaggle
dataset descriptions can drift from what's actually in the CSV.

**Current status: done, against the real files.** `notebooks/01_data_profiling.ipynb` ran against
the actual downloads in `data/raw/`; `db/schema.sql` and the `RAW_COLUMN_MAP` constants in
`etl/load_funds_postgres.py` / `etl/load_esg_cosmos.py` were reconciled against real column names,
not the original best-guess. Headline drift from the original design draft:

- The Morningstar export has 132 columns per fund, not ~16 — full sector/asset allocation,
  involvement flags, quarterly returns back to 2015, and Morningstar's own portfolio E/S/G
  subscores, but **no** `management_company`, `domicile`, `sharpe_ratio`, `treynor_ratio`,
  `alpha`, or `beta` column. `domicile_country` is derived from the ISIN's 2-letter country
  prefix (sane distribution: LU/IE dominate both mutual funds and ETFs, matching real-world
  fund-domicile geography). `management_company` is a best-effort parse of `fund_name` on the
  `"<Company> - <Fund>"` pattern — only ~44% coverage, kept nullable, not authoritative
  (GLEIF legal-name grounding remains authoritative for LU entity identity).
- Real Tier 2 ticker overlap is **~14%** of unique ETF holding tickers (590/4,229) against the
  ~700-company ESG ratings file — much lower than the ~79% used in early synthetic fixtures for
  scaffolding. Per-ETF coverage ranges 0-90.3%, median 16%; 35 of the 99 ETFs (bond funds) have
  zero overlap since the ESG ratings dataset only covers equities. The greenwashing-risk model
  (Phase 2) should scope itself to the higher-coverage equity ETFs (32/99 at ≥50% coverage), not
  attempt all 99 — see the notebook for the full per-ETF breakdown.
- The holdings CSV stores holding names as a stringified-dict scrape artifact (e.g.
  `"{'t': 'span', 'a': {}, 'c': ['Microsoft Corp']}"`), parsed in `load_esg_cosmos.py`.
- The ESG ratings file's `total_score` is not a 0-100 score (observed range ~600-1536, sum of
  three subscores) — not directly comparable to Tier 1's 0-100 `sustainability_score` without
  normalizing first, a Phase 2 concern for the risk model.

`tests/fixtures/*.csv` still hold small *synthetic* stand-ins, now matching the real column
shapes — used for fast, deterministic unit tests of `etl/` transform logic, not a substitute for
the profiling above.
