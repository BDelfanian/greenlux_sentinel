# Roadmap

Phased so each milestone produces something runnable/demoable, not a big-bang integration at the
end. Check items off as they land; don't mark a phase done until its own checklist is clean.

## Phase 0 — Scaffolding (current)

- [x] Local repo + folder structure
- [x] Documentation set (this file and its siblings)
- [x] GitHub remote created and pushed
- [x] `pyproject.toml` dependencies pinned to real versions

## Phase 1 — Data profiling & ingestion

- [x] Download all three Kaggle datasets, confirm actual columns against [DATA.md](DATA.md)
      (real files in `data/raw/`, profiled in `notebooks/01_data_profiling.ipynb` — see
      [DATA.md](DATA.md#first-milestone-data-profiling) for what changed vs. the original
      best-guess schema)
- [x] Profile ticker overlap between ETF holdings and company ESG ratings datasets
      (real overlap: ~14% of unique holding tickers, 0–90.3% per-ETF, median 16% — much lower
      than the ~79% used in early synthetic fixtures; see DATA.md)
- [x] Finalize Postgres schema (`db/schema.sql`) based on confirmed columns — reconciled
      against the real Morningstar export (dropped sharpe/treynor/alpha/beta, which don't
      exist in the real data; added domicile/management_company derivation + E/S/G subscores,
      which do)
- [x] ETL Agent: load Morningstar funds → Postgres (`etl/load_funds_postgres.py`, transform
      logic unit-tested and smoke-tested against the full real 67k-row export; upsert path
      unit-tested via injected connection — not yet run against a live Postgres instance)
- [x] ETL Agent: reshape + load ETF holdings/company ESG → Cosmos DB
      (`etl/load_esg_cosmos.py`, same caveat — unit- and smoke-tested against the full real
      132k-row holdings file, not yet run against live Cosmos DB)
- [x] Audit log table live and being written to from the first ETL run (`db/audit.py`,
      called from both loaders; verified via unit test, not a live DB)

**Still open before Phase 1 is fully done:** an actual Postgres/Cosmos instance (local emulator
or Azure) to run `load()` against for real, rather than just unit/smoke-testing the transform
logic. No Docker was available in the dev environment used so far — see Phase 2 below.

## Phase 2 — Core agents

- [x] Local Postgres + Cosmos DB NoSQL emulator running in Docker (`docker-compose.yml`) —
      Docker Desktop was successfully installed this phase, unblocking the Phase 0/1 assumption
      that it wasn't available
- [x] NL2SQL Agent against local Postgres (`agents/sql_agent.py`) — Azure OpenAI (`gpt-5-mini`)
      generating schema-constrained SQL, validated single-SELECT + forbidden-keyword checks,
      executed in a native Postgres read-only transaction; verified live against real data and
      a live prompt-injection attempt (blocked by Azure content filtering, then would have been
      blocked again by our own validation)
- [x] Query-Optimizer Agent + human-approval gate (`agents/query_optimizer_agent.py`) — real
      gate, not simulated: proposals queue as `pending` rows in `audit_log`, `apply_approved()`/
      `reject_proposal()` re-check `pending` before acting (blocks double-apply), verified live
      end to end including an actual `CREATE INDEX` landing in Postgres
- [x] Greenwashing-Risk Agent producing a real score (`agents/risk_agent.py`) — see the Tier 2
      data-linkage correction below; scores 19 real fund_id rows (5 verified ISINs) live
- [x] LangGraph supervisor wiring the three implemented specialists (`agents/supervisor.py`) —
      LLM-based routing to sql/risk/query_optimizer; etl/dashboard/report agents stay
      unimplemented stubs, not yet graph nodes (deferred to Phase 3/4)
- [x] LangSmith tracing enabled end to end — EU-hosted workspace needs `LANGCHAIN_ENDPOINT`
      pointed at `eu.api.smith.langchain.com` (SDK defaults to the US endpoint); verified via
      the LangSmith API that a live trace landed

**Major deviation from the original plan** — the Tier 2 "Top 100 ETF holdings" dataset had zero
overlap with Tier 1 and no fund of its own carried a sustainability claim, so the risk-score
formula was uncomputable for any fund in it. Fixed by pulling real, issuer-published holdings for
five UCITS ETFs that *are* in Tier 1 (`etl/fetch_verified_holdings.py`,
`etl/load_verified_holdings_cosmos.py`) — see
[DATA.md](DATA.md#tier-2-verified-holdings-phase-2-correction) and CLAUDE.md decision #2's
correction note for the full story.

## Phase 3 — MCP servers

- [x] `postgres_server`, `cosmos_server` implemented and swapped in for direct SDK calls —
      sql_agent.ask(), risk_agent's Cosmos lookup, and query_optimizer_agent's explain/propose
      paths now call through these modules; live-verified end to end against the local stack
      (see docs/PROGRESS_LOG.md)
- [x] `gleif_server` — live API integration, verified live against api.gleif.org (lookup_lei,
      search_lu_entities); not yet called by any agent (etl_agent is still a stub)
- [x] `powerbi_server` — implemented against the real Power BI REST API surface
      (service-principal auth via azure-identity), request shaping unit-tested via
      httpx.MockTransport; **not** live-verified — no Power BI workspace/service principal is
      provisioned yet (that happens in Phase 4)

## Phase 4 — BI + reporting

- [ ] Power BI dataset connected to Postgres/Cosmos outputs
- [ ] Dashboard Agent: NL question → DAX query → live dashboard update
- [ ] Report Agent: multilingual (EN/FR/DE) draft generation + citation trail
- [ ] Report human-approval gate wired to a real "publish" action

## Phase 5 — Azure deployment

- [ ] Bicep IaC for the full service map in [ARCHITECTURE.md](ARCHITECTURE.md#azure-service-map)
- [ ] CI/CD via GitHub Actions
- [ ] Secrets in Key Vault, no local `.env` in any deployed path
- [ ] Azure Monitor/Log Analytics wired alongside the Postgres audit log

## Phase 6 — Polish for portfolio presentation

- [ ] README architecture diagram matches what's actually built
- [ ] Short demo video/GIF
- [ ] Sanity pass on [REQUIREMENTS_TRACEABILITY.md](REQUIREMENTS_TRACEABILITY.md) — every row still true
