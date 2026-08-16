# Roadmap

Phased so each milestone produces something runnable/demoable, not a big-bang integration at the
end. Check items off as they land; don't mark a phase done until its own checklist is clean.

## Phase 0 — Scaffolding

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
      hit in Phase 4's Power BI provisioning), RBAC scoped to the exact compute resources touched
      (including the Function App's App Service Plan, not just the site — see
      docs/PROGRESS_LOG.md for why that distinction mattered) + `AcrPush` on the registry, gated by
      a GitHub Environment requiring manual approval before the job runs. **Verified with a real
      `push`-triggered run that went green end-to-end**, not just written and assumed to work.

**Phase 5 is now fully closed** — every item above is live-verified against the real deployed
environment, not just written or deployed without crashing.

## Phase 6 — Polish for portfolio presentation (complete)

- [x] README architecture diagram matches what's actually built
- [x] Short demo video/GIF
- [x] Sanity pass on [REQUIREMENTS_TRACEABILITY.md](REQUIREMENTS_TRACEABILITY.md) — every row still true

All six original roadmap phases are complete. Phase 8 (document evidence + multi-hop
orchestration) has 8a-8d built and verified locally; 8e (live Azure deployment) is the remaining
step — see below and docs/PROGRESS_LOG.md's top entry.

## Phase 8 — Document evidence agent (CLAUDE.md decision #4 reversal)

- [x] **8a — document sourcing + ingestion pipeline.** 11 real, live-verified PDFs (5 fund
      KIIDs/PRIIPS-KIDs + 2 shared umbrella prospectuses for the 5 issuer-verified ETFs, plus
      SFDR Reg 2019/2088, SFDR RTS 2022/1288, CSSF FAQ on SFDR, CSSF Circular 26/905) fetched by
      `etl/fetch_fund_documents.py`. Entity tagging via the existing Azure OpenAI chat model
      (`etl/extract_document_entities.py`) — **not** the Microsoft `graphrag` library (dropped
      after a real Windows packaging blocker; see docs/PROGRESS_LOG.md) and **not** a hand-rolled
      graph database (deliberately scoped down for an 11-document corpus — see that entry too).
      `etl/load_documents_search.py` embeds + indexes into Azure AI Search. New
      `document_citations` Postgres table. Azure AI Search + a second OpenAI embedding deployment
      authored in Bicep, **not deployed** (infra/README.md's Phase 8 note).
- [x] **8b — evidence agent.** `mcp_servers/search_server.py` (hybrid search, OR-shaped
      fund/regulatory filter), `guardrails/grounding.py` (Principle 5: cite a retrieved doc or
      abstain), `agents/evidence_agent.py`, `POST /evidence`. 24 new tests, 190 total passing.
      Live-verified against real local Postgres + real Azure OpenAI chat calls (fake search
      client, since Azure AI Search isn't deployed yet): correct cited answers on
      directly-answerable questions, clean abstention (no crash) on interpretive questions the
      evidence doesn't settle and on empty retrieval, and real `document_citations` rows
      persisted.
- [x] **8c — multi-hop supervisor rewrite.** `agents/supervisor.py`: new `SupervisorState` fields
      (`plan`, `hop_results`, `hop_errors`, `trace`, `final_answer`), a `multi_hop` route (planner
      → dispatch loop → synthesize) plus a new single-hop `evidence` route, `POST /ask` is the
      only reachable entry point for `multi_hop` (dedicated routes bypass the graph, unaffected).
      25 new tests (46 total in `test_supervisor.py`), 215 passing repo-wide. Live-verified via a
      restarted local uvicorn: the 6 pre-existing routes still work unchanged through the
      rewritten graph (real risk-score call confirmed), and a real multi-hop request correctly
      LLM-routed to `multi_hop`, planned `["evidence"]`, dispatched it, and failed at the exact
      expected point (undeployed Azure AI Search) with a clean structured error, not a crash.
- [x] **8d — UI + full documentation pass.** `ui/`'s `agent-api.ts` (`DocumentCitation`,
      `evidence`/`multi_hop` route types, `plan`/`hop_results`/`trace`/`final_answer` fields) and
      `ResultView.tsx` (`EvidenceResult`, `MultiHopResult`) — type-checked, production build
      clean, and live-verified via real browser-equivalent form POSTs (same technique as Phase
      7's verification): correct route labels, correct citation/abstention rendering, correct
      plan/hop-trace rendering, all reaching the same expected undeployed-Azure-Search error as
      the API itself. Full documentation pass: CLAUDE.md decision #4's reversal write-up (+ #5,
      #6 updates), ARCHITECTURE.md's agent graph/MCP servers/API routes/differentiation table,
      DATA.md's new "Document corpus (Phase 8)" section, README.md's differentiation section,
      REQUIREMENTS_TRACEABILITY.md's non-goals (marked superseded, not deleted).
- [x] **8e — live Azure deployment.** Azure AI Search + embedding deployment provisioned, real
      document ingestion run against the live index (411 chunks), the agent API redeployed with
      Phase 8 code via the deploy-on-merge CI, one real production bug found and fixed (the
      `document_citations` table existed locally but was never applied to live Postgres — fixed
      via Azure Cloud Shell once a direct connection from the local machine proved
      firewall-blocked), and `/evidence`/multi-hop `/ask` fully live-verified over the public
      internet, including two independent real SQL-guardrail rejections handled gracefully by the
      multi-hop dispatcher across separate runs.
- [x] **Portfolio polish — operator UI live deployment + new demo GIF.** The UI itself had only
      ever run via `npm run dev` locally; now deployed as a second Container App
      (`infra/modules/container-apps-ui.bicep`), live-verified over the public internet, with a
      new demo GIF captured via Playwright against the real live deployment (not staged, not a
      terminal-transcript workaround). See docs/PROGRESS_LOG.md's top entry.

## Phase 7 — Operator UI (Next.js)

- [x] CLAUDE.md decision #5 ("no chat frontend") reversed at the user's explicit request —
      recorded with rationale in CLAUDE.md itself, not silently changed; ARCHITECTURE.md,
      REQUIREMENTS_TRACEABILITY.md, and README.md's differentiation-from-agentic-rag-lu language
      updated to match (see docs/PROGRESS_LOG.md for the full reasoning)
- [x] `/ask` endpoint added to the Agent API (`api/app.py`) — single free-text entry point that
      routes through `supervisor.build_graph()` and returns the route taken plus its full result;
      3 new tests in `tests/test_api.py`, all 40 tests (existing + new) pass
- [x] Next.js 16 / React 19 app scaffolded in `ui/` (App Router, TypeScript, Tailwind 4) — Server
      Actions call the Agent API server-side only, so `AGENT_API_TOKEN` never reaches the browser
      bundle
- [x] Route-specific result rendering for all five specialist agents: SQL (generated query +
      results table), risk (score + explanation + caveat), dashboard (DAX + results table),
      query-optimizer (proposed DDL + estimated improvement + human approve/reject gate),
      report (EN/FR/DE tabs + citations + human publish/reject gate) — plus a raw-JSON panel on
      every result for full transparency
- [x] **Live-verified end to end, not just built and assumed to work**: real form submissions
      (simulated via curl replicating the browser's no-JS progressive-enhancement POST, using the
      actual Server Action id extracted from the rendered page — not a mock) against the local
      stack. `sql` route: real Azure-OpenAI-generated query returned live Postgres rows, rendered
      in the results table. `risk` route: returned the real 53.03 score for `0P00018CYB`
      (iShares MSCI USA SRI UCITS ETF), rendered in the score view. `report` route: correctly
      classified and ran, and its real `tool_sourced_numbers` guardrail rejection (the LLM draft
      didn't pass the retry) surfaced as a clean error in the UI instead of crashing — proving the
      guardrail and the error-display path both work, not just the happy path.

**Deviation:** Node.js wasn't installed in this dev environment. `winget install OpenJS.NodeJS.LTS`
hung indefinitely waiting for an interactive UAC elevation prompt this non-interactive session
can't answer, so a portable (installer-free) Node.js zip was downloaded and extracted to
`C:\tools\node-v24.19.0-win-x64` and added to the user `PATH` instead — see docs/PROGRESS_LOG.md.

## Phase 9 — Tier 1 composition-anomaly ML model

- [x] `db/schema.sql`: 41 objective portfolio-composition columns added to `funds` (additive, no
      prior decision violated) + new `fund_sustainability_anomaly_scores` table
- [x] `etl/load_funds_postgres.py`: loader extended to map the 41 new columns
      (`COMPOSITION_COLUMNS`); fixture CSVs + `test_etl_transforms.py` extended to cover them
- [x] `ml/greenwashing_risk_model.py`: real implementation replacing the Phase 0-8 stub — a
      `RandomForestClassifier` predicting a fund's real claimed rating bucket from objective
      composition, `GroupShuffleSplit`-by-ISIN evaluation, `composition_anomaly_score`/tier via
      `predict_proba`, `save_model`/`load_model`. 16 new unit tests
      (`tests/test_ml_greenwashing_risk_model.py`), all pure/no-DB
- [x] `ml/train_greenwashing_risk_model.py`: runnable training entry point + `score_all_funds()`
      batch-scoring path (not yet called from anywhere — see below). **Run for real against the
      local `data/raw/*.csv` files (67,098 funds)**: group-split accuracy 90.9%, macro-F1 0.910 vs.
      a 38.4% baseline — see [DATA.md](DATA.md#tier-1-composition-anomaly-model-ml) for full
      metrics and the honest naive-vs-group-split comparison
- [x] `agents/sql_agent.py`: `fund_sustainability_anomaly_scores` added to `_SCHEMA_DDL` — the
      existing NL2SQL agent can already query this signal, no new agent/route needed
- [x] `notebooks/02_ml_model_worked_example.ipynb`: methodology walkthrough, real metrics, a
      concrete fund walkthrough (`0P00018CYB`) plus a contrasting flagged fund, and the Tier
      1-vs-Tier 2 cross-check — executed end to end against real data, not hand-typed numbers
- [x] Full documentation pass: CLAUDE.md (new decision #8), DATA.md (new section), ARCHITECTURE.md,
      REQUIREMENTS_TRACEABILITY.md, RESPONSIBLE_AI.md, README.md
- [ ] **Not done — wire into `etl_agent.run_ingestion()` and run `train_greenwashing_risk_model.
      main()` + `score_all_funds()` against live Azure Postgres.** No live Postgres/Cosmos
      credentials were available in the session that built this phase — the schema/loader/model
      code is real and unit-tested, but has only been trained/evaluated against the local,
      gitignored `data/raw/*.csv` files, matching the honesty pattern Phase 1 used for the same
      situation. Also not done this pass, by deliberate scope choice: a new LangGraph agent node
      or API route surfacing this signal directly (it's reachable today only via the NL2SQL agent
      once live data exists).

### Phase 9b — wire the ML signal into multi-hop synthesis

- [x] `agents/ml_risk_agent.py` (new) — Postgres-wired caller of
      `ml/greenwashing_risk_model.py`, mirroring `risk_agent.score_fund()`'s DI/persist/audit-log
      shape; loads the trained artifact once and caches it (no in-request training)
- [x] `agents/supervisor.py`: `ml_risk` added as a fourth plannable `multi_hop` hop
      (`_PLANNABLE_HOPS`, planner prompt, `dispatch()`, `_facts_from_hops()`) — deliberately kept
      under a distinctly-named fact (`composition_anomaly_score`, never merged with `risk`'s
      `greenwashing_risk_score`); deliberately **not** a new top-level route or REST endpoint
- [x] 11 new tests (4 in `test_ml_risk_agent.py`, 7 in `test_supervisor.py`, incl. a combined
      risk+ml_risk multi-hop case) — 245 total passing, `ruff check .` clean
- [x] `ui/`'s `ResultView.tsx` needed **no change** — its multi-hop plan/trace rendering is
      already generic over hop names, confirmed by reading it directly
- [x] Docs: CLAUDE.md (decision #6 + #8 updates), ARCHITECTURE.md (agent table + diagram),
      DATA.md, RESPONSIBLE_AI.md
- [ ] **Not live-verified** — same live-Postgres-backfill dependency as the Phase 9 item above,
      plus the model artifact itself would need to ship with the deployed container image (it's
      currently gitignored, trained on-demand locally only); neither attempted this session
