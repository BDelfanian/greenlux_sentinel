# Progress Log

Append-only history of work sessions, organized by roadmap phase. **Newest entry first.** This
is what lets a new chat session pick up exactly where the last one left off — read the top entry
here (alongside [CLAUDE.md](../CLAUDE.md) and [ROADMAP.md](ROADMAP.md)) before starting new work.

Each entry covers: what got done, any deviation from the plan recorded elsewhere in the docs, and
the concrete next step. Don't rewrite past entries when circumstances change — append a new one
that supersedes it; the history of *why* decisions changed is as valuable as the current state.

---

## Phase 3 — MCP servers

**Completed:** 2026-08-06

**Done:**
- Implemented all four MCP servers for real, using the `mcp` Python SDK's `FastMCP` scaffolding
  (`mcp_servers/postgres_server.py`, `cosmos_server.py`, `gleif_server.py`, `powerbi_server.py`).
  Each follows the same two-layer shape: a plain, conn/container-injectable function that
  agents import and call in-process (keeps existing agent unit tests working unchanged against
  MagicMock connections, and lets a shared transaction span multiple calls — e.g.
  sql_agent.ask() reads then audit-logs then commits once), plus an `@mcp.tool()`-decorated
  wrapper with a JSON-only signature for when the module runs standalone via `serve()` (opens
  its own connection per call, since MCP tool arguments can't carry a live Connection/
  ContainerProxy object).
- Swapped the direct-SDK calls that map onto ARCHITECTURE.md's documented tool surface
  (`run_readonly_query`, `explain_query`, `propose_index`, `write_audit_log` for Postgres;
  `get_company_esg`, `query_esg_documents` for Cosmos) out of `sql_agent.py`, `risk_agent.py`,
  and `query_optimizer_agent.py` and into the new MCP server modules — validation/gate logic
  (SELECT-only regex, forbidden-keyword check, the `pending`-status re-check before DDL apply)
  stays exactly where it was, in the agents, per the brief.
- `gleif_server.py` live-verified against the real `api.gleif.org` (no key needed) — confirmed
  the actual response shape (`{"data": {...}}` for a single LEI lookup, `{"data": [...]}` for a
  filtered search; `attributes.entity.{legalName.name, legalForm.id, status,
  legalAddress.country}`) via `curl`, then again through `lookup_lei("Amundi")` and
  `search_lu_entities("FUND")`. Not yet called by any agent — `etl_agent.py` (its intended
  consumer) is still an unimplemented stub.
- `powerbi_server.py` implemented against the real Power BI REST API
  (`executeQueries`/`refreshes`, service-principal auth via `azure-identity`'s
  `ClientSecretCredential` — no new dependency needed) but **not** live-verified: no Power BI
  workspace or service principal is provisioned yet (that's Phase 4). Request shaping is
  unit-tested via `httpx.MockTransport`.
- Live end-to-end verification against the local Docker stack (Postgres + Cosmos emulator,
  which had been stopped since the last session): `sql_agent.ask()`, `risk_agent.
  score_all_verified()` (all 19 rows, same scores as Phase 2 — e.g. 0P00018CYB still 53.03),
  and `query_optimizer_agent.propose_index()` + `apply_approved()` (a real `CREATE INDEX
  idx_funds_management_company` landed in Postgres) all still work end to end through the new
  MCP-server wiring, with audit_log rows written via `postgres_server.write_audit_log`.
- 20 new unit tests (`test_postgres_server.py`, `test_cosmos_server.py`, `test_gleif_server.py`,
  `test_powerbi_server.py`) plus zero changes needed to the existing Phase 2 agent tests — the
  refactor was designed so the same MagicMock conn/container objects flow through unchanged.
  100 tests passing total (up from 80), ruff clean.

**Deviations from the original plan:**
- **Not every direct-SDK call moved behind an MCP tool** — only the ones that map onto
  ARCHITECTURE.md's documented tool list did. Left as direct psycopg calls, deliberately:
  `risk_agent.persist()`'s `fund_risk_scores` INSERT (this agent's own output write; no generic
  "write" MCP tool exists by design — inventing one would be exactly the "arbitrary write
  exposed as a tool" anti-pattern ARCHITECTURE.md warns against), `risk_agent`'s
  `fund_id`→isin and isin→claims lookups (hardcoded, non-analyst-facing reads specific to this
  agent's own workflow, not the dynamic LLM-generated SQL `run_readonly_query` exists for),
  `query_optimizer_agent._existing_indexed_columns()` (pg_indexes catalog introspection), and
  `_fetch_pending_proposal()`/`reject_proposal()`/`apply_approved()`'s DDL execution (the
  human-gate's own state machine — deliberately kept off the LLM-reachable tool surface, same
  reasoning Phase 2 already applied to keeping DDL-apply out of any tool). If this needs
  revisiting, `postgres_server.py`'s module docstring and the per-function docstrings in
  `risk_agent.py`/`query_optimizer_agent.py` explain the reasoning inline.
- **The local Cosmos DB emulator has no committed database/container provisioning step
  anywhere in the repo.** Phase 2's "data already loaded" note assumed the container survives a
  `docker compose up -d` restart; in practice the vnext-preview emulator's storage is ephemeral
  across a container stop/start (not just a full recreation), so this session's first Cosmos
  query failed with a generic `PostgresError` from the emulator's own Postgres-backed engine
  (not a clean 404 — worth knowing if this comes up again) until the database/container were
  (re)created ad hoc via `create_database_if_not_exists`/`create_container_if_not_exists` and
  the two `etl.load_*_cosmos` loaders re-run. Not fixed as a committed script this session
  (out of Phase 3's scope) — worth a small `etl/setup_cosmos.py` in a future session if this
  friction recurs.
- `gleif_server`'s `search_lu_entities` filters on GLEIF's `entity.category` field (e.g.
  `'FUND'`) rather than `entity.legalForm.id` — the latter is an opaque ELF code (e.g. `'8888'`
  for a Luxembourg sub-fund), not a human-readable entity-type string, so `category` is the
  more usable filter for this tool's signature. Confirmed live that `filter[entity.category]`
  is a supported GLEIF query parameter.

**Live local environment:** same as Phase 2's note, plus: this session's Docker Desktop restart
required manually recreating the Cosmos database/container (see deviation above) before the
`etl.load_esg_cosmos`/`etl.load_verified_holdings_cosmos` reload would work — a fresh session
should expect to need the same two steps if the Cosmos container was stopped since the data was
last loaded, not only on a full `docker compose down -v`.

**Next step:** Phase 4 — BI + reporting. Provision a real dev Power BI workspace/dataset and
service principal (unblocks live-verifying `powerbi_server.py` for the first time) and start on
the Dashboard Agent (NL question → DAX query, via `powerbi_server.run_dax_query`) and the Report
Agent (multilingual EN/FR/DE draft generation + citation trail, gated on human approval per
RESPONSIBLE_AI.md — this is the second and last human-in-the-loop gate the project needs).
Wire whichever of these lands first into `supervisor.py`'s graph alongside the three Phase 2
specialists.

---

## Phase 2 — Core agents

**Completed:** 2026-08-06

**Done:**
- Installed Docker Desktop (via winget) — unblocked the Phase 0/1 "no Docker available"
  assumption. `docker-compose.yml` runs Postgres 16 + the Cosmos DB NoSQL emulator
  (`vnext-preview` image), schema auto-initialized from `db/schema.sql` +
  `db/audit_log_schema.sql`.
- Ran `load_funds_postgres.py` and `load_esg_cosmos.py` live for real (Phase 1's last open
  item) — 67,098 funds into Postgres, 99 ETF docs into Cosmos. Found and fixed a real bug while
  doing so: a missing `industry` cell in the ESG ratings CSV produced a Python float `NaN` that
  `json.dumps` renders as the invalid JSON literal `NaN`, which Cosmos rejects outright
  ("Failed to parse Json request") — fixed in `load_esg_cosmos.py`'s `transform()` with a
  `pd.notnull` sweep before dict conversion; regression test added.
- Provisioned a real Azure OpenAI resource (`greenlux-openai`, `rg-greenlux-sentinel`,
  francecentral, on the user's "Azure for Students" subscription) via `az` CLI, with a
  `gpt-5-mini` / `GlobalStandard` deployment (the originally-planned `gpt-4o-mini` is deprecated
  and unavailable for new deployments as of this session's date).
- **Discovered and fixed a foundational data-linkage gap** (see Deviations) — added
  `etl/fetch_verified_holdings.py` and `etl/load_verified_holdings_cosmos.py`, five real UCITS
  ETFs loaded live into Cosmos, unit-tested.
- Implemented and live-verified all three Phase 2 agents plus the supervisor:
  `agents/risk_agent.py`, `agents/sql_agent.py`, `agents/query_optimizer_agent.py`,
  `agents/supervisor.py` (LangGraph `StateGraph`). Every one of them was exercised against the
  real live Postgres/Cosmos/Azure OpenAI stack, not just unit tests with fakes.
- Enabled LangSmith tracing end to end — signed up for a LangSmith account, wired the API key,
  and discovered/fixed a second real gotcha: the account's workspace is EU-hosted, and the SDK
  defaults to the US endpoint (`api.smith.langchain.com`), which 403s for an EU key. Added
  `langchain_endpoint` to `config.py` (default `eu.api.smith.langchain.com`) and confirmed via
  the LangSmith API that a real trace landed.
- 80 unit tests passing (up from 19 at the end of Phase 1), ruff clean.

**Deviations from the original plan:**
- **The Tier 2 "Top 100 ETF holdings" Kaggle dataset cannot support the risk-score formula.**
  Discovered that all 99 ETFs in it (VOO, SPY, VTI, sector SPDRs, Treasury/bond ETFs, etc.) are
  plain US-listed index/bond trackers: zero overlap with Tier 1's Morningstar **European** funds
  table (0/99 by ticker — different market entirely) and no sustainability claim of their own.
  CLAUDE.md decision #2 had assumed Tier 2 was "a narrower set" of Tier 1; Phase 1's profiling
  never actually checked that (it only checked Tier-2-internal overlap between holdings tickers
  and ESG-ratings tickers), so the false assumption survived until risk_agent implementation
  forced the question. Fixed by fetching real, current, issuer-published holdings (free,
  no-auth CSV export from each fund's public iShares product page) for five UCITS ETFs that
  *are* real Tier 1 rows, chosen for strong overlap with the US-centric ESG ratings dataset
  (52-84% by weight, vs. ~14% for the original set). Full writeup, the five ISINs, and the
  ratings/scores involved: [DATA.md](DATA.md#tier-2-verified-holdings-phase-2-correction). The
  original Top 100 Kaggle set stays loaded as a separate, explicitly-unlinked descriptive
  dataset, not used for scoring.
- The Greenwashing Risk Score formula ended up more concrete than DATA.md's abstract
  `f(claimed, holdings_implied)`: claimed rating (1-5 globes) rescales to a 0-100 "claimed
  quality" scale; the raw ~600-1536 weighted company-ESG score rescales to 0-100 using the
  *observed* min/max across the 722-company ESG ratings population (not a theoretical ceiling —
  re-derive if that source dataset changes); the score is `max(0, claimed - holdings_implied)`,
  clamped at 0 so a fund whose real holdings beat its claim isn't scored as "negative risk." See
  `agents/risk_agent.py` module docstring.
- `gpt-4o-mini` (the model named in earlier planning) is deprecated for new deployments as of
  this session — used `gpt-5-mini` instead (real quota available, `GlobalStandard` SKU,
  `francecentral`).
- Query-optimizer's human-approval gate reuses `audit_log`'s existing `approval_status` columns
  rather than a new table — RESPONSIBLE_AI.md already specified those columns for exactly this
  purpose, and a dedicated table would have duplicated it for no benefit at this scale.
- Supervisor only wires the three specialists actually implemented this phase (sql/risk/
  query_optimizer). etl_agent/dashboard_agent/report_agent remain `NotImplementedError` stubs —
  ARCHITECTURE.md's six-agent graph is the end state, not a Phase 2 deliverable.
- **None of the five verified Tier 2 funds are Luxembourg-domiciled** (all five ISINs are `IE`-
  prefixed, chosen because iShares publishes a trivially scriptable public holdings CSV). Tier 1
  as a whole and the GLEIF LU grounding still carry the project's Luxembourg framing untouched,
  but the risk-score demo itself doesn't showcase a real LU fund. Checked Amundi
  (`LU1861136247`) and BNP Paribas (`LU1291103338`) — both are real LU-domiciled funds with the
  same strategy already present in Tier 1, but neither exposes an iShares-style static CSV
  export (Amundi's holdings load from a private API not in the static HTML; no CSV/XLSX link
  found for BNP Paribas). Not fixed — would need a headless browser, a paid data provider, or
  contacting the issuer directly. Full detail:
  [DATA.md](DATA.md#tier-2-verified-holdings-phase-2-correction) (see "Known limitation").

**Live local environment, ready for a fresh session to resume against:** Docker Desktop is
installed and `docker-compose up -d` starts Postgres (`localhost:5432`) + the Cosmos emulator
(`localhost:8081`) with data already loaded (67,098 Tier 1 funds, 99 Top-100 ETF docs, 5 verified
Tier 2 docs, 19 `fund_risk_scores` rows). `.env` has live Azure OpenAI (`greenlux-openai`,
`gpt-5-mini`) and LangSmith credentials already filled in — nothing needs re-provisioning to keep
building. If the containers aren't running, `docker compose up -d` from the repo root brings them
back (data persists in the `postgres_data` named volume; Cosmos emulator data does not persist
across container recreation — re-run the two `etl.load_*` calls and `etl.load_verified_holdings_cosmos`
if the Cosmos container was recreated).

**Next step:** Phase 3 — MCP servers. Wrap the direct-SDK calls in `sql_agent.py` (Postgres),
`risk_agent.py` (Postgres + Cosmos), and `query_optimizer_agent.py` (Postgres) behind
`postgres_server`/`cosmos_server` MCP tools per ARCHITECTURE.md, without changing the validation/
gate logic that already lives in the agents. `gleif_server` and `powerbi_server` still need their
first real implementation (currently empty stubs). Optionally, revisit the LU-domicile limitation
above if a real Luxembourg-fund holdings source turns up.

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
