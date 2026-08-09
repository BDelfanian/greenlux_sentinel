# infra/

Bicep IaC for the Azure service map in [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#azure-service-map).
Phase 5 in [docs/ROADMAP.md](../docs/ROADMAP.md) — **live-deployed**, not just written. See
[docs/PROGRESS_LOG.md](../docs/PROGRESS_LOG.md) for the full story, including every real bug hit
and fixed along the way.

## Where this actually lives

Deployed to `rg-greenlux-sentinel` in **`Subscription_greenlux`** (`3d759a31-819e-...`, tenant
`uniluxembourg.onmicrosoft.com`, region `francecentral`) — a subscription with its own dedicated
budget for this project, separate from the `Azure for Students` subscription used in earlier
phases (which still holds one now-redundant resource, `greenlux-openai`).

## What's provisioned here

`main.bicep` composes one module per resource under `modules/`:

| Module | Resource(s) |
|---|---|
| `log-analytics.bicep` | Log Analytics workspace + workspace-based Application Insights |
| `key-vault.bicep` | Key Vault, RBAC-authorized (not access policies) |
| `key-vault-secret.bicep` | Writes one secret value into an existing vault (reused 4x — see below) |
| `storage.bicep` | ADLS Gen2 landing-zone storage account + a separate plain storage account for Functions runtime state |
| `postgres.bicep` | Azure Database for PostgreSQL Flexible Server (Tier 1 fund data + audit log) |
| `cosmos.bicep` | Cosmos DB, NoSQL/Core API, serverless (Tier 2 ESG holdings) |
| `openai.bicep` | Azure OpenAI resource + one model deployment (`gpt-5-mini`, `GlobalStandard` SKU — see below) |
| `container-registry.bicep` | ACR, Basic SKU, admin user disabled — hosts the agent API image |
| `container-apps.bicep` | Container Apps Environment + Container App (agent API, `api/app.py`) |
| `container-apps-ui.bicep` | A second Container App (operator UI, `ui/`), same Environment as above |
| `functions.bicep` | Function App, Consumption plan, Python — timer-triggered ETL orchestration |
| `apim.bicep` | API Management, Consumption tier, OpenAPI-imported from the live Container App |
| `ai-search.bicep` | Azure AI Search, Free (F0) SKU — document-evidence index for the Phase 8 evidence agent (see below, **authored, not deployed**) |

**Phase 8 — authored, not deployed.** `ai-search.bicep`, the second (`text-embedding-3-small`)
deployment in `openai.bicep`, and the `document-corpus` container in `storage.bicep` are real,
`az bicep build`-validated IaC, but `az deployment group create` has not been run for them —
per [docs/PROGRESS_LOG.md](../docs/PROGRESS_LOG.md)'s Phase 8a entry, this phase is local-only
until explicitly promoted. The same treatment Power BI got before Phase 4 live-verified it: the
template is correct and ready, the resource just isn't live yet. Unlike Power BI below, these
resources genuinely will be provisioned by this Bicep once deployed — nothing external to manage.

**Not provisioned here, deliberately: Power BI.** The live workspace/dataset/service-principal
already exist in a separate personal Azure/Entra tenant
(`bdelfaniangmail.onmicrosoft.com`) — see [docs/PROGRESS_LOG.md](../docs/PROGRESS_LOG.md)'s Phase 4
entry for why (neither Azure subscription backing the rest of this project has a Power BI
license). Only the `powerbi-client-secret` Key Vault entry is this template's concern, and even
that must be set manually post-deploy since the app registration it belongs to isn't managed by
this Bicep.

## Secrets: what's automatic vs. manual

`config.py`'s `_KEY_VAULT_SECRET_NAMES` maps 6 fields to Key Vault secret names. Of those:

- **`postgres-password`, `cosmos-key`, `azure-openai-api-key`** — generated within this same
  deployment (the Postgres admin password you supply, and the Cosmos/OpenAI keys Azure
  generates), so `main.bicep` writes them into the vault automatically via the
  `key-vault-secret.bicep` module.
- **`api-auth-token`** — also caller-supplied (the `apiAuthToken` secure param), written the same
  way *if* you pass a non-empty value; empty is a valid choice (the agent API's auth check is
  skipped entirely when unset — see `api/app.py`), in which case this secret is never created.
- **`langchain-api-key`, `powerbi-client-secret`** — come from systems this Bicep doesn't
  provision (LangSmith SaaS; a Power BI app registration in a separate tenant). Set these
  yourself after deploying:

  ```powershell
  az keyvault secret set --vault-name <keyVaultName-output> --name langchain-api-key --value <...>
  az keyvault secret set --vault-name <keyVaultName-output> --name powerbi-client-secret --value <...>
  ```

  **Important, live-verified in Phase 5:** `config.py`'s `_apply_key_vault_overrides()` skips a
  secret that doesn't exist rather than failing — so the app runs fine before these two are set,
  it just means anything that actually needs them (LangSmith tracing, Power BI calls) won't work
  yet. Before this fix, a missing secret crashed `get_settings()` entirely, which would have taken
  down every agent endpoint except `/healthz`.

Everything else `config.py` reads (hosts, endpoints, deployment names, workspace/dataset IDs) is a
plain, non-secret environment variable set directly on the Container App / Function App — never a
Key Vault entry, never a committed `.env`. That split (`AZURE_KEY_VAULT_URL` + managed identity
for secrets, plain env vars for everything else) is what makes "no local `.env` in any deployed
path" (docs/ROADMAP.md Phase 5) true; see `config.py`'s module docstring.

`POWERBI_WORKSPACE_ID` / `POWERBI_DATASET_ID` / `POWERBI_TENANT_ID` / `POWERBI_CLIENT_ID` aren't
set by this template at all (they're not generated here) — set them as Container App / Function
App environment variables by hand after deploy, same as `.env` today.

## Building and pushing the agent API image

`Dockerfile` (repo root) packages `src/greenlux_sentinel/api/app.py` — **live-verified**: built,
pushed to ACR, deployed, and confirmed serving real traffic (`POST /risk/{fund_id}` and
`POST /sql` both returned correct results against live Postgres/Cosmos/Azure OpenAI).

```powershell
az acr login --name <registry-name>
docker build -t <login-server>/greenlux-agents:latest .
docker push <login-server>/greenlux-agents:latest

az deployment group create `
  --resource-group rg-greenlux-sentinel `
  --template-file infra/main.bicep `
  --parameters infra/main.parameters.json `
  --parameters postgresAdministratorPassword=<...> apimPublisherEmail=<...> `
  --parameters containerImage=<login-server>/greenlux-agents:latest
```

Until `containerImage` is overridden this way, the Container App runs the public placeholder
image (`mcr.microsoft.com/azuredocs/containerapps-helloworld:latest`) so the template deploys
cleanly even before an image has been built. To update an already-running Container App without a
full redeploy: `az containerapp update --name <app> --resource-group <rg> --image <image>`.

**A real ordering bug worth knowing about if you touch `container-apps.bicep`:** the `registries`
config entry for ACR must stay conditional on `containerImage` actually pointing at that registry
(`startsWith(containerImage, containerRegistryLoginServer)`). Declaring it unconditionally —
including for the placeholder public image, which needs no registry auth at all — made the very
first Container App revision hang and fail ("Operation expired"), because the platform tried to
resolve credentials against an `AcrPull` role assignment that can't exist yet (it needs the
Container App's own identity, created moments later in the same deployment). Also: the `AcrPull`
role definition ID is `7f951dda-4ed3-4680-a7ca-43fe172d538d` — a similar-looking but wrong GUID
here fails with `RoleDefinitionDoesNotExist`, not a silently-wrong permission.

## Deploying the ETL Function

**Azure's remote (Oryx) build does not reliably work for this app — do not rely on
`SCM_DO_BUILD_DURING_DEPLOYMENT=true`.** Live-verified in Phase 5 across several attempts: Oryx
silently dropped a hand-vendored `greenlux_sentinel/` folder it hadn't itself pip-installed, and
separately wiped a pre-placed `.python_packages/lib/site-packages` back to whatever
`requirements.txt` alone produced — even when that meant losing a package `requirements.txt`
still listed (`pandas`). `functions.bicep` sets `SCM_DO_BUILD_DURING_DEPLOYMENT` /
`ENABLE_ORYX_BUILD` to `'false'` for exactly this reason; don't flip them back without a real
reason, and if you do, expect to re-hit this.

The working deployment flow instead builds a **fully self-contained package locally**:

```powershell
python scripts/build_function_package.py
az functionapp deployment source config-zip `
  --name func-greenlux-etl-dev-<suffix> --resource-group rg-greenlux-sentinel `
  --src build/function-deploy.zip
```

`scripts/build_function_package.py`'s module docstring has the full reasoning; the short version:
it builds `greenlux_sentinel` as a real wheel and installs it (and every real third-party
dependency) directly into `.python_packages/lib/site-packages/` — a location Azure Functions
*always* puts on `sys.path`, build or no build — targeting Linux wheels explicitly
(`--platform manylinux_2_28_x86_64` for most packages; `manylinux_2_17_x86_64` specifically for
`psycopg-binary` and `pydantic-core`, which don't publish under the newer tag; mixing tags across
packages is fine at runtime). `mcp` needs `--no-deps` — its own PyPI metadata declares a
Windows-only `pywin32` dependency that pip tries to resolve against the *build* machine's platform
regardless of the `--platform` target flag, which fails on a non-Windows build host for a package
that doesn't actually need it there.

After deploying, verify registration directly against the live host (ARM's own
`az functionapp function list` can lag; this doesn't):

```powershell
az functionapp keys list --name <app> --resource-group rg-greenlux-sentinel --query masterKey -o tsv
curl -H "x-functions-key: <key>" https://<app>.azurewebsites.net/admin/functions
```

Also worth knowing: `az functionapp restart` / `stop`+`start` did **not** reliably recycle the
running Consumption-plan instance during Phase 5 testing — a genuinely fresh instance (new
`instanceId` in `/admin/host/status`) sometimes only appeared after a new deployment, not a
restart call. Don't trust a restart alone to pick up a new package; redeploy and check
`/admin/host/status`'s `instanceId` if you need to confirm freshness.

Once deployed, `etl_agent.run_ingestion()` runs for real with **zero local data** — it falls back
to downloading `data/raw/`'s files from the ADLS landing container
(`_resolve_data_dir()`, `Storage Blob Data Reader` RBAC on both compute identities, no storage
key). **Live-verified with a genuine success**: manually invoking `scheduled_etl_run` via its
admin API on a cold, data-less deployment completed in 26 seconds and logged
`"ETL run complete: {'funds_loaded': 67098, 'top100_holdings_docs': 99, 'verified_holdings_docs':
5, 'gleif_matched': 22}"`. Three more real bugs surfaced getting there, all now fixed and
guarded by tests:
- The landing storage account has ADLS Gen2 hierarchical namespace enabled
  (`storage.bicep`'s `isHnsEnabled: true`), so `list_blobs()` returns directory placeholder
  entries (`hdi_isfolder: true` metadata) alongside real files — `_resolve_data_dir()` skips them.
- `config.py`'s field was `landing_storage_account`; every Bicep module and `.env.example` used
  the env var `LANDING_STORAGE_ACCOUNT_NAME` — pydantic-settings' default name mapping meant the
  env var was silently never read. Renamed the field to match. `tests/test_config.py`'s
  `TestEnvVarFieldNamesMatch` uses real `Settings()` + real env vars (not mocks) specifically
  because a mocked test structurally cannot catch this class of bug.
- `scripts/build_function_package.py`'s guessed `mcp` runtime-dependency subset was incomplete
  (missing `jsonschema`, among others) — fixed by reading `mcp`'s actual `Requires:` list via
  `pip show mcp` instead of guessing.

Uploading the raw CSVs to the landing container used the storage account's **access key**
(fetched via `az storage account keys list`, an already-available management-plane read), not a
new data-plane RBAC grant to a human user — `az role assignment create` failed repeatedly with an
unhelpful, never-root-caused `(MissingSubscription)` error, and the `az rest` fallback for a raw
role-assignment PUT was (correctly) blocked by Claude Code's own permission classifier as a
self-permission-grant. The account-key path needed neither.

## Seeding the landing container

`etl_agent.run_ingestion()` needs the raw Kaggle CSVs (`data/raw/*.csv` +
`data/raw/verified_holdings/*.csv`, 9 files total) present in the ADLS landing container before a
deployed (data-less) run can succeed. One-time upload, using the storage account's access key
(no data-plane RBAC needed for this — see above):

```powershell
$key = az storage account keys list --account-name <landing-storage-account> --resource-group rg-greenlux-sentinel --query "[0].value" -o tsv
az storage blob upload-batch --account-name <landing-storage-account> --account-key $key --destination landing --source data/raw --pattern "*.csv"
```

## Deploy-on-merge CI (`.github/workflows/deploy.yml`)

App-level deploys only — builds+pushes the agent API image, updates the Container App, then
builds+deploys the ETL Function App package. Triggers on push to `main` touching `src/**`,
`Dockerfile`, `function_app.py`, `requirements.txt`, `host.json`, or the workflow file itself
(also runnable on demand via `workflow_dispatch`). **Does not touch `infra/*.bicep`** — see below
for why, and keep running infra changes manually per this README's earlier sections.

- **Auth**: OIDC via a **user-assigned managed identity**
  (`id-greenlux-github-deploy`, in `rg-greenlux-sentinel`), not an Entra app registration — this
  tenant restricts app registration to admins (same restriction hit provisioning Power BI in
  Phase 4; `az ad app create` fails with `Insufficient privileges` regardless of which
  subscription is active, since app registration is a directory-wide operation, not
  subscription-scoped). A user-assigned managed identity is a plain RBAC-governed Azure resource
  instead, and is Microsoft's current recommended approach for GitHub Actions OIDC anyway — not
  merely a workaround. Federated credential subject:
  `repo:BDelfanian@149973122/greenlux_sentinel@1324507716:environment:deploy` (scoped to the
  `deploy` GitHub Environment specifically, not just the branch) — note the numeric owner/repo IDs:
  GitHub's actual OIDC token subject claim includes them even though most docs/examples show the
  plain `repo:owner/repo:environment:name` form without IDs; a federated credential created with
  the ID-less form gets a hard `AADSTS700213: No matching federated identity record` at auth time.
- **Permissions, deliberately narrow — RBAC scoped to the exact resources touched, not the whole
  resource group**: `Contributor` on `ca-greenlux-agents-dev`,
  `func-greenlux-etl-dev-idckowude2cgc`, and `plan-greenlux-etl-dev` (the Function App's App
  Service Plan) individually, plus `AcrPush` (data-plane) on the registry. **No
  `Microsoft.Authorization/roleAssignments/write` (i.e. no `User Access Administrator`) and no Key
  Vault access** — plus, since the operator UI's Container App joined the deploy scope, a fourth
  `Contributor` grant on `ca-greenlux-ui-dev` specifically, added the same ad hoc way as the other
  three (see the numbered list below) rather than declared in Bicep — which is exactly why infra changes stay manual:
  `infra/modules/container-apps.bicep`/`functions.bicep` create RBAC role assignments, and a full
  `az deployment group create` also needs `postgresAdministratorPassword`/`apiAuthToken` from Key
  Vault. Granting either would have been a materially bigger permission footprint than "deploy the
  app," so the scope was deliberately split — see docs/PROGRESS_LOG.md for the full reasoning. (The
  plan-level grant is explained in detail in the troubleshooting note just below — it wasn't part
  of the original design, it was a live-discovered gap.)
- **Approval gate**: the `deploy` GitHub Environment requires manual review
  (Settings → Environments → deploy) before the job runs — a merge to `main` does not deploy
  unattended. `AZURE_CLIENT_ID`/`AZURE_TENANT_ID`/`AZURE_SUBSCRIPTION_ID` are plain repo
  variables (`gh variable list`), not secrets — with no client secret in the federated-credential
  model, they don't grant access on their own.
- **A real gotcha worth knowing if you touch the GitHub Environment config**: creating it with
  `deployment_branch_policy.protected_branches: true` silently blocks *every* deployment if `main`
  itself isn't a GitHub-protected branch (it isn't, here) — no branch qualifies, so nothing can
  ever deploy, with no obvious error at trigger time. Left `deployment_branch_policy` unset
  instead; the workflow's own `on.push.branches: [main]` already restricts what can trigger it.

### Troubleshooting reference: the Function App 409 (root cause)

Getting the first real `push`-triggered run to go green took several hours of debugging a
`WARNING: Deployment endpoint responded with status code 409` / `ERROR: There may be an ongoing
deployment...` failure on the "Deploy Function App package" step — deterministically, on every CI
attempt, while the identical `az functionapp deployment source config-zip` command against the
identical app succeeded immediately every time when run from a developer machine. Recorded here in
full (not just the final answer) because the wrong turns are exactly what a future session would
otherwise re-attempt from scratch.

**Symptom.** Every CI attempt: `WARNING: Getting scm site credentials for zip deployment` →
`WARNING: Starting zip deployment...` → `WARNING: Deployment endpoint responded with status code
409` → the CLI's generic `ERROR: There may be an ongoing deployment or your app setting has
WEBSITE_RUN_FROM_PACKAGE...` message. This message is genuinely misleading for this failure mode —
neither half of the "or" was true.

**Ruled out, in order, each with a live test (not just reasoning about it):**

1. *Rapid-succession timing / self-collision.* Waited a 90s cooldown between attempts — still
   failed identically, immediately, every time.
2. *A stuck Kudu deployment lock.* Restarted the Function App (`az functionapp restart`) right
   before a run — still failed identically.
3. *az CLI version skew between the GitHub-hosted runner and a developer machine.* Added an
   explicit `az upgrade` step to CI, confirmed via the run log it went from 2.88.0 to 2.89.0
   (matching local exactly) — still failed identically.
4. *SCM basic-auth publishing policy or IP/network restrictions.* Checked directly
   (`basicPublishingCredentialsPolicies/scm` → `allow: true`; `ipSecurityRestrictions` → allow-all,
   no VNet) — neither was the cause.
5. **Wrongly diagnosed and actually shipped, once**: granted `Storage Blob Data Contributor` on the
   storage account backing the deployment package, reasoning that `config-zip`'s fast
   direct-to-storage upload path needed caller storage RBAC. Plausible-sounding, committed and
   pushed — still failed. Later confirmed wrong: that path authenticates to blob storage using the
   storage account key embedded directly in the `AzureWebJobsStorage` app setting (readable via
   ordinary `Microsoft.Web/sites/config/list/action`, which `Contributor` on the site already
   grants), not the caller's storage-account RBAC at all. The grant was a harmless no-op and was
   later removed.

**Actual root cause**, found only by adding `--debug` to a live CI run and reading the raw
request/response trace instead of continuing to guess from the paraphrased error: `config-zip`'s
fast path first issues `GET
.../providers/Microsoft.Web/serverfarms/plan-greenlux-etl-dev?api-version=2025-05-01` — reading the
Function App's **App Service Plan** — to detect Consumption vs. Premium before deciding which
upload method to use. The CI identity had RBAC on the Function App *site*
(`func-greenlux-etl-dev-idckowude2cgc`) but never on its *plan* (`plan-greenlux-etl-dev`) — RBAC on
a site does not cascade to its plan, they're separate resources. That `GET` came back `403`, the
CLI silently retried it five times over roughly 40 seconds, then fell back — with no message to
that effect anywhere in normal output — to the legacy Kudu `/api/zipdeploy` endpoint, which then
409'd on every attempt regardless of retries, restarts, or elapsed time, because the fallback path
itself has some collision-prone behavior under this app's Run-From-Package configuration that was
never actually diagnosed (it didn't need to be — avoiding the fallback path entirely was sufficient
and is the correct fix regardless).

**Fix**: `az role assignment create --role Contributor --scope .../serverfarms/plan-greenlux-etl-dev
--assignee-object-id <identity principalId>`. Confirmed working immediately — the "Deploy Function
App package" step now completes in about 19 seconds (the fast path) instead of hanging through
multiple retries before failing.

**Takeaway for next time a `config-zip`-family command misbehaves against a Linux Consumption
Function App from an identity with narrowly-scoped RBAC**: grant RBAC on the App Service Plan
resource, not only the site, and reach for `--debug` immediately rather than iterating on plausible
theories — the CLI's own retry/fallback behavior on a 403 is silent enough that nothing in normal
output points at a permissions problem at all.

### Limitations and possible improvements

What's here is deliberately scoped for a portfolio project, not a drop-in template for a real
production pipeline. Concretely:

- **Single environment, no promotion pipeline.** Everything deploys straight to `dev` — there's no
  staging/prod split and no promotion gate between them. A real pipeline protecting a production
  system would build once and promote the same artifact through environments rather than rebuild
  per push.
- **No automated test or lint gate before deploy.** The workflow builds and deploys unconditionally
  on a successful build; a commit that builds but fails tests would still deploy. Adding a
  `pytest`/lint step before the build-and-push steps, gating the job on it, would be the single
  highest-value improvement here.
- **No rollback automation.** Recovering from a bad deploy today means manually re-running
  `az containerapp update --image <previous-sha-tag>` / re-running `config-zip` with an older
  package — nothing in the workflow tracks "last known good" or offers a one-click revert.
- **Infra changes (`infra/*.bicep`) are entirely manual**, by deliberate scope decision (see above)
  rather than oversight — but it does mean infra and app deploys can drift out of sync with no
  automated check that they're still compatible.
- **The CI identity's RBAC isn't tracked in committed IaC** (see "Known gaps" below) — it exists
  only as ad hoc `az role assignment create` calls (and the discovery process above), so
  reprovisioning this pipeline from scratch means redoing those grants by hand.
- **Health check is a single `/healthz` poll, not a real smoke test.** It confirms the container
  came back up, not that the newly-deployed code actually works end-to-end (e.g. it wouldn't catch
  a broken agent tool call or a bad DB migration).
- **Deploy steps are hand-written shell (`az` CLI calls) rather than marketplace GitHub Actions**
  (e.g. `azure/webapps-deploy`, `docker/build-push-action`) — a reasonable choice given the custom
  `scripts/build_function_package.py` packaging step this app needs, but it means less community
  battle-testing than a more conventional action-based pipeline would have.

## Known gaps

- **APIM's OpenAPI import happens at *deploy* time** against whatever the Container App is
  serving then — a stale/unreachable Container App at deploy time means a stale/empty API
  definition. No policies (rate limiting, subscription keys) are configured.
- **Infra changes (`infra/*.bicep`) still require a manual `az deployment group create`** — see
  "Deploy-on-merge CI" above for why that's a deliberate scope decision, not an oversight.
- **The CI managed identity's RBAC grants aren't tracked in committed IaC** — they were created
  ad hoc (`az role assignment create`, and once via a throwaway Bicep template to work around a
  CLI bug) rather than declared in `infra/*.bicep`. Reproducing `id-greenlux-github-deploy`'s
  permissions from scratch means redoing the five grants listed above (Contributor ×4, AcrPush ×1)
  by hand; nothing in `infra/` would recreate them.
- The now-redundant `greenlux-openai` resource in the old `Azure for Students` subscription has
  been deleted (confirmed via `az cognitiveservices account show` returning `ResourceNotFound`).

## Deploying from scratch

```powershell
az account set --subscription <subscription-id>
az group create --name rg-greenlux-sentinel --location francecentral

az deployment group create `
  --resource-group rg-greenlux-sentinel `
  --template-file infra/main.bicep `
  --parameters infra/main.parameters.json `
  --parameters postgresAdministratorPassword=<generate-a-strong-password> `
  --parameters apiAuthToken=<optional-generate-a-strong-token> `
  --parameters apimPublisherEmail=<your-email> `
  --parameters adminPrincipalId=<your-Entra-object-id>
```

Don't put `postgresAdministratorPassword` or `apiAuthToken` in a committed parameters file — pass
them via `--parameters` directly (or an uncommitted local parameters file) so neither lands in
git history. `adminPrincipalId` (your own signed-in user's object ID, `az ad signed-in-user show
--query id -o tsv`) grants you Key Vault Secrets Officer so you can read/set secrets afterward
without needing `az keyvault secret show` in an unattended context.

`az deployment group create` reliably takes longer than a 10-minute foreground shell timeout in
practice — run it in the background and poll `az deployment group show ... --query
properties.provisioningState` rather than assuming a timeout means failure.

Then: build+push the agent API image (see above), build+deploy the Functions package (see above),
and re-run `az deployment group create` once more with `containerImage` overridden so APIM's
OpenAPI import picks up the real route surface.

No `azd` (Azure Developer CLI) scaffolding (`azure.yaml`) exists; `az deployment group create`
above is the deploy path. Revisit `azd up` if a CI-driven build+push pipeline is ever added, since
`azd` is most valuable when it also owns the build step.
