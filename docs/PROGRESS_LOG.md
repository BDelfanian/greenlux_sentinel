# Progress Log

Append-only history of work sessions, organized by roadmap phase. **Newest entry first.** This
is what lets a new chat session pick up exactly where the last one left off — read the top entry
here (alongside [CLAUDE.md](../CLAUDE.md) and [ROADMAP.md](ROADMAP.md)) before starting new work.

Each entry covers: what got done, any deviation from the plan recorded elsewhere in the docs, and
the concrete next step. Don't rewrite past entries when circumstances change — append a new one
that supersedes it; the history of *why* decisions changed is as valuable as the current state.

---

## Phase 1 — Data profiling & ingestion

**Completed:** 2026-08-06

**Done:**
- Reconciled `db/schema.sql`'s `funds` table against the real downloaded Morningstar CSVs
  (previously a best-guess placeholder from Phase 0).
- Rewrote `etl/load_funds_postgres.py` and `etl/load_esg_cosmos.py` with real `RAW_COLUMN_MAP`s,
  split into pure `transform()` (unit-tested) + `load()` (I/O, tested via injected fake
  connection/container). Both smoke-tested against the full real files (67k funds, 132k
  holdings), not just fixtures.
- Added `db/audit.py`, wired into both loaders so every load writes an audit_log row.
- Implemented `config.py` for real with `pydantic-settings` + an Azure Key Vault override path.
- Wrote and executed `notebooks/01_data_profiling.ipynb` against the real files — column sets,
  null rates, ISIN-derived domicile distribution, management_company heuristic hit-rate, Tier 2
  ticker overlap.
- Renamed the four downloaded Kaggle files to expressive, script-friendly names in `data/raw/`
  and documented the exact expected filenames in `data/README.md`.
- 19 unit tests passing (`tests/test_etl_transforms.py`, `tests/test_etl_load.py`), ruff clean.

**Deviations from the original plan:**
- No Kaggle API credentials or Docker were available in the working environment at the start of
  this phase. Per an explicit choice the user made when asked, small *synthetic* fixture CSVs
  (`tests/fixtures/`) were built first to unblock ETL development, clearly flagged as
  provisional. The user then manually downloaded the real Kaggle files mid-session; everything
  was reconciled against the real data before this phase was called done. The synthetic fixtures
  now mirror the real column shapes and remain in place as fast unit-test inputs — not a
  substitute for the real-data profiling, which did happen.
- The real Morningstar schema differs substantially from the Phase 0 best-guess: **no**
  `management_company`, `domicile`, `sharpe_ratio`, `treynor_ratio`, `alpha`, or `beta` column
  exists. `domicile_country` is now derived from the ISIN country prefix; `management_company` is
  a best-effort parse of `fund_name` (~44% coverage, kept nullable — not authoritative).
  `sharpe_ratio`/`treynor_ratio`/`alpha`/`beta` were dropped and replaced with the
  `return_3y`/`return_5y`/`return_10y`/`quarters_up`/`quarters_down` fields that actually exist.
- Real Tier 2 ticker overlap is **~14%** (590/4,229 unique holding tickers), far lower than the
  ~79% used in the early synthetic fixtures. Per-ETF coverage ranges 0–90.3%, median 16%; 35/99
  ETFs (bond funds) have zero overlap since the ESG ratings dataset only covers equities. This
  materially narrows the *usable* subset for the Phase 2 risk model — see
  [DATA.md](DATA.md#first-milestone-data-profiling) for the full breakdown and the recommendation
  to scope the risk model to the ≥50%-coverage equity ETFs (32/99) rather than all 99.
- The ESG ratings file's `total_score` is on a raw ~600–1536 scale, not 0–100 — flagged in both
  the notebook and the loader docstring so Phase 2 doesn't naively compare it to Tier 1's 0–100
  `sustainability_score` without normalizing first.

**Still open within this phase:** an actual Postgres/Cosmos instance to run `load()` against for
real — no Docker was available, so only the transform logic and the upsert *call shape* (via
injected fakes) are verified, not a live write.

**Next step:** Phase 2 — Core agents (LangGraph supervisor + specialists). Needs a decision on
how to get a local Postgres/Cosmos DB emulator running (Docker, or skip straight to a dev Azure
instance) before the ETL loaders or NL2SQL/risk agents can be exercised against live data instead
of mocks.

---

## Phase 0 — Scaffolding

**Completed:** 2026-08-06

**Done:**
- Pinned all `pyproject.toml` dependencies to real, current versions (added `pydantic-settings`,
  not in the original scaffold list).
- Created a local `.venv` (Python 3.12.10) and installed the project in editable mode with dev
  extras — first time the project was actually installed/importable.
- (Local repo, docs set, and GitHub remote were already in place before this session — see
  git history.)

**Deviations from the original plan:**
- `python`/`python3` were not resolvable on PATH in this environment (Windows Store alias
  stubs) — the real Python 3.12 interpreter was found at an explicit path under
  `AppData\Local\Programs\Python\Python312` and used directly to create the venv.
- No Docker was available in this environment, which blocks the "local Postgres/Cosmos emulator"
  assumption in Phase 2 of the roadmap — flagged for a decision when Phase 2 starts.

**Next step:** Phase 1 — data profiling & ingestion.
