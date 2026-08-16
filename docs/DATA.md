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

## Tier 1 composition-anomaly model (ML)

Phase 9. `ml/greenwashing_risk_model.py` — the project's first classical, **trained** ML
component (previously an unimplemented stub; the shipped score was `agents/risk_agent.py`'s
hand-written linear formula, not a learned model).

**Why not a classifier trained to detect greenwashing directly:** no free dataset carries a real
SFDR/greenwashing label (see "Ground-truth methodology" above), and the only place a genuine
holdings-based signal exists (Tier 2, `compute_gap()`) covers **4 funds** — far too small for a
credible train/test split. Instead, this model uses the full Tier 1 population and predicts a
**real, existing** field.

**Model:** a single `RandomForestClassifier` predicting each fund's own claimed
`sustainability_rating`, bucketed Low(1-2)/Medium(3)/High(4-5), from 41 **objective**
portfolio-composition columns newly loaded onto `funds` (`etl/load_funds_postgres.
COMPOSITION_COLUMNS` — asset-class mix, 11 sector allocations, 5 market-cap tiers, 8
credit-quality tiers, 13 controversial-business-involvement percentages — alcohol, tobacco,
weapons, gambling, thermal coal, etc.). These were present in the raw Kaggle export from day one
but never loaded into Postgres until now. **Deliberately excludes**
`environmental_score`/`social_score`/`governance_score`/`sustainability_score` as features — these
are commented in `db/schema.sql` as claimed-side, the same signal as the target itself, so
including them would make the prediction circular. The model's own `predict_proba` output *is*
the anomaly signal: `composition_anomaly_score = (1 - P(actual claimed bucket)) * 100` — no second
model trained on the first model's own residual/quantile-bins (considered and rejected as
near-tautological).

**Methodology, and why it matters:** ~6% of ISINs in the scorable population have more than one
`fund_id` row (share classes of the same underlying fund, near-identical feature values). A naive
row-level train/test split lets near-duplicates leak across the split and inflates the score —
confirmed empirically (naive split: ~92.8% accuracy; the honest, methodologically-correct
`GroupShuffleSplit` grouped by ISIN: ~90.7-90.9%). Imputation medians (for the structural
missingness below) are fit on the train fold only and applied unchanged to the test fold — a
second, smaller leakage source avoided the same way. See
`notebooks/02_ml_model_worked_example.ipynb` for this comparison reproduced live against the real
data.

**Missingness is structural, not random:** `credit_*` columns are present almost only for bond
funds, `sector_*`/`market_cap_*` almost only for equity funds (confirmed via crosstab: mean
`asset_bond` ≈ 77% when `credit_aaa` is present vs. ≈19% when absent). Handled via median
imputation plus a same-named `<col>__missing` indicator flag per feature — the flags themselves
carry real signal, not noise.

**Real metrics** (trained via `python -m greenlux_sentinel.ml.train_greenwashing_risk_model`
against the real local `data/raw/*.csv` files, 67,098 funds, 40,737 with a claimed rating,
`GroupShuffleSplit` by ISIN):

- **Classification (shipped model): accuracy 90.9%, macro-F1 0.910**, vs. a 38.4% most-frequent-
  class baseline; confusion matrix diagonal-dominant across all three buckets, no collapsed class.
- Top feature importances are intuitively sane — `market_cap_small`, `market_cap_giant`,
  `sector_energy`, `involvement_thermal_coal`, `sector_technology`, `involvement_animal_testing` —
  well-known real ESG-score drivers, another sanity check that the model learned a real pattern.
- `category` (295 distinct values, confirmed no leakage-by-name of "sustainable/esg/sri" terms) is
  left out of v1 — too high-cardinality for naive one-hot, and target/mean encoding needs
  out-of-fold care not justified yet without a live DB to validate against. Deferred follow-up:
  per-category peer normalization (compare a fund's anomaly score only against same-category
  peers).
- A regression variant (predict continuous `sustainability_score` instead) was also validated,
  same split methodology: R²≈0.76, MAE≈1.0 (target std≈3.76) — comparably strong signal, not
  shipped as primary because the classification framing matches the existing Low/Medium/High
  globe-rating vocabulary more directly, not because it performed worse.
- A pure unsupervised `IsolationForest` was considered and rejected: it can't condition on
  "atypical *for its claimed tier*," which is the actual point of a supervised model here.

**Honest limitation — this signal does NOT need to agree with Tier 2's `compute_gap()`, and in the
one case checked, it doesn't.** Cross-checking against `IE00BYVJRR92` (iShares MSCI USA SRI UCITS
ETF, `fund_id` `0P00018CYB` — the same fund already used in the live-verified Phase 7/8 demo):
Tier 1's composition-anomaly score is **14.82 (Low tier)** — this fund's sector/asset/involvement
mix looks entirely typical for a High-claiming fund — while Tier 2's real holdings-based gap is
**53.03** (`holdings_implied_esg=1039.64`) — its actual, named constituents' individual ESG scores
tell a less flattering story. This is the expected, correct result of two different questions, not
a bug: Tier 1 asks "is this claim typical for funds with this kind of *portfolio composition*,
population-wide?" (broad, ~41k funds, but coarse); Tier 2 asks "given this fund's *actual
constituent holdings*, does the real weighted ESG profile support the claim?" (narrow, 4 funds,
but the more grounded question). This is exactly why the two-tier architecture (decision #2) is
kept rather than collapsed into one score. Full walkthrough, plus a contrasting fund the model
*does* flag (`F00000W9IL`, UBAM SRI European Convertible Bond, predicted Medium vs. claimed High,
anomaly score 65.27/High tier): `notebooks/02_ml_model_worked_example.ipynb`.

**Scope, honestly stated:** not wired into `etl_agent.run_ingestion()`, a new LangGraph agent
node, or a new API route this pass (see docs/PROGRESS_LOG.md's Phase 9 entry for why). Not run
against live Azure Postgres — no credentials were available in the session that built this; the
schema/loader changes are real code, trained/evaluated only against the local, gitignored
`data/raw/*.csv` files, and `agents/sql_agent.py`'s `_SCHEMA_DDL` already includes the new
`fund_sustainability_anomaly_scores` table so the existing NL2SQL agent can query it once live
data exists.

**Phase 9b — wired into the multi-hop pipeline.** `agents/ml_risk_agent.py` (a new,
Postgres-wired, `risk_agent.score_fund()`-shaped caller of this model) is now a fourth plannable
hop in `agents/supervisor.py`'s `multi_hop` route, alongside `sql`/`risk`/`evidence`. This is the
concrete answer to "what does this model add for a user": `risk` (Tier 2) only succeeds for the 5
issuer-verified ETFs — every other fund's multi-hop answer today combines document evidence with
*zero* quantitative grounding. `ml_risk` fills that gap for any fund with a claimed rating and
composition data (~41k funds once Postgres is backfilled), so a question like "is this fund's KIID
consistent with its rating, and does anything about its portfolio composition look unusual?" gets
one synthesized answer citing both a real disclosure passage *and* a real, quantified anomaly
score — not just prose. See CLAUDE.md decision #6's Phase 9b update for the full reasoning,
including why `risk` and `ml_risk` are kept as two distinctly-named facts, never merged into one
number.

**Phase 9c — the above didn't actually work until this fix, and now it's live-confirmed.** Phase
9b's hop wiring alone still produced abstentions: the evidence hop drafted its answer blind to
`ml_risk`'s result (a `dispatch()` bug), and even once facts did reach it, a precomputed number had
no `[doc:<id>]` to cite so the guardrail-following model declined to state it. Both fixed — see
CLAUDE.md decision #6's Phase 9c correction and docs/PROGRESS_LOG.md's Phase 9c entry for the real
transcript: a live question about `0P0001EVL3`'s KIID exclusions vs. its 47.49/Medium
composition-anomaly score returned a genuine synthesized answer citing both, confirmed independently
by the user's own live UI test. Also: live Postgres backfill happened this same session (Phase 9b's
live entry) — the "once Postgres is backfilled" caveat above is resolved, not hypothetical.

## Datasets

| Dataset | Source | Size | Format | Role |
|---|---|---|---|---|
| European Funds dataset from Morningstar | [Kaggle](https://www.kaggle.com/datasets/stefanoleone992/european-funds-dataset-from-morningstar) | ~57.6k mutual funds + ~9.5k ETFs | CSV → Postgres | Tier 1: fund universe, returns, fees, category, Morningstar Sustainability Rating |
| Full Holdings Data for the Top 100 ETFs | [Kaggle](https://www.kaggle.com/datasets/jackstev298/full-holdings-data-for-the-top-100-etfs) | Top 100 ETFs, constituent-level | CSV → Cosmos DB (reshaped to JSON) | Tier 2: real security-level holdings |
| Public Company ESG Ratings Dataset | [Kaggle](https://www.kaggle.com/datasets/alistairking/public-company-esg-ratings-dataset) | ~700 companies | CSV → reshaped to nested JSON → Cosmos DB | Tier 2: company-level ESG scores joined to holdings by ticker |
| GLEIF LEI data | [GLEIF API](https://www.gleif.org/en/lei-data/gleif-api) (live, no key) | Luxembourg-registered entities (SICAV/FCP, country=LU) | JSON via REST, called at runtime | Authentic Luxembourg legal-entity grounding — proves domicile claims against a real public register |
| Fund KIIDs/PRIIPS-KIDs | Issuer (BlackRock/iShares), per verified ISIN | 5 PDFs | PDF → text → Azure AI Search | Document corpus, Phase 8: per-fund disclosure evidence for the Evidence Agent |
| Umbrella prospectuses | Issuer (BlackRock/iShares) | 2 PDFs (shared across the 5 ISINs) | PDF → text (capped, see below) → Azure AI Search | Document corpus, Phase 8 |
| SFDR Regulation + RTS | [EUR-Lex](https://eur-lex.europa.eu/), CELEX 32019R2088 / 32022R1288 | 2 PDFs | PDF → text → Azure AI Search | Document corpus, Phase 8: general regulatory grounding |
| CSSF FAQ + Circular 26/905 | [CSSF](https://www.cssf.lu/) | 2 PDFs | PDF → text → Azure AI Search | Document corpus, Phase 8: general regulatory grounding |

## Document corpus (Phase 8)

Backs the Evidence Agent (`agents/evidence_agent.py`) — see CLAUDE.md decision #4's Phase 8
correction for why this exists at all (a deliberate reversal of the original "no RAG" decision).

**11 documents total, every URL individually live-verified** (a real HTTP GET returning
`application/pdf`, not assumed from a naming pattern) before being hardcoded into
`etl/fetch_fund_documents.py` — same due-diligence standard as `fetch_verified_holdings.py`'s CSV
URLs. Deliberately small: this project's document corpus is scoped to the 5 issuer-verified UCITS
ETFs already in Tier 2 plus a hand-curated general regulatory set, not an open-ended crawl.

- **Fund-specific (7 PDFs):** one PRIIPS KID per verified ISIN (`IE00BYVJRR92`, `IE00BFNM3G45`,
  `IE00BDZZTM54`, `IE00BKVL7331`, `IE00B5BMR087`) plus 2 shared umbrella prospectuses (iShares IV
  plc covers SUAS/SASU — confirmed by cross-referencing Fidelity's factsheet URLs; SUSW/MVEA by
  inference from the same 2018-2019 SRI/ESG-factor product-launch wave, **not independently
  confirmed per-ISIN**; iShares VII plc covers CSSPX, confirmed via Yahoo Finance).
  **Note:** the EU PRIIPS KID already carries the SFDR sustainability summary for these Article 8
  products — there is no separate "SFDR pre-contractual annex" PDF to fetch per fund, contrary to
  an earlier planning assumption.
- **General regulatory (4 PDFs):** SFDR Regulation (EU) 2019/2088, SFDR RTS (EU) 2022/1288 (both
  EUR-Lex — the PDF export endpoint needs real `Accept`/`Accept-Language` headers or it returns a
  202 with an empty body), CSSF FAQ on SFDR, CSSF Circular 26/905 (the real underlying document
  behind "the CSSF's 2026 supervisory priorities in the area of sustainable finance," already
  cited conceptually in "Why this topic" above).

**No entity/relationship graph.** Full GraphRAG-style graph construction + community detection
(whether via Microsoft's `graphrag` library or a hand-rolled graph store) was evaluated and
deliberately not built — see `etl/extract_document_entities.py`'s module docstring. An
11-document corpus covering 5 known funds has no hidden entity structure worth discovering; the
real structure (which fund, which doc type, which regulation) is already known before ingestion
runs. Instead: lightweight LLM entity tagging per document (fund names, ISINs, regulation
references), stored as a searchable field in Azure AI Search.

**Document size cap.** The umbrella prospectuses are full legal documents covering dozens of
sub-funds beyond the 5 this project tracks — one alone extracted to 2.85M characters / 2907
chunks before capping. `extract_document_entities._MAX_DOCUMENT_CHARS = 60_000` bounds every
document's contribution, same portfolio-scale-cap philosophy as `etl_agent._GLEIF_LOOKUP_LIMIT`.

**Not yet live.** Azure AI Search + the embedding deployment are authored in Bicep but not
deployed (`infra/README.md`'s Phase 8 note) as of Phase 8a-8d. `etl_agent.run_document_ingestion()`
is verified locally against real fetched PDFs, real Azure OpenAI entity extraction, and real
Postgres, with fakes only for the not-yet-deployed Search/embedding clients — see
docs/PROGRESS_LOG.md's Phase 8a/8b entries for the verification detail.

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
