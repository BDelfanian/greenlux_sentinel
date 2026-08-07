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
      search_lu_entities); called by `agents/etl_agent.py`'s `cross_check_lu_entities()` as of
      Phase 5
- [x] `powerbi_server` — implemented against the real Power BI REST API surface
      (service-principal auth via azure-identity), request shaping unit-tested via
      httpx.MockTransport; **not** live-verified — no Power BI workspace/service principal is
      provisioned yet (that happens in Phase 4)

## Phase 4 — BI + reporting

- [x] Power BI dataset connected to Postgres/Cosmos outputs — a push dataset (`Funds` +
      `FundRiskScores` tables, one relationship on `fund_id`) in a Power BI workspace, seeded
      with real rows pulled live from the local Postgres `funds`/`fund_risk_scores` tables. Not
      an auto-refreshing pipeline (out of scope for this portfolio project) — see
      docs/PROGRESS_LOG.md for the full provisioning story and its IDs
- [x] Dashboard Agent: NL question → DAX query template selection → Power BI MCP call —
      live-verified end to end (real Azure OpenAI classification + real `executeQueries` calls
      against the live dataset via the actual service-principal auth path), plus unit tests
- [x] Report Agent: multilingual (EN/FR/DE) draft generation + citation trail — tool-sourced-
      numbers guardrail enforced (with one retry) before a draft is returned; unit tested
- [x] Report human-approval gate wired to a real "publish" action — `publish_report()`/
      `reject_report()` re-check every language row is still `draft` before acting, same
      non-bypassable pattern as `query_optimizer_agent.apply_approved()`

## Phase 5 — Azure deployment

- [x] Bicep IaC for the full service map in [ARCHITECTURE.md](ARCHITECTURE.md#azure-service-map)
      (`infra/main.bicep` + `infra/modules/*.bicep`, one module per resource) — **live-deployed**
      to `rg-greenlux-sentinel` in `Subscription_greenlux` (`francecentral`); five real bugs found
      and fixed against the live subscription (wrong Azure OpenAI SKU, an ACR-registry/AcrPull
      role-assignment ordering problem, a wrong role-definition GUID) — see docs/PROGRESS_LOG.md
      for the full story
- [x] CI/CD via GitHub Actions (`.github/workflows/ci.yml` — ruff + pytest on push/PR; no deploy
      job yet, by deliberate scope choice, not a blocker — see docs/PROGRESS_LOG.md)
- [x] Secrets in Key Vault, no local `.env` in any deployed path — **live-verified**: the deployed
      Container App reads `postgres-password`/`cosmos-key`/`azure-openai-api-key`/`api-auth-token`
      from `kv-greenlux-dev-idckowud` via its own managed identity, confirmed by real end-to-end
      API calls (see below). Found and fixed a real bug in this path: `config.py`'s Key Vault
      overlay crashed entirely if any one of its 6 mapped secrets was missing, which would have
      taken down every agent endpoint on the live deployment the moment
      `langchain-api-key`/`powerbi-client-secret` (deliberately never auto-populated) were
      touched — now skips missing secrets instead of aborting; `tests/test_config.py` added
- [x] Azure Monitor/Log Analytics wired alongside the Postgres audit log
      (`infra/modules/log-analytics.bicep` — live, `log-greenlux-dev` + `appi-greenlux-dev`)

- [x] Agent API (`src/greenlux_sentinel/api/app.py`) — **live and verified end to end**: built,
      pushed to `greenluxacrdevidckowude2cgc.azurecr.io`, and running on the deployed Container
      App. Real calls against real live data: `POST /risk/0P0001EVL3` → a correctly computed risk
      score with a real holdings-driven explanation (live Postgres + Cosmos); `POST /sql` → a
      real Azure-OpenAI-generated query against live Postgres returning `36413` LU-domiciled
      funds; an unauthenticated call to the same route correctly returned `401`
- [x] ETL Agent implemented for real (`agents/etl_agent.py`) and **run live against Azure**:
      67,098 funds loaded into the live Postgres, 99 Top-100 + 5 verified holdings docs into live
      Cosmos, 22 LU management companies matched against live GLEIF, 19 real risk scores computed
      via `risk_agent.score_all_verified()`. Still deliberately not a `supervisor.py` graph
      node — invoked via the Agent API's `/etl/run` and the Functions timer trigger
      (`function_app.py`, not yet itself deployed — see below)
- [x] Azure Container Registry (`infra/modules/container-registry.bicep`) — live, passwordless
      `AcrPull` via the Container App's managed identity confirmed working (image pull succeeded)

- [x] Functions timer trigger **live and registered**: `func-greenlux-etl-dev-idckowude2cgc`'s
      `scheduled_etl_run` shows up in the live host's own `/admin/functions` with the correct
      `timerTrigger` binding, confirmed against the running instance directly (not just ARM's
      view, which lagged repeatedly during this work). Getting there took six distinct real bugs
      (zip path separators, `-e .` not surviving Oryx, a vendored folder Oryx silently dropped,
      pip's cwd-relative local-path resolution, unreliable restart/stop-start recycling, and
      per-package manylinux tag mismatches for compiled dependencies) — full story in
      docs/PROGRESS_LOG.md. The working, reproducible build lives in
      `scripts/build_function_package.py`; Oryx remote build is now explicitly disabled
      (`SCM_DO_BUILD_DURING_DEPLOYMENT`/`ENABLE_ORYX_BUILD` = `'false'` in `functions.bicep`, so a
      future Bicep redeploy doesn't silently re-enable it).
- [x] APIM real API import — `apim.bicep` imports the live Container App's own
      `/openapi.json` (FastAPI serves it for free); all 11 real routes confirmed via
      `az apim api operation list`, and a real request through the actual gateway URL
      (`https://apim-greenlux-dev-idckowude2cgc.azure-api.net/agents/healthz`) succeeded.
- [x] `etl_agent.run_ingestion()`'s `data_dir` gap closed — `_resolve_data_dir()` falls back to
      downloading the ADLS Gen2 landing container (`Storage Blob Data Reader` managed-identity
      RBAC, no storage keys) when local `data/raw/` isn't present. **Live-verified with a genuine
      success, not just a non-crashing deploy**: manually invoked the deployed Function App via
      its admin API and confirmed via Application Insights — `"Executed
      'Functions.scheduled_etl_run' (Succeeded, ..., Duration=26169ms)"`, `"ETL run complete:
      {'funds_loaded': 67098, 'top100_holdings_docs': 99, 'verified_holdings_docs': 5,
      'gleif_matched': 22}"` — from a cold, data-less deployment, matching the original manual
      seeding numbers exactly. Getting there surfaced three more real bugs (an ADLS Gen2
      directory-placeholder collision, a `config.py` field name that didn't match the
      `LANDING_STORAGE_ACCOUNT_NAME` env var anywhere it was set, and an incomplete guessed
      dependency list for `mcp`'s `--no-deps` install) — see docs/PROGRESS_LOG.md.

- [x] Cleanup: the now-redundant `greenlux-openai` resource in the old `Azure for Students`
      subscription — deletion was blocked when attempted via Claude Code (its permission
      classifier requires direct tool-level approval for destructive Azure operations); the user
      ran `az cognitiveservices account delete` themselves and confirmed via
      `az cognitiveservices account show` returning `ResourceNotFound`.

- [x] Deploy-on-merge CI (`.github/workflows/deploy.yml`) — app-level deploys only (agent API
      image + Container App, ETL Function App package), deliberately excluding `infra/*.bicep`
      changes (that would need `User Access Administrator` + Key Vault read, a materially bigger
      grant than what was agreed — see docs/PROGRESS_LOG.md). OIDC via a user-assigned managed
      identity (Entra app registration is blocked for this tenant's accounts — same restriction
      hit in Phase 4's Power BI provisioning), RBAC scoped to the exact two compute resources +
      `AcrPush` on the registry, gated by a GitHub Environment requiring manual approval before
      the job runs.

**Phase 5 is now fully closed** — every item above is live-verified against the real deployed
environment, not just written or deployed without crashing.

## Phase 6 — Polish for portfolio presentation

- [ ] README architecture diagram matches what's actually built
- [ ] Short demo video/GIF
- [ ] Sanity pass on [REQUIREMENTS_TRACEABILITY.md](REQUIREMENTS_TRACEABILITY.md) — every row still true
