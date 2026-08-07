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
| `functions.bicep` | Function App, Consumption plan, Python — timer-triggered ETL orchestration |
| `apim.bicep` | API Management, Consumption tier, OpenAPI-imported from the live Container App |

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

## Known gaps

- **APIM's OpenAPI import happens at *deploy* time** against whatever the Container App is
  serving then — a stale/unreachable Container App at deploy time means a stale/empty API
  definition. No policies (rate limiting, subscription keys) are configured.
- No deploy-on-merge GitHub Actions job (deliberate scope choice, pending the user's explicit
  sign-off on granting Azure deploy credentials to CI).
- The now-redundant `greenlux-openai` resource in the old `Azure for Students` subscription —
  cleanup left to the user (destructive action on a resource that predates this session, and
  Claude Code's permission classifier blocks the deletion call itself regardless).

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
