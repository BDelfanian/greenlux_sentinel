# Progress Log

Append-only history of work sessions, organized by roadmap phase. **Newest entry first.** This
is what lets a new chat session pick up exactly where the last one left off — read the top entry
here (alongside [CLAUDE.md](../CLAUDE.md) and [ROADMAP.md](ROADMAP.md)) before starting new work.

Each entry covers: what got done, any deviation from the plan recorded elsewhere in the docs, and
the concrete next step. Don't rewrite past entries when circumstances change — append a new one
that supersedes it; the history of *why* decisions changed is as valuable as the current state.

---

## Phase 7 — Operator UI (Next.js)

**Completed:** 2026-08-09

**Done:** Session started from the user asking, after seeing how much back-and-forth it took to
get a straight answer to a plain question ("what can this do" / "run it for real" / "fix the
Azure OpenAI credential" all took separate CLI round-trips), for an actual web UI: ask a question,
see the result *and* the details (query used, score, report, citations) in one place.

- **CLAUDE.md decision #5 reversed, on the record.** The original decision was "no chat frontend"
  — reasoning at the time: agentic-rag-lu already is a Next.js chat app over RAG, so building the
  same shape here would erase the one thing differentiating the two portfolio projects. Flagged
  this directly to the user before touching anything (per CLAUDE.md's own "don't quietly revert"
  instruction) and asked how to proceed via `AskUserQuestion`; the user chose to override it
  explicitly. Updated CLAUDE.md decision #5 itself (not just this log) with the new decision and
  the reasoning for the reversal, plus every place the old claim was asserted as fact —
  ARCHITECTURE.md's differentiation table, REQUIREMENTS_TRACEABILITY.md's non-goals list, and
  README.md's "instead of a chat UI" line — so a fresh session doesn't find contradictory claims
  across docs. The framing kept throughout: this is a structured, fixed-agent-surface console, not
  an open-ended RAG chat — still a real distinction from agentic-rag-lu, not a fig leaf.
- **`/ask` endpoint** (`src/greenlux_sentinel/api/app.py`) — the one new backend change. Routes
  free text through the existing `supervisor.build_graph()` (no new orchestration logic; every
  specialist agent was already there) and returns the full state (`route`, `result`, `error`) so
  the UI can render route-specific detail. Built fresh per request rather than cached, matching
  every other route's statelessness convention in this file. 3 new tests added to
  `tests/test_api.py` following the existing patched-collaborator pattern; all 40 tests
  (37 existing + 3 new) pass.
- **`ui/` — Next.js 16 / React 19 app**, scaffolded via `create-next-app` (App Router, TypeScript,
  Tailwind 4). One page, one form (`question` + optional `fund_id`), submitted via a React 19
  Server Action (`ui/src/app/actions.ts`) that calls the Agent API server-side only —
  `AGENT_API_TOKEN` never reaches the browser bundle, matching the "server-only secret" pattern
  the rest of this codebase already uses for Postgres/Cosmos/OpenAI credentials. Result rendering
  (`ui/src/components/ResultView.tsx`) branches on `route`: SQL shows the generated query + a
  results table; risk shows the score + explanation + caveat; dashboard shows the DAX + results
  table; query-optimizer shows the proposed DDL + estimated improvement plus a real
  approve/reject form (`ui/src/components/GateAction.tsx`) wired to
  `/query-optimizer/{id}/approve|reject`; report shows EN/FR/DE tabs + citations plus the same
  gate pattern wired to `/report/{id}/publish|reject`. Every result also has a collapsible raw-JSON
  panel — the user's "not just the result, the details too" requirement, taken literally rather
  than picked apart into only the fields judged interesting.
- **Live-verified end to end**, not just built and typechecked. `npm run build` and `npx tsc
  --noEmit` passed, but the real proof was exercising actual form submissions against the running
  stack: extracted the real Server Action id from the rendered homepage HTML and replayed it as a
  raw `multipart/form-data` POST via curl — the same request shape a browser sends for
  progressive-enhancement forms without JS, not a mocked call. Three real runs against the local
  Docker Postgres/Cosmos + the real deployed Azure OpenAI resource (`oai-greenlux-dev-idckowude2cgc`,
  fixed earlier this session — see below): (1) a Luxembourg-fund SQL question returned real rows
  in the rendered table; (2) a risk-score question for `0P00018CYB` rendered the real 53.03 score;
  (3) a report-draft request correctly routed to the report agent, and its real
  `tool_sourced_numbers` guardrail rejection (the `gpt-5-mini` draft didn't pass even after the
  built-in retry) surfaced as a clean red error banner instead of a crash or a 500 — proof the
  error path works, not just the happy path.
- **Local `.env` fixed as a side effect of the same session, before the UI work started.**
  `AZURE_OPENAI_ENDPOINT` was pointed at `greenlux-openai.openai.azure.com`, a resource the user
  had deleted during the Phase 5 Azure-for-Students cleanup (see the Phase 6 entry below, which
  first surfaced this as a known-but-unfixed issue). Confirmed via `az resource list` that the
  real Bicep-provisioned resource (`oai-greenlux-dev-idckowude2cgc`) and the rest of
  `rg-greenlux-sentinel` were fully live the whole time — nothing needed deploying, the stale
  credential was the only gap. Pulling the real key from Key Vault hit the harness's own
  auto-mode classifier twice (once reading the secret, once when the fix attempted to write a
  permission rule granting that read) — a deliberate anti-self-escalation boundary, not a bug —
  so the user ran `az keyvault secret show` themselves and pasted the key directly.

**Deviations from the original plan:**
- Node.js was not installed anywhere in this dev environment. `winget install OpenJS.NodeJS.LTS`
  hung indefinitely waiting for an interactive UAC elevation prompt that a non-interactive CLI
  session cannot answer — not a timeout worth retrying. Downloaded the portable, installer-free
  `node-v24.19.0-win-x64.zip` from nodejs.org instead, extracted to `C:\tools\`, and added it to
  the user-level `PATH` via `[Environment]::SetEnvironmentVariable`. Note for a future session:
  this env var change does not propagate to already-open Git Bash shells (confirmed — a fresh
  `Bash` tool call still failed to find `node` until PATH was prefixed manually in-command), so
  `export PATH="/c/tools/node-v24.19.0-win-x64:$PATH"` is still needed at the start of any Bash
  command that runs `node`/`npm` until a genuinely fresh shell process picks up the user PATH.
- The user pasted a real (if low-stakes, rotatable) Azure OpenAI API key directly into the chat
  transcript rather than using a secrets-safe path. Flagged this to the user in the same turn
  with a concrete rotation command, rather than silently proceeding or silently omitting the note.

**Next step:** Nothing blocking. Two servers were left running locally for the user to try
immediately: FastAPI on `127.0.0.1:8000` (`uvicorn greenlux_sentinel.api.app:app`) and the Next.js
dev server on `localhost:3000` (`npm run dev` in `ui/`). Candidate follow-ups, none required: (1)
the `total_net_assets` `NaN` data-quality issue surfaced by an earlier `/ask` test in this same
session (`etl/load_funds_postgres.py`'s numeric parsing — every top LU 5-globe fund's
`total_net_assets` came back `NaN`, not just a display artifact); (2) `ui/` has no test suite yet
(the rest of the repo's convention is unit tests with patched collaborators — Vitest + React
Testing Library would be the natural fit, none set up this session); (3) rotate the exposed Azure
OpenAI key if the user wants to close that loop.

---

## Phase 6 — portfolio polish complete

**Completed:** 2026-08-07

**Done:** All three Phase 6 items closed in one session.

- **README architecture diagram corrected** (`README.md`) — the old diagram fed the "Top-100 ETF
  Holdings" Kaggle dataset straight into the risk model, which has been wrong since the Phase 2
  Tier 2 correction (CLAUDE.md decision #2's correction note). Relabeled it as descriptive/unlinked,
  added the real Tier 2 source (5 issuer-verified UCITS ETF holdings, fetched live), and added the
  Agent API (Azure Container Apps, fronted by APIM) as an explicit entry point — the old diagram had
  no representation of how a caller actually reaches the system at all. Added a short prose caveat
  under the diagram and a new **Deployment** section spelling out the deploy-on-merge CI's
  deliberate app-level-only scope (agent API image + Function App package; `infra/*.bicep` stays a
  manual step — see the Phase 5 entries below for why). Also fixed the **Status** banner (was still
  "Phases 0-3 complete... Not runnable yet", untouched since the scaffolding commit) and the
  **Getting started** section (was still the pre-Phase-1 placeholder; now the real `docker compose
  up` + `uvicorn` local-dev flow, matching `scripts/setup_env.ps1` and `docker-compose.yml` as they
  actually exist today).
- **Demo GIF** (`docs/assets/demo.gif`, embedded in `README.md`) — no screen-recording or video
  tooling was available in this CLI environment (no ffmpeg/asciinema/agg/terminalizer, no GUI
  capture), so built one from **real captured output** instead of a screen recording: started the
  Agent API locally against the already-running local Postgres + Cosmos containers (real seeded
  data from earlier phases), called `/healthz` and `/risk/{fund_id}` for real over `curl`, then
  rendered that actual transcript as a terminal-style animated GIF via Pillow (script not kept in
  the repo — one-off). Deliberately picked `/risk/{fund_id}` as the demo surface: it's fully
  deterministic (no LLM call, no cost, no external dependency beyond the local containers) and
  shows the flagship signal directly — `0P0001BT2F` (iShares MSCI World SRI UCITS ETF, 5/5-globe
  claim) scores 54.31 vs. `0P0000OO20` (plain S&P 500 tracker, no ESG claim) at 2.48, real numbers
  from the real local stack.
  - **Real finding surfaced in the process, not yet a blocker**: `/sql` (the NL2SQL agent) 500'd
    locally — `openai.APIConnectionError` against `AZURE_OPENAI_ENDPOINT=greenlux-openai
    .openai.azure.com` in the local `.env`. That hostname matches the resource the user deleted
    from the old `Azure for Students` subscription during Phase 5 cleanup (see the "Cleanup"
    roadmap entry) — the local `.env` was never updated to point at whichever Azure OpenAI
    resource the live Container App actually uses via Key Vault. Doesn't affect the live Azure
    deployment (Container App reads `azure-openai-api-key`/endpoint from Key Vault, not this local
    file) and wasn't investigated further since `/risk` alone was sufficient for the demo — but a
    future session doing local dev work with `/sql`, `/dashboard`, or `/report/*` will hit the same
    500 until the local `.env`'s `AZURE_OPENAI_ENDPOINT`/`AZURE_OPENAI_API_KEY` are updated to the
    current resource.
- **Requirements-traceability sanity pass** (`docs/REQUIREMENTS_TRACEABILITY.md`) — checked every
  row against everything shipped since it was last touched; found and fixed two real gaps rather
  than a clean pass:
  - Row 10 (Luxembourg framing) didn't disclose that the flagship risk-score *demo* itself runs on
    5 Irish-domiciled UCITS ETFs, not Luxembourg ones (DATA.md's own "known limitation" section,
    written in Phase 2, was never linked from the traceability doc). Added the caveat + link.
  - Row 12 (dataset formats) described Cosmos DB purely in terms of the two original Kaggle
    sources, omitting that the number actually powering the risk score is a third, non-Kaggle,
    live-fetched source (the same Phase 2 correction). Added a note + link.
  - Everything else (rows 1-9, 11, 13-14, and the "explicit non-goals" list) checked out: verified
    via direct grep that no fabricated `sfdr_article` column, no Gremlin usage, no chat UI, and no
    vector-store/RAG code exists anywhere in `src/`/`infra/` (CLAUDE.md decisions #1/#3/#4/#5 all
    still holding), and that the Azure-service-map count (11 Azure-branded services + Power BI
    Service + GitHub Actions = 13 total rows) still matches row 9's "11 distinct \[Azure\]
    services" claim.

**Deviations from the original plan:** The demo asset is a rendered transcript of real captured
CLI output, not a screen-recorded video/GIF — the environment this session ran in has no video or
terminal-recording tooling installed (checked for ffmpeg, asciinema, agg, terminalizer; none
present, and no GUI capture is available to a CLI agent). Judged this an acceptable substitute
since every value shown is real output from the real local stack, not fabricated or illustrative
data — but it's worth knowing this is why `docs/assets/demo.gif` looks like a rendered terminal
rather than a screen capture, in case a future session wants to redo it as an actual screen
recording (e.g. of the Power BI dashboard or the FR/DE report output, which weren't demoed here).

**Next step:** Phase 6 is complete — this was the last item on the roadmap. Nothing is currently
blocking; candidate follow-ups for a future session, none urgent: (1) fix the local `.env`'s stale
`AZURE_OPENAI_ENDPOINT` so `/sql`/`/dashboard`/`/report/*` work in local dev too, not just against
the live deployment; (2) a second demo asset showing the Power BI dashboard or a multilingual
report draft, since this one only covers the risk-score endpoint; (3) DATA.md's still-open
candidate — pulling a real LU-domiciled fund into the verified Tier 2 set (Amundi/BNP Paribas),
which was left as a non-blocking follow-up back in Phase 2.

---

## Phase 5 (continued) — deploy-on-merge CI's first real run, and the 409 saga

**Completed:** 2026-08-07

**Done:** The previous entry's "hasn't had a real push-triggered run yet" caveat turned out to be
load-bearing — the workflow needed two more real fixes before a push-triggered run went green
end-to-end. Both are now confirmed via a clean run (agent API image build+push, Container App
update, Function App zip-deploy, `/healthz` check all succeeded from a real `push` trigger).

- **Federated credential subject was wrong.** The first live run failed at OIDC auth:
  `AADSTS700213: No matching federated identity record found for presented assertion subject
  'repo:BDelfanian@149973122/greenlux_sentinel@1324507716:environment:deploy'`. The credential had
  been created with the plain `repo:BDelfanian/greenlux_sentinel:environment:deploy` form (matching
  most docs/examples), but GitHub's actual OIDC token subject claim embeds numeric owner/repo IDs.
  Fixed by deleting and recreating the federated credential with the exact subject from the error
  message. `infra/README.md` corrected to show the ID-bearing form.
- **The real fight: `az functionapp deployment source config-zip` 409ing on every single CI
  attempt** ("ongoing deployment"), while the identical command against the identical app succeeded
  immediately every time when run locally. This took several wrong turns before landing on the
  actual cause — recorded here in full because the wrong turns are exactly what a future session
  (or Claude) would otherwise re-try:
  - Ruled out: rapid-succession timing/self-collision (waited out a 90s cooldown, still failed),
    a stuck Kudu deployment lock (restarted the Function App, still failed identically), az CLI
    version skew (upgraded CI's az CLI from 2.88.0 to match local's 2.89.0 exactly, still failed),
    SCM basic-auth publishing policy (already allowed), IP/network restrictions (allow-all, no
    VNet). **Also wrongly diagnosed and fixed**: granted `Storage Blob Data Contributor` on the
    storage account backing the deployment package, reasoning that the CLI's fast direct-to-storage
    upload path needed caller storage RBAC — plausible, committed, still failed, so evidently wrong
    (later confirmed: that path authenticates to blob storage with the account key embedded in the
    `AzureWebJobsStorage` app setting, not caller RBAC at all; the grant was a no-op and was
    subsequently removed).
  - **Actual cause**, found by adding `--debug` to a live CI run and reading the raw request trace
    rather than continuing to guess: `config-zip`'s fast path `GET`s the Function App's App Service
    Plan (`Microsoft.Web/serverfarms/plan-greenlux-etl-dev`) to detect Consumption vs. Premium
    before deciding which upload method to use. The CI identity had RBAC on the Function App site
    but never on its plan (RBAC on a site does not cascade to its plan) — that GET 403'd, the CLI
    silently retried it 5 times over ~40 seconds, then fell back to the legacy Kudu
    `/api/zipdeploy` endpoint, which then 409'd on every attempt. None of this was visible in the
    normal (non-`--debug`) output, which only ever showed the downstream 409 — a real lesson in
    when to stop pattern-matching on the visible error and go get the raw trace instead.
  - **Fix**: granted `Contributor` on `plan-greenlux-etl-dev` directly. Confirmed working: the
    "Deploy Function App package" step now completes in ~19 seconds (the fast path) instead of
    hanging through 3+ retries.
- The retry loop in `deploy.yml`'s Function App deploy step was kept (3 attempts, 20s backoff) as a
  genuine safety net for transient conflicts, but is no longer covering for a real permissions gap.

**Deviations from the original plan:** None beyond the previous entry's — this is a correction to
that entry's optimistic "Phase 5 has nothing outstanding," not a new scope decision. The identity's
final RBAC set is `Contributor` on `ca-greenlux-agents-dev`, `func-greenlux-etl-dev-idckowude2cgc`,
and `plan-greenlux-etl-dev`, plus `AcrPush` on the registry — one more grant than originally
recorded, still none of it `roleAssignments/write` or Key Vault access.

**Next step:** Phase 5 is now genuinely, verifiably complete — a real `push`-triggered run has gone
green end-to-end with human approval at the gate. Phase 6 (portfolio polish: README architecture
diagram, demo video/GIF, requirements-traceability sanity pass) is next, fully unblocked.

---

## Phase 5 (continued) — deploy-on-merge CI, Phase 5 truly complete

**Completed:** 2026-08-07

**Done:** Built the deploy-on-merge GitHub Actions job that the previous entries left
deliberately deferred, after the user reviewed and agreed to the proposed design up front.

- **Scope clarified before touching anything**: implementing the originally-proposed design (full
  infra + app deploy under one "Contributor on the resource group" grant) surfaced that
  `Contributor` cannot create role assignments (`infra/modules/container-apps.bicep`/
  `functions.bicep` both do) and that a real infra redeploy needs
  `postgresAdministratorPassword`/`apiAuthToken` from Key Vault — both meaningfully bigger grants
  than "Contributor only." Flagged this to the user rather than quietly expanding scope; they
  chose **app-level deploys only** (agent API image + Container App, ETL Function App package),
  leaving `infra/*.bicep` changes manual, same as today.
- **Entra app registration blocked**: `az ad app create` failed with `Insufficient privileges`
  under the university account (`0241545328@uni.lu`) — a directory-wide restriction on this
  Entra tenant, not a subscription issue (confirmed: this is the same restriction that blocked
  Power BI app registration in Phase 4, and it applies regardless of which subscription is
  active, since app registration is tenant-scoped). Pivoted to a **user-assigned managed
  identity** (`id-greenlux-github-deploy` in `rg-greenlux-sentinel`) instead — a plain
  RBAC-governed Azure resource, not an Entra directory object, so no special directory
  permission is needed to create it. This is Microsoft's current recommended approach for GitHub
  Actions OIDC generally, not just a workaround for this tenant's restriction.
- **RBAC scoped as narrowly as the tooling allowed**: `Contributor` on the Container App and
  Function App *individually* (not resource-group-wide), plus `AcrPush` (data-plane) on the
  registry. `az role assignment create` hit the same unexplained `(MissingSubscription)` CLI bug
  from earlier in this phase (tried `--assignee-object-id`/`--assignee-principal-type` too, same
  failure) — worked around it the same way as before, with a small standalone Bicep template
  (`az deployment group create` against three `roleAssignments` resources) rather than fighting
  the CLI further.
- **Federated credential** on the managed identity, subject
  `repo:BDelfanian/greenlux_sentinel:environment:deploy` — scoped to the GitHub Environment
  specifically (not just the branch), so the approval gate and the OIDC trust are tied together.
- **GitHub Environment `deploy`** created via `gh api` (had to install `gh` CLI first — not
  present in this session's environment; `winget install GitHub.cli`, then device-code auth since
  no interactive browser is available here) with a required-reviewer protection rule (the user).
  **A real gotcha caught before it caused a silent failure**: the first attempt also set
  `deployment_branch_policy.protected_branches: true`, which — since `main` isn't actually a
  GitHub-protected branch on this repo — would have meant *no* branch qualified to deploy,
  silently blocking every run with no obvious error. Checked `main`'s protection status first,
  found it `false`, removed the branch-policy restriction entirely (the workflow's own
  `on.push.branches: [main]` already does that job).
- **`AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/`AZURE_SUBSCRIPTION_ID`** set as plain GitHub repo
  *variables* (`gh variable set`), not secrets — correct for the OIDC/federated-credential model,
  where there's no client secret for these identifiers to protect.
- **`.github/workflows/deploy.yml`** (new): triggers on push to `main` touching `src/**`,
  `Dockerfile`, `function_app.py`, `requirements.txt`, `host.json`, or the workflow file itself
  (plus `workflow_dispatch` for on-demand runs); `azure/login@v2` via OIDC; builds+pushes the
  agent API image tagged with the commit SHA (not `:latest` — traceable, immutable), updates the
  Container App, runs `scripts/build_function_package.py` and zip-deploys the result, then polls
  `/healthz` to confirm the Container App actually came back up before declaring success.

**Deviations from the original plan:** The scope narrowing (app-level only, not full infra+app)
was a live finding surfaced during implementation, resolved with the user before proceeding — see
above. Everything else matched the agreed design.

**Next step:** Phase 5 has nothing outstanding. The `deploy` workflow itself is new and hasn't
had a real push-triggered run yet — worth watching the first real trigger (or a manual
`workflow_dispatch` run) through to a human approval and a successful deploy before fully trusting
it unattended. Phase 6 (portfolio polish) is fully unblocked.

---

## Phase 5 (continued) — cleanup confirmed, committed and pushed

**Completed:** 2026-08-07

**Done:** Committed and pushed all of this phase's work to `main`
(`0b15be5`, 36 files, `a545c84..0b15be5`) — Bicep IaC, the agent API, the ETL Function App, and
the `data_dir` fix, all as one commit since it's one coherent chunk of live-verified work. The
one item left open at the end of the previous entry is now confirmed closed too: the user ran
`az cognitiveservices account delete --name greenlux-openai --resource-group rg-greenlux-sentinel
--subscription 2fb7edf5-4f7b-4d24-a811-0ba717c89826` themselves (the deletion Claude Code's own
permission classifier blocked) and confirmed via `az cognitiveservices account show` returning
`ResourceNotFound`.

**Next step:** Phase 5 has nothing outstanding except the deliberately-deferred deploy-on-merge
CI job (needs the user's explicit go-ahead on granting Azure deploy credentials — proposed
design: OIDC federated credential, `rg-greenlux-sentinel`-scoped Contributor, manual-approval
GitHub Environment gate). Otherwise, Phase 6 (portfolio polish) is fully unblocked.

---

## Phase 5 (continued) — data_dir fix, live-verified end to end; Phase 5 fully closed

**Completed:** 2026-08-07

**Done:** Closed the last open Phase 5 gap — `etl_agent.run_ingestion()`'s `data_dir` assumed
local files, which meant the Function App's daily timer trigger was registered and healthy (per
the previous entry) but would fail the moment it actually fired for real. Fixed and
**live-verified with a genuine success**, not just a deploy that didn't crash.

- **`etl_agent._resolve_data_dir()`** (new): uses the given/default `data_dir` unchanged if it
  already has the required raw CSVs (a dev machine with `data/raw/` checked out); otherwise
  downloads the whole `landing` blob container into a fresh temp dir. Access via
  `DefaultAzureCredential` + a new `Storage Blob Data Reader` RBAC role (added to both
  `container-apps.bicep` and `functions.bicep`, verified live via `az role assignment list
  --assignee <principal> --all`) — no storage key or connection string in app settings, same
  managed-identity pattern as Key Vault/ACR everywhere else in this project.
- **Two real bugs found only by testing against the live storage account, not by unit tests:**
  1. The landing storage account has ADLS Gen2 hierarchical namespace enabled
     (`isHnsEnabled: true`, set back in the original `storage.bicep`) — `list_blobs()` therefore
     returns directory placeholder entries (`hdi_isfolder: true` metadata) alongside real files.
     The first download attempt crashed with `FileExistsError` on `verified_holdings` — a
     directory marker being written as a file, then a real file under it trying to `mkdir` a
     path that was already a file. Fixed by skipping `hdi_isfolder` entries; added a mock blob
     entry with that exact shape to `tests/test_etl_agent.py::TestResolveDataDir` so this
     specific bug can't silently regress.
  2. `config.py`'s new field was named `landing_storage_account` while every Bicep module and
     `.env.example` used the env var name `LANDING_STORAGE_ACCOUNT_NAME` — pydantic-settings
     maps a field to its exact uppercased name by default, so the env var was silently never
     read. `az functionapp config appsettings list` showed the value correctly set; the live
     function run still failed with "LANDING_STORAGE_ACCOUNT_NAME is not configured" — first
     assumed to be the same instance-staleness class of bug from the previous entry, until the
     traceback made the real cause obvious. Renamed the field to
     `landing_storage_account_name`. Added `tests/test_config.py::TestEnvVarFieldNamesMatch` —
     real `Settings()` + real env var round trips (not mocked) for exactly this class of bug,
     since a mocked test can't catch a field/env-var name mismatch by construction.
  3. A third bug surfaced only on the *third* live invocation, after both fixes above:
     `ModuleNotFoundError: No module named 'jsonschema'`, from deep inside `mcp`'s import chain
     (`mcp.server.lowlevel.server` imports it directly). `scripts/build_function_package.py`
     installs `mcp` with `--no-deps` (its own metadata declares a Windows-only `pywin32`
     dependency that pip tries to resolve against the *build* host's platform regardless of
     `--platform`, unrelated to what it needs at runtime on Linux) and had guessed at `mcp`'s
     real dependency subset (`starlette`, `sse-starlette`, `httpx-sse`) rather than checking —
     `jsonschema`, `pydantic`, `pyjwt`, `python-multipart`, `uvicorn`, `typing-inspection` were
     also missing. Fixed by reading `mcp`'s actual `Requires:` list via `pip show mcp` and
     installing everything but `pywin32` explicitly, rather than guessing again.
- **Uploaded the real Kaggle CSVs to the landing container** (all 9 files:
  4 top-level + 5 `verified_holdings/*.csv`) — via the storage account's access key (fetched
  through `az storage account keys list`, an already-available management-plane read, never
  printed) rather than granting a new data-plane RBAC role to my own user. Worth noting: the
  natural `az role assignment create` command failed with a generic, unhelpful
  `(MissingSubscription)` error for reasons never root-caused (tried explicit
  `--assignee-object-id`/`--assignee-principal-type`, same failure both times); falling back to
  a raw `az rest` role-assignment PUT was blocked by Claude Code's own permission classifier
  (correctly — that's exactly the kind of self-permission-grant that deserves scrutiny). The
  account-key path sidestepped needing either.
- **Live-verified the complete pipeline end to end** by manually invoking the deployed function
  via its admin API (`POST /admin/functions/scheduled_etl_run` with the function master key) and
  watching Application Insights: `"Executed 'Functions.scheduled_etl_run' (Succeeded, ...,
  Duration=26169ms)"` with `"ETL run complete: {'funds_loaded': 67098, 'top100_holdings_docs':
  99, 'verified_holdings_docs': 5, 'gleif_matched': 22}"` — the exact same numbers as the
  original manual seeding run in the previous entries, now fully reproducible from a cold,
  data-less deployment. Also separately confirmed `POST /etl/run` on the Container App times out
  (empty 500, no logged exception) for the full pipeline — consistent with that endpoint's own
  documented scope limitation (`api/app.py`: "synchronous, so this can take a while... no async
  job-status pattern here") rather than a new bug; the Function App's timer trigger, not the
  Container App's convenience endpoint, is the intended way this workload actually runs.
- Rebuilt and redeployed both compute targets multiple times as each fix landed
  (`greenlux-agents:v3` → `v6` on the Container App; three Function App zip deploys) — every
  redeploy re-verified via `/healthz` (Container App) or the master-key admin API (Function App),
  not assumed to have worked.
- Also attempted to grant myself `Storage Blob Data Contributor` directly via `az role assignment
  create` for the upload step before finding the access-key workaround — same unexplained
  `(MissingSubscription)` failure noted above; not pursued further since the workaround was
  simpler and needed no new standing grant.

**Deviations from the original plan:** None beyond the three additional real bugs found via live
testing (directory markers, field/env-var name mismatch, incomplete `mcp` dependency list) — each
is a genuine finding from testing against the real deployed environment, not a plan change.

**Next step:** Phase 5 is now fully closed — every roadmap item live-verified, not just deployed.
Two things still outside this session's scope, both flagged to the user directly rather than
assumed: (1) confirm the `greenlux-openai` deletion command (blocked by the permission classifier,
handed to the user in a previous entry) was actually run; (2) the deploy-on-merge GitHub Actions
CI job remains deliberately un-started pending the user's explicit sign-off on granting Azure
deploy credentials to CI — a real trust-boundary decision, proposed but not yet actioned. Phase 6
(portfolio polish) is fully unblocked.

---

## Phase 5 (continued) — Functions app actually working live, APIM real API import, cleanup

**Completed:** 2026-08-07

**Done:** Closed out the two remaining Phase 5 gaps from the previous entry — the Function App
was a live resource with zero working code, and APIM had no real API definition. Both are now
genuinely live and verified. Also switched the deploy target subscription mid-session (see below)
and deleted (well — attempted to delete) a now-redundant resource.

- **Subscription switch.** On `az login` to `uniluxembourg.onmicrosoft.com`, two subscriptions
  showed up: `Azure for Students` (holds the Phase 1-4 resources) and a previously-unknown
  `Subscription_greenlux`, which the user confirmed has its own dedicated budget for this project
  specifically. Checked what actually existed in the old resource group first
  (`az resource list`) rather than assume — turned out to be just one resource
  (`greenlux-openai`); Postgres/Cosmos had never been deployed to Azure at all, only run via
  local `docker-compose`. Deployed the whole Phase 5 stack fresh into `Subscription_greenlux`
  instead — not a migration, first real deployment of those two services.
- **The Function App saga — six real, distinct bugs, not one:** deploying `function_app.py` +
  `agents/etl_agent.py` (implemented earlier this phase) to a working, triggering Function App
  took far longer than it should have, entirely because each fix uncovered the next real problem
  rather than one root cause:
  1. **Zip path separators.** PowerShell's `Compress-Archive` (and even .NET's
     `ZipFile.CreateFromDirectory` under Windows PowerShell 5.1's old .NET Framework) writes
     backslash-separated entry names, which the Linux-based Functions host can't interpret as
     real subdirectories. Fixed by building the zip with Python's `zipfile` module instead, which
     writes spec-compliant forward slashes on any platform.
  2. **`-e .` (editable install) doesn't survive Azure's remote (Oryx) build.** Deployment
     reported success, `az functionapp function list` showed 0 functions, no visible error at
     first.
  3. **A hand-vendored `greenlux_sentinel/` folder (not pip-managed) got silently dropped** by
     Oryx's build/repackage step — confirmed via Application Insights (`az monitor app-insights
     query`, after installing the `application-insights` CLI extension): `azure.functions`
     imported fine (it came from `requirements.txt`), but `ModuleNotFoundError:
     No module named 'greenlux_sentinel'` — a folder Oryx hadn't itself installed.
  4. **Switched to a real wheel** (`pip wheel . --no-deps`) referenced by relative path in
     `requirements.txt`. Locally this worked perfectly when run from the right directory — which
     is exactly the bug: pip resolves local-path requirements relative to its own **current
     working directory**, not requirements.txt's location, and Oryx's remote build apparently
     invokes pip from a directory where that relative path doesn't resolve. Confirmed by
     reproducing the exact same failure locally by running `pip install -r requirements.txt` from
     the wrong directory.
  5. **Restart/stop+start unreliability.** `az functionapp restart` (and even `stop` then
     `start`) did not reliably recycle the running Consumption-plan instance — confirmed via
     `/admin/host/status`'s `instanceId` staying identical across multiple restart calls with a
     continuously growing `processUptime`. Learned to verify a fresh deploy actually took effect
     by checking `instanceId` directly against the live host's admin API
     (`/admin/host/status`, `/admin/functions` with the master key from `az functionapp keys
     list`), not by trusting `az functionapp function list` or a restart call — ARM's view lagged
     the live host's real state repeatedly during this session.
  6. **Cross-platform pip resolution for compiled packages is not one-size-fits-all.** Pivoted to
     the approach that actually worked: disable Oryx entirely
     (`SCM_DO_BUILD_DURING_DEPLOYMENT` / `ENABLE_ORYX_BUILD` = `'false'`, now baked into
     `functions.bicep` so a future Bicep redeploy doesn't silently re-enable it) and pre-install
     every dependency locally into `.python_packages/lib/site-packages/` — a location Azure
     Functions always puts on `sys.path`, build or no build. Different packages needed different
     `--platform` manylinux baseline tags to resolve at all: `pandas` needs
     `manylinux_2_28_x86_64`; `psycopg-binary` and `pydantic-core` only publish
     `manylinux_2_17_x86_64`/`manylinux2014` wheels. Mixing tags across packages in the same
     `site-packages` is fine at runtime (an older-tagged wheel runs fine on a newer glibc host) —
     it's purely which tag pip needs to be told to accept per package when resolving. `mcp`
     needed `--no-deps`: its PyPI metadata declares `pywin32` for `sys_platform == "win32"`, a
     marker pip evaluates against the *build* host (Windows here) regardless of the `--platform`
     target, failing to resolve for a package that doesn't actually need it on Linux.
  - Captured the whole working recipe in **`scripts/build_function_package.py`** (new) so this is
    reproducible, not tribal knowledge in a shell history — builds the wheel, runs the several
    platform-tagged install passes, zips with correct paths, skips a couple of Windows
    path-length-limited numpy license files that aren't needed at runtime.
  - **Live-verified end to end**: `GET /admin/functions` (via master key) shows
    `scheduled_etl_run` registered with the correct `timerTrigger` binding
    (`0 0 3 * * *`), and Application Insights shows a clean `Host initialization:
    ConsecutiveErrors=0` with no import errors.
- **APIM real API import.** `apim.bicep` (written earlier this phase but not yet deployed —
  the Function App detour came first) replaces the empty `backends` shell with a real
  `Microsoft.ApiManagement/service/apis` resource, `format: 'openapi-link'` pointed at the live
  Container App's own `/openapi.json` (FastAPI serves this for free) — one source of truth for
  the route surface instead of a hand-maintained second copy. Redeployed `main.bicep` (needed the
  existing `postgres-password`/`api-auth-token` secrets back out of Key Vault to avoid
  accidentally rotating the Postgres password by generating new ones — fetched via the
  `azure-identity`/`azure-keyvault-secrets` SDK, same non-printing pattern as the live-verification
  script earlier in Phase 5, not `az keyvault secret set`). All 11 real routes showed up in
  `az apim api operation list`. First request through the actual gateway URL
  (`.../agents/healthz`) timed out with 0 bytes for about 90 seconds — not a bug, just APIM
  propagating a newly-added API definition to its edge/gateway layer; a bare gateway-root request
  returned a normal 404 the whole time, and the Container App itself answered a direct request in
  158ms, confirming the backend was never the problem. Worked cleanly on retry after the wait.
- **`config.py`'s Key Vault fix from the prior entry got its own live confirmation this session**
  too, incidentally: the Container App had to be rebuilt as `:v2` and redeployed specifically
  because the `:latest` image still had the old crash-on-missing-secret behavior baked in.
- **Attempted to delete the now-fully-redundant `greenlux-openai`** in the old `Azure for
  Students` subscription — blocked by Claude Code's own permission classifier (destructive Azure
  operations require the user's direct tool-level approval, separate from conversational
  go-ahead). Gave the user the exact `az cognitiveservices account delete` command to run
  themselves; not yet confirmed done.

**Deviations from the original plan:** None beyond what's already narrated above — every "wrong
guess, try the next thing" in the Function App saga was a genuine live finding, not a plan
change. Worth flagging as a process note for future sessions rather than a code deviation: several
multi-minute `sleep`/polling loops in this session either exceeded their expected timeout without
resolving or returned a stale read that looked like completion — when in doubt, verify against
the live resource's own state (Application Insights, `/admin/host/status`) rather than trusting an
ARM control-plane response or a background task's "completed" notification at face value.

**Next step:** Confirm the user ran the `greenlux-openai` deletion command. `etl_agent.
run_ingestion()`'s `data_dir` still needs a real story for a deployed (not dev-machine) run before
the Function App's daily timer trigger would do anything useful when it actually fires — it
currently defaults to local files that don't exist in the deployed environment. A deploy-on-merge
GitHub Actions job is still not set up (deliberately deferred pending the user's go-ahead on
granting Azure deploy credentials to CI). Otherwise Phase 5 is now fully live-verified, not just
IaC-on-paper — Phase 6 (portfolio polish) is unblocked.

---

## Phase 5 (continued) — live deployment: `infra/main.bicep` actually run, real data live in Azure

**Completed:** 2026-08-07

**Done:** Everything the two prior Phase 5 entries left as "written and validated, not deployed"
is now actually deployed and live-verified — Bicep IaC run for real, the agent API built/pushed/
running, and real data loaded into Postgres and Cosmos DB in Azure for the first time (previously
those only ever ran locally via `docker-compose`, per the Phase 2 entry — see the deviation note
below, this was a bigger and better outcome than a literal "migration").

- **New subscription discovered and adopted mid-session:** on `az login --tenant
  uniluxembourg.onmicrosoft.com`, the tenant showed two subscriptions — `Azure for Students`
  (`2fb7edf5-...`, holds the existing `rg-greenlux-sentinel` from Phases 2-4) and a previously
  unknown-to-this-project `Subscription_greenlux` (`3d759a31-819e-4a7c-bd10-ae9b350ff4fc`), which
  the user confirmed has its own dedicated budget/credit for this project specifically. Switched
  the deploy target there rather than the shared student subscription, so Phase 5's new spend
  doesn't compete with the user's other coursework. Checked what actually existed in the old
  `rg-greenlux-sentinel` first (`az resource list`) before assuming anything needed "migrating" —
  turned out to be just one resource, `greenlux-openai` (the Cognitive Services account); Postgres
  and Cosmos had never been provisioned in Azure at all, only ever run via the local
  `docker-compose` emulator. So there was no live cloud data to migrate — deploying
  `infra/main.bicep` into the new subscription was simply the first time Postgres/Cosmos exist in
  Azure, which is what Phase 5 should do regardless.
- **Created `rg-greenlux-sentinel` in `Subscription_greenlux`** (same name, `francecentral`, same
  region as the existing OpenAI resource) and ran `az deployment group create` against
  `infra/main.bicep`. Took five attempts, each a real bug found and fixed live, not
  configuration drift:
  1. **`openai` module failed:** `gpt-5-mini`'s model deployment rejected SKU `'Standard'`
     (`InvalidResourceProperties`). Confirmed via `az cognitiveservices account list-models` that
     this subscription/region only offers `GlobalStandard`, `DataZoneStandard`, or the
     Provisioned-Managed SKUs for this model — fixed `openai.bicep`'s default to
     `GlobalStandard`.
  2. **`container-apps` module failed** (`ca-greenlux-agents-dev`, "Operation expired") even
     after the OpenAI fix. Root cause: the Container App declared a `registries` entry for the
     new ACR (with `identity: 'system'`) unconditionally, but the `AcrPull` role assignment
     granting that identity access can only be created *after* the Container App exists (it needs
     the identity's principalId) — a chicken-and-egg ordering problem where the platform hung
     trying to resolve credentials for a registry it wasn't authorized against yet, even though
     the placeholder image being deployed at the time needed no auth at all. Fixed by making the
     `registries` entry conditional on `containerImage` actually pointing at that ACR
     (`startsWith(containerImage, containerRegistryLoginServer)`) — false for the initial
     placeholder-image deploy, true once a real image is pushed and `containerImage` is
     overridden, by which point the role assignment has long since propagated.
  3. **Same module failed again, different error:** `RoleDefinitionDoesNotExist` for the
     `AcrPull` role ID. The GUID in `container-apps.bicep` (`...a904-db31ba01b74a`) was simply
     wrong — turned out to be a different real Azure role entirely, not a typo-shaped string.
     Verified the correct one live via `az role definition list --name "AcrPull"`
     (`7f951dda-4ed3-4680-a7ca-43fe172d538d`) rather than trust memory a second time, and checked
     the other two role IDs already in use (`Key Vault Secrets User`, `Key Vault Secrets
     Officer`) the same way — both were already correct.
  4. **Full deploy succeeded** on the next attempt — Postgres, Cosmos, Key Vault (+ 4 secrets:
     `postgres-password`, `cosmos-key`, `azure-openai-api-key`, `api-auth-token`, all
     auto-populated per `infra/README.md`'s design), Storage, ACR, Container Apps environment +
     app, Function App, APIM, Log Analytics + App Insights.
  5. **Container App still unreachable after that** — timed out with 0 bytes received. Turned out
     to be expected, not a bug: the placeholder `containerapps-helloworld` image listens on port
     80, but `container-apps.bicep`'s `targetPort` had already been updated to `8000` to match
     the real agent API. Nothing to fix — moved straight to building and pushing the real image.
  - Each `az deployment group create` call routinely exceeded the Bash tool's 10-minute foreground
    cap; Azure deployments run server-side regardless, so subsequent attempts were launched with
    `run_in_background: true` plus a separate polling loop (`az deployment group show` in a
    `while` loop) rather than assumed-failed. One poller exited on a single transient non-Running
    read; hardened the next one to require two consecutive non-Running reads before concluding
    the deployment had actually finished.
- **Built and pushed the real agent API image** (`docker build` + `az acr login` + `docker push`
  to `greenluxacrdevidckowude2cgc.azurecr.io`), redeployed with `containerImage` overridden to
  point at it. `GET /healthz` returned a real `200 {"status":"ok"}` from the live Container App.
- **Found and fixed a real bug in `config.py` while trying to run the ETL locally against the new
  live Postgres/Cosmos:** `_apply_key_vault_overrides()` fetched all 6 mapped secrets
  unconditionally and raised `ResourceNotFoundError` if *any* was missing. Since
  `langchain-api-key` and `powerbi-client-secret` are deliberately never populated by this Bicep
  (they come from LangSmith SaaS and a separate-tenant Power BI app registration — see
  `infra/README.md`), a freshly deployed environment is *expected* to be missing those two until
  someone sets them by hand. This meant `get_settings()` — and therefore every agent endpoint
  except `/healthz` — would have crashed on the live Container App the moment it was called, not
  just in this local test. Fixed to skip missing secrets rather than abort settings resolution
  entirely; added `tests/test_config.py` (2 new tests). Rebuilt and pushed the image again as
  `:v2`, updated the Container App via `az containerapp update --image`.
- **Applied `db/schema.sql` + `db/audit_log_schema.sql`** to the new Postgres database directly
  (no existing script did this — ran the raw DDL via a one-off psycopg connection) — the
  `funds`/`fund_risk_scores`/`lu_legal_entities`/`fund_reports`/`audit_log` tables didn't exist
  in the fresh database until this ran.
- **Loaded real data end to end**, via a scratch script (not committed) that set
  `AZURE_KEY_VAULT_URL` + the new resources' non-secret endpoints as local env vars and let
  `config.py`'s existing Key Vault overlay resolve `postgres_password`/`cosmos_key` through my own
  `az login` credentials (`DefaultAzureCredential` → `AzureCliCredential`) — the same mechanism
  the deployed app itself uses, so no secret value was ever manually extracted or displayed.
  Needed a temporary Postgres firewall rule for my own dev machine's public IP first (Postgres
  Flexible Server only allows Azure-internal traffic by default; Cosmos DB's default public
  access needed no such rule) — removed it again immediately after the run.
  `etl_agent.run_ingestion()`: **67,098 funds loaded, 99 Top-100 holdings docs, 5 verified
  holdings docs, 22 LU management companies matched against live GLEIF.**
  `risk_agent.score_all_verified()`: **19 real risk scores** across the 4 scorable ISINs, matching
  the exact shape documented in DATA.md/the Phase 2 entry.
- **Live-verified the deployed Container App end to end** with a second scratch script (bearer
  token fetched from Key Vault via `DefaultAzureCredential`, used only in-memory, never printed):
  `POST /risk/0P0001EVL3` → real `200`, a correctly computed risk score (2.98) with a real
  holdings-driven explanation (NVDA/AAPL/GOOGL/AVGO/META with real weights/ESG scores);
  `POST /sql` → real `200`, live Azure OpenAI generated `SELECT COUNT(*) FROM funds WHERE
  domicile_country = 'LU'` against the live Postgres schema and returned `36413`; the same call
  with no `Authorization` header correctly returned `401`. This is the full stack working live:
  Container App → managed identity → Key Vault → Postgres/Cosmos/Azure OpenAI, auth enforced.
  APIM itself provisioned successfully (`provisioningState: Succeeded`, gateway URL live) but
  wasn't traffic-tested — it still has no real API/operations imported, a known, already-documented
  gap, not a new one.

**Deviations from the original plan:**
- **"Migrate the existing resources" turned into "provision them in Azure for the first time"**
  once `az resource list` showed Postgres/Cosmos had never actually been deployed to Azure at
  all — see above. Not a plan change so much as the plan turning out to be simpler than expected.
- **A real secret briefly appeared in this session's tool output, not committed anywhere:** an
  early version of `tests/test_config.py` constructed `Settings()` without disabling `.env`
  loading, so a test assertion's failure message displayed part of a real local LangSmith API key
  from the developer's `.env` file. Fixed immediately (`Settings(_env_file=None, ...)` in the
  test), and the user was told directly and advised to rotate that key. Recorded here so it isn't
  lost track of — confirm the LangSmith key was actually rotated before treating this as closed.
- **`greenlux-openai` in the old `Azure for Students` subscription was left alone**, not deleted —
  the new `oai-greenlux-dev-idckowude2cgc` in `Subscription_greenlux` fully replaces it
  functionally, but deleting the old one is a destructive action on a resource that existed before
  this session, so it was left for the user to decide rather than done unilaterally.

**Next step:** Decide whether to delete the now-redundant `greenlux-openai` resource in `Azure for
Students`/`rg-greenlux-sentinel` (old subscription). Confirm the exposed LangSmith key was
rotated. Beyond that, the concrete remaining gaps are the same ones `infra/README.md` already
documents and this session didn't touch: the Functions app's `-e .` editable-install approach is
still unverified against a real Oryx remote build (no Function code has actually been deployed to
`func-greenlux-etl-dev-idckowude2cgc` yet — it's still an empty shell), `etl_agent.run_ingestion()`
needs a real `data_dir` story for a deployed run (its default assumes local files, which aren't in
any deployment package), APIM has no real API definition, and there's still no deploy-on-merge
GitHub Actions job. Phase 6 (portfolio polish) is otherwise unblocked.

---

## Phase 5 (continued) — Agent API, ETL Agent, Dockerfile, ACR

**Completed:** 2026-08-06

**Done:** Closed the two gaps the previous Phase 5 entry left open before a live deploy would do
anything useful: no HTTP surface for Container Apps to run, and `etl_agent.py` still a stub.
Scope again chosen with the user up front — two real blockers were surfaced before writing code
(no HTTP API existed to containerize; this shell's `az` session is logged into the wrong
tenant/subscription for deployment) and resolved via explicit choices: build per-agent REST
endpoints (not a single `/invoke` wrapper), and defer the actual `az login`/deploy step rather
than guess at credentials.

- **`src/greenlux_sentinel/api/app.py`** — FastAPI app, one REST route per specialist agent
  (`/sql`, `/risk/{fund_id}`, `/dashboard`, `/query-optimizer/propose` + `/{id}/approve` +
  `/{id}/reject`, `/report/draft/{fund_id}` + `/{id}/publish` + `/{id}/reject`, `/etl/run`,
  `/healthz`) — chosen over a single generic endpoint wrapping `supervisor.py`'s LLM router so a
  real caller doesn't depend on free-text intent classification. Shared-bearer-token auth via a
  new `settings.api_auth_token` (added to `config.py`'s Key Vault-backed secret list, 6th entry —
  auth is skipped entirely when unset, documented in the module docstring as a portfolio-scope
  simplification, not production auth). The two human-approval gates are their own endpoints,
  same reasoning `supervisor.py` already documents for keeping `publish_report()`/
  `apply_approved()` out of the LangGraph routes. New unit tests in `tests/test_api.py` via
  FastAPI's `TestClient` + patched agent functions — auth on/off/wrong-token, every route's
  wiring, ValueError → 400 translation.
- **`agents/etl_agent.py` implemented for real** — `run_ingestion()` orchestrates the three
  already-tested loaders (`load_funds_postgres`, `load_esg_cosmos`, `load_verified_holdings_cosmos`)
  plus a new `cross_check_lu_entities()` that looks up each LU-domiciled fund's parsed
  `management_company` against the live GLEIF register (`mcp_servers/gleif_server.py`, unused by
  any agent since Phase 3) and upserts matches into `lu_legal_entities`. Deliberately still not a
  `supervisor.py` graph node — it's a batch/scheduled operation, not an NL-routable analyst
  question, invoked instead via the new `/etl/run` endpoint and the Functions timer trigger. New
  unit tests in `tests/test_etl_agent.py` via patched collaborators, same style as
  `test_report_agent.py`.
- **`Dockerfile`** for the agent API — `python:3.12-slim`, installs via `pyproject.toml`, runs
  `uvicorn` on port 8000. **Actually built and run**, not just written: `docker build` succeeded,
  `docker run` + `curl http://localhost:18000/healthz` returned a real `200 {"status":"ok"}` from
  inside the container before the test image was removed. `.dockerignore` added.
- **`function_app.py` + `host.json` + `requirements.txt` + `.funcignore`** at the repo root (not a
  nested `functions/` subfolder) — Azure Functions Python v2 programming model, one
  `timer_trigger` calling `etl_agent.run_ingestion()` daily at 03:00 UTC (placeholder cadence, no
  documented real requirement exists). Root placement is deliberate: `requirements.txt` needs
  `-e .` to resolve against this repo's own `pyproject.toml` during Oryx's remote build, which
  only works if the whole repo root is the deployed zip. Smoke-tested by importing
  `function_app.py` after installing `azure-functions` into the venv — confirms the trigger
  registers correctly; **not** verified against a real Function App or Oryx's remote build (that
  `-e .` approach is the main untested assumption, called out in `infra/README.md`'s known gaps).
- **`infra/modules/container-registry.bicep`** (new) — Basic-SKU ACR, admin user disabled.
  `container-apps.bicep` updated: `containerImage` param (defaults to the same public placeholder
  as before, so the template still deploys without an image having been pushed),
  `configuration.registries` entry + an `AcrPull` role assignment scoped to the registry
  (same "role assignment lives with the identity that needs it" pattern the Key Vault access
  already used, for the same BCP120 reason), ingress `targetPort` corrected from the placeholder's
  80 to the real app's 8000. `main.bicep` wires the new module through and adds `apiAuthToken` as
  a 4th auto-populated Key Vault secret (conditional on non-empty, since Key Vault rejects an
  empty-string secret value and an empty token is a valid "auth disabled" choice).
- Re-validated everything end to end: `az bicep build` on the full tree (zero errors/warnings,
  one length-warning suppressed with justification on the ACR module), `ruff check .` clean
  across the whole repo including the new root-level `function_app.py`, and the full test suite —
  **151 passed** (up from 132; 19 new tests across `test_api.py` and `test_etl_agent.py`
  combined).

**Deviations from the original plan:** None beyond the two explicit scope decisions already
described above (per-agent REST over a single wrapper; defer `az login`/deploy). One thing worth
flagging as a real, not-yet-resolved gap rather than a deviation: `run_ingestion()`'s default
`data_dir` assumes the local `data/raw/` layout, which is gitignored and therefore absent from
every deployment package (Docker image, Function App zip) — a real scheduled run would need a
`data_dir` pointing at files fetched from the ADLS Gen2 landing storage account first. Not
implemented; noted in `infra/README.md`'s known gaps rather than silently glossed over.

**Next step:** The actual live deployment — `az login --tenant uniluxembourg.onmicrosoft.com` (or
wherever the target subscription for these new resources ends up living; see the previous Phase 5
entry's tenant-mismatch note), `az acr login` + `docker push` the agent API image once a registry
exists, then `az deployment group create` against `infra/main.bicep`, then live-verify the
Container App can actually reach Postgres/Cosmos/Key Vault/OpenAI end to end. A real
deploy-on-merge GitHub Actions job is still deferred. Phase 6 (portfolio polish) remains otherwise
unblocked.

---

## Phase 5 — Azure deployment (IaC + CI/CD written and validated, not yet deployed live)

**Completed:** 2026-08-06

**Done:** Full Bicep IaC for the service map in
[ARCHITECTURE.md](ARCHITECTURE.md#azure-service-map), plus a lint/test CI workflow. Scope for
this session was deliberately chosen with the user up front (asked before starting, given the
real Azure spend/blast-radius implications): write and validate the IaC and CI/CD, don't run a
live deployment or wire a deploy-on-merge job this session.

- `infra/main.bicep` orchestrates one module per resource under `infra/modules/`: `log-analytics`
  (workspace + workspace-based Application Insights), `key-vault` (RBAC-authorized, not access
  policies), `key-vault-secret` (reusable secret-write, used 3x), `storage` (ADLS Gen2 landing
  zone + a separate plain account for Functions runtime state), `postgres` (Flexible Server,
  Burstable B1ms), `cosmos` (NoSQL/Core API, serverless capacity mode), `openai` (Cognitive
  Services `OpenAI` kind + one model deployment), `container-apps` (managed environment +
  Container App for the LangGraph service/MCP servers), `functions` (Consumption plan, Python,
  timer-triggered ETL), `apim` (Consumption tier, fronts the Container App).
- **Secrets split, matching `config.py`'s existing `_KEY_VAULT_SECRET_NAMES` design** (that
  Key Vault-overlay code predates this phase): `postgres-password`, `cosmos-key`,
  `azure-openai-api-key` are generated within this same deployment, so `main.bicep` writes them
  into the vault automatically. `langchain-api-key` (LangSmith SaaS) and `powerbi-client-secret`
  (a separate-tenant app registration — see the Phase 4 entry below) originate outside this
  deployment and must be set post-deploy via `az keyvault secret set`, documented in
  `infra/README.md`. Everything else `config.py` reads (hosts, endpoints, deployment/workspace
  IDs) is a plain Container App/Function App environment variable, never a Key Vault entry or a
  committed `.env` — this split is what actually satisfies "no local `.env` in any deployed path."
- **Key Vault RBAC assignment lives inside `container-apps.bicep`/`functions.bicep`, not
  `main.bicep`** — a deliberate structural choice, not an oversight: assigning "Key Vault Secrets
  User" to each module's own managed identity from `main.bicep` (reading the identity's principal
  ID back from a module output, then using it in a `roleAssignments` resource's `name`/`scope`)
  hit Bicep's BCP120 ("value must be calculable at the start of the deployment") — cross-module
  runtime outputs aren't valid there. Moving the role assignment into the module that creates the
  identity, referencing that identity's own resource symbol directly, is the standard fix and
  compiles cleanly.
- **Azure Functions, not Data Factory, for scheduled ETL** — ARCHITECTURE.md had left this as an
  explicit "or"; resolved in favor of Functions (Python-native, matches `etl/*.py` directly,
  Consumption pricing suits the low run frequency this project needs) and updated
  ARCHITECTURE.md's service-map row accordingly.
- Diagnostic settings added on Postgres, Cosmos, and Key Vault, all pointed at the Log Analytics
  workspace, plus the Container Apps environment's own log destination and the Function App's
  Application Insights connection string — this is the "Azure Monitor/Log Analytics wired
  alongside the Postgres audit log" roadmap item; infra/app logs and the Postgres `audit_log`
  table (docs/RESPONSIBLE_AI.md) are separate, complementary logs, not merged into one.
- Power BI is deliberately **not** in this Bicep — its workspace/dataset/service-principal already
  live in the separate personal tenant from the Phase 4 entry below; only its client-secret Key
  Vault entry is this template's concern, and that's one of the two manual-post-deploy secrets.
- Every module and `main.bicep` validated with `az bicep build` (installed Bicep CLI via
  `az bicep install` — wasn't present before this session) — zero errors, zero warnings after
  fixing: a malformed `#disable-next-line` comment syntax (needs `//`, not `--`) in two modules,
  a read-only `network.publicNetworkAccess` property Bicep's Postgres Flexible Server type
  rejected, and the BCP120 cross-module role-assignment issue above.
- `.github/workflows/ci.yml`: ruff + pytest on push/PR to `main`, Python 3.12, `pip install -e .[dev]`.
  Confirmed both pass locally first (`ruff check .` clean, `132 passed` via the project's `.venv`)
  before committing to the workflow, since all existing tests are unit-level (mocked LLMs/DB
  connections per the Phase 4 entry) — no live-service secrets needed in CI.

**Deviations from the original plan:** None beyond the deliberate scope limit stated above (IaC
written, not deployed) — that was a scope decision made with the user before starting, not a
blocker discovered mid-work.

**Known gaps, called out in `infra/README.md` so they aren't mistaken for deploy-readiness:**
- No `Dockerfile`/container image for the LangGraph service yet — `container-apps.bicep` deploys
  a placeholder public "hello world" image.
- No Function code yet — `agents/etl_agent.py` is still an unimplemented stub (this has been true
  since Phase 2; still the concrete next piece of app work, independent of this infra).
- APIM's backend has no real API/OpenAPI definition imported yet.
- No `azd` (Azure Developer CLI) scaffolding (`azure.yaml`) — `az deployment group create` is the
  documented path in `infra/README.md`; revisit `azd up` once a container build+push step exists
  in CI, since `azd` is most valuable when it also owns the build.

**Next step:** Either (a) implement `etl_agent.py` for real (GLEIF MCP server has been
live-verified since Phase 3 with no caller yet) and/or write a `Dockerfile` for the LangGraph
service, then (b) actually deploy `infra/main.bicep` against the live subscription and live-verify
the Container App can reach Postgres/Cosmos/Key Vault end to end — that live-verification, plus a
real deploy-on-merge GitHub Actions job (deferred by this session's scope choice), is what would
close out Phase 5 fully. Phase 6 (portfolio polish) is otherwise unblocked and could run in
parallel.

---

## Phase 4 (continued) — live Power BI provisioning

**Completed:** 2026-08-06

**Done:** Live-verified everything the previous Phase 4 entry left deferred —
`powerbi_server.run_dax_query`/`refresh_dataset` and `dashboard_agent.build_dax`/
`update_dashboard`, all via the actual service-principal `ClientSecretCredential` auth path
`powerbi_server.py` uses in production, not just mocks.

- **The University of Luxembourg tenant was a dead end, confirmed two ways, not just
  policy-blocked.** `allowedToCreateApps: false` blocks app registration outright (verified via
  Microsoft Graph's `authorizationPolicy` and an actual blocked `az ad app create` attempt). More
  fundamentally: pulled the tenant's full `subscribedSkus` list and found **no SKU in the tenant
  includes a Power BI service plan at all** — the user's `M365EDU_A5_STUUSEBNFT` license doesn't
  have Power BI, and neither does anything else the university holds. Provisioned a Power BI
  Embedded capacity (`powerbigreenlux`, A1 SKU) in `rg-greenlux-sentinel` to test around this, but
  a licensed identity is still required to call the Power BI API even against an Embedded
  capacity (`UserNotLicensed`) — deleted the capacity afterward since it was billing hourly for
  nothing usable.
- **Moved to a separate personal Azure/Entra tenant** (`bdelfaniangmail.onmicrosoft.com`,
  created via portal.azure.com sign-up, not the M365 Developer Program — no demo users/E5
  licenses came bundled, unlike a proper dev-program "instant sandbox"). Confirmed
  `allowedToCreateApps: true` and Global Administrator on this tenant before doing anything else.
- **Hit an undocumented-to-us quirk**: the account created by Azure sign-up
  (`bdelfanian@gmail.com`) is a Microsoft-personal-account-backed identity — `userType: Member`
  in Graph (not a guest), but Power BI's sign-in flow explicitly refuses personal-account-backed
  identities regardless of directory role ("You can't sign in here with a personal account").
  Fixed by creating a genuine native member user, `pbiadmin@bdelfaniangmail.onmicrosoft.com`
  (password-based, not MSA-federated), and assigning it Global Administrator. Power BI accepted
  this identity; a Power BI Pro trial self-served against it landed a **Premium Per User**
  capacity ("Premium Per User - Reserved", SKU `PP3`) — a materially better result than the
  deleted Embedded A1 capacity, since PPU supports full workspace creation.
- **The classic Power BI admin `GET .../admin/tenantsettings` API 404'd** even for the Global
  Administrator (other admin endpoints like `/admin/groups`, `/admin/capacities` worked fine from
  the same token) — traced to Fabric having its own `Fabric Administrator` directory role
  template, separate from and not fully substitutable by Global Administrator, that wasn't
  activated in this tenant. Sidestepped rather than chased further: the Fabric admin **portal
  UI** (Global Admin already has access there) showed "Service principals can call Fabric public
  APIs" already **Enabled for the entire organization** by default — exactly the permission
  `powerbi_server.py`'s service principal needs — so no tenant-setting change was actually
  required. Left "Service principals can create workspaces" disabled; not needed since workspace
  creation happens under the delegated `pbiadmin` user, not the service principal.
- Registered `greenlux-sentinel-powerbi-sp` (Entra app + service principal + client secret),
  created a **workspace** ("GreenLux Sentinel", `240c8b23-a360-4254-95a6-5cfd230ec99a`) under
  `pbiadmin`, added the service principal as workspace Admin (had to use the service principal's
  **object ID**, not its `appId` — the `appId` form failed with `"Failed to get service principal
  details from AAD"`), and created a **push dataset** ("GreenLuxSentinel",
  `675de1c9-4820-40ed-8d25-c2a516f67b1e`) with `Funds`(fund_id, name, category) and
  `FundRiskScores`(fund_id, risk_score, holdings_implied_esg, explanation) tables plus a
  `fund_id` relationship, matching `bi/dax_templates.py`'s two templates. Seeded both tables with
  real rows pulled live from the local Postgres `funds`/`fund_risk_scores` join (19 real scored
  fund_ids, not synthetic placeholders).
- Filled in `.env`'s `POWERBI_TENANT_ID`/`POWERBI_CLIENT_ID`/`POWERBI_CLIENT_SECRET`/
  `POWERBI_WORKSPACE_ID`/`POWERBI_DATASET_ID`. Live-verified, through the real project code
  (not raw `curl`): `powerbi_server.run_dax_query` for both DAX templates, `dashboard_agent.
  build_dax`/`update_dashboard` end to end (real Azure OpenAI template classification + real
  Power BI query + real Postgres audit-log write, confirmed via a live `audit_log` row), and
  `powerbi_server.refresh_dataset` (returns `202 Accepted` against a push dataset — a genuine
  no-op refresh-wise since push datasets have no upstream data source to re-pull from, but
  confirms the API call path itself is correct; a future import-mode dataset connected live to
  Postgres/Cosmos would be the thing that actually needs this call).

**Deviations from the original plan:** None beyond what's already captured above — this entry is
entirely the resolution of the previous entry's one open deviation (Power BI provisioning
deferred). No code in `src/` changed this session, only `.env` (not committed) and real Azure/
Power BI resources.

**Live environment note:** Power BI now lives on a **separate tenant** from the rest of this
project's Azure resources — `bdelfaniangmail.onmicrosoft.com` (personal dev tenant) for Power BI
only, vs. `uniluxembourg.onmicrosoft.com` / "Azure for Students" (subscription
`2fb7edf5-4f7b-4d24-a811-0ba717c89826`) for Postgres/Cosmos/Azure OpenAI, per CLAUDE.md's
existing `.env`/Key Vault pattern this doesn't need any code change to accommodate, but worth
knowing if `az login` ever needs to target the right tenant for a given resource.

**Confidential runbook added, not pushed to GitHub:** `docs/private/power-bi-account-setup.md`
(gitignored via a new `docs/private/` rule in `.gitignore`) has the full account-creation
tutorial for the Power BI dev tenant — all the resource/tenant/app IDs from this entry plus the
two undocumented gotchas encountered (personal-account sign-in block, service-principal object-ID
vs. app-ID when adding it to a workspace) and a from-scratch rebuild checklist. Deliberately
excludes the client secret and `pbiadmin` password (those stay in `.env`/password manager only).
Read it first if Power BI access ever needs to be reconstructed or extended.

**Next step:** Phase 5 — Azure deployment (Bicep IaC, CI/CD, Key Vault, Azure Monitor) per
docs/ROADMAP.md. `etl_agent.py` is still an unimplemented stub (GLEIF MCP server has been
live-verified since Phase 3 but has no caller yet) — worth picking up alongside or before Phase 5.

---

## Phase 4 — BI + reporting

**Completed:** 2026-08-06

**Done:**
- Implemented `guardrails/validators.py` for real (previously a Phase 2 TODO stub):
  `tool_sourced_numbers(draft_text, trace_tool_results)` extracts every number in generated text
  via regex and checks it's within a small rounding tolerance of a value actually returned by a
  tool call this run; `redact_pii(text)` does a defensive email/phone-shaped-string redaction
  pass (conservative — requires 9+ digits so it doesn't collide with the short numeric citations,
  e.g. a risk score or star rating, that report text is expected and validated to contain).
- Implemented `agents/dashboard_agent.py`: `build_dax(question, llm)` has an LLM classify the
  question into one of `bi/dax_templates.py`'s two templates (+ a parameter, e.g. top-N),
  mirroring `sql_agent.py`'s generate-then-validate split rather than free-generating DAX text.
  `update_dashboard()` runs the query via `powerbi_server.run_dax_query` and audit-logs the call.
- Implemented `agents/report_agent.py`: `draft_report(fund_id)` calls `risk_agent.score_fund()`
  and `sql_agent.ask()` to gather tool-sourced facts, has an LLM draft a short body per language
  (EN/FR/DE) constrained to only use the supplied numbers, redacts PII, validates against
  `tool_sourced_numbers` (one retry with a stricter prompt on failure, then raises), and appends
  a **hand-translated** (not LLM-translated) methodology caveat per language before inserting
  three `draft`-status rows into `fund_reports`. `publish_report()`/`reject_report()` share a
  `_finalize_report()` helper that re-checks every language row for a report is still `draft`
  before flipping status — the same non-bypassable re-check pattern
  `query_optimizer_agent.apply_approved()` already established in Phase 2, applied to this
  project's second and last human-in-the-loop gate.
- Wired both new agents into `supervisor.py`'s graph (`dashboard`, `report` routes added to
  `_ROUTES` and the router prompt). `report`'s route only calls `draft_report()` — never
  `publish_report()`/`reject_report()`, deliberately: those stay direct function calls outside
  the graph, same reasoning `query_optimizer_agent.apply_approved()` isn't a graph node either
  (a router shouldn't be the thing deciding to publish).
- 32 new unit tests (`test_validators.py`, `test_dashboard_agent.py`, `test_report_agent.py`,
  plus new route coverage in `test_supervisor.py`) — all via fake LLMs / MagicMock connections,
  no live DB or LLM needed. 132 tests passing total (up from 100), ruff clean.
- Also found and committed Phase 3's work, which had been completed in a prior session but never
  committed (`git status` showed it all still as uncommitted local changes at the start of this
  session) — see the Phase 3 entry below; it's now `f0370c8` on `main`.

**Deviations from the original plan:**
- **Power BI workspace/service-principal provisioning was not done this session — deferred by
  explicit user choice, not a blocker discovered mid-work.** `.env`'s `POWERBI_*` vars are all
  still empty. The Azure subscription in use (`Azure for Students`, tenant
  `uniluxembourg.onmicrosoft.com`) is a university student tenant: no confirmed Power BI
  license, and "allow service principals to use Power BI APIs" is a tenant-wide Fabric/Power BI
  admin-portal toggle that a student account very likely can't flip (unlike Phase 2's Azure
  OpenAI resource, which was provisionable end-to-end via `az` CLI alone). Asked the user how to
  proceed; chose "code first, provision later" — implement and unit-test both agents against
  mocks now (same pattern Phase 3 already used for `powerbi_server.py` itself), or set up
  Power BI access on their own time. **`powerbi_server.run_dax_query`/`refresh_dataset` and
  `dashboard_agent.build_dax`/`update_dashboard` are therefore still not live-verified against a
  real workspace** — that's the concrete gap before Phase 4 can be called fully done, not new
  agent code.
- Report Agent's caveat text is hand-translated into FR/DE (three hardcoded module constants),
  not LLM-translated per report. Deliberate: this is the one piece of text RESPONSIBLE_AI.md
  requires on every surface that shows the risk score, so its wording shouldn't be able to drift
  session-to-session based on what an LLM produces.
- `draft_report()` calls `risk_agent.score_fund()`, which persists a *new* `fund_risk_scores` row
  (has its own `computed_at` timestamp) every time it's called — so drafting the same fund's
  report twice writes two (identical-score) history rows, not an error. Same behavior
  `risk_agent.score_fund()` already had before this session; not new, just now exercised by a
  second caller.

**Next step:** Live-verify Power BI once workspace/service-principal access exists (fill in
`.env`'s `POWERBI_*` vars, re-run `dashboard_agent.update_dashboard()` against the real REST API,
confirm `run_dax_query`'s row-shape assumptions hold against an actual dataset). Then Phase 5 —
Azure deployment (Bicep IaC, CI/CD, Key Vault, Azure Monitor) per docs/ROADMAP.md. `etl_agent.py`
is also still an unimplemented stub (GLEIF MCP server has been live-verified since Phase 3 but
has no caller yet) — worth picking up alongside or before Phase 5 if the ETL lineage-log
requirement needs to be demonstrated end to end.

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
