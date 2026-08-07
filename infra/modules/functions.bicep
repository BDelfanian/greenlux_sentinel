// Azure Functions (Consumption plan, Linux, Python) -- timer-triggered ETL orchestration.
// docs/ARCHITECTURE.md#azure-service-map originally left this as "Azure Data Factory or Azure
// Functions"; Functions is the concrete choice here (see docs/PROGRESS_LOG.md Phase 5 entry for
// why: Python-native, matches etl/*.py directly with no pipeline-JSON translation layer, and
// Consumption pricing is near-zero for a once-a-day/on-demand ETL run at this project's scale).
//
// SCM_DO_BUILD_DURING_DEPLOYMENT / ENABLE_ORYX_BUILD are deliberately 'false': live-verified in
// Phase 5 that Azure's remote (Oryx) build does not reliably work for this app (it silently
// dropped files it hadn't itself pip-installed, and wiped a pre-placed .python_packages back to
// whatever requirements.txt alone produced -- even losing packages requirements.txt still
// listed). Deployment instead ships a fully self-contained package built locally by
// scripts/build_function_package.py -- see infra/README.md's Functions deployment section. If a
// future `az deployment group create` needs to reset these to re-enable remote build for some
// other reason, do it deliberately, not by accident via a Bicep redeploy overwriting them back
// to Azure's default (which is effectively "true").

param location string
param namePrefix string
param environmentName string
param uniqueSuffix string
param functionsStorageConnectionString string
param appInsightsConnectionString string
param keyVaultUri string
param keyVaultName string
param landingStorageAccountName string
param postgresFqdn string
param postgresDatabase string
param postgresAdministratorLogin string
param cosmosEndpoint string
param cosmosDatabase string
param cosmosContainer string
param gleifApiBaseUrl string

var planName = 'plan-${namePrefix}-etl-${environmentName}'
var functionAppName = take('func-${namePrefix}-etl-${environmentName}-${uniqueSuffix}', 60)

resource consumptionPlan 'Microsoft.Web/serverfarms@2022-09-01' = {
  name: planName
  location: location
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
  }
  kind: 'functionapp'
  properties: {
    reserved: true
  }
}

resource functionApp 'Microsoft.Web/sites@2022-09-01' = {
  name: functionAppName
  location: location
  kind: 'functionapp,linux'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: consumptionPlan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.12'
      appSettings: [
        { name: 'AzureWebJobsStorage', value: functionsStorageConnectionString }
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'AZURE_KEY_VAULT_URL', value: keyVaultUri }
        { name: 'POSTGRES_HOST', value: postgresFqdn }
        { name: 'POSTGRES_PORT', value: '5432' }
        { name: 'POSTGRES_DB', value: postgresDatabase }
        { name: 'POSTGRES_USER', value: postgresAdministratorLogin }
        { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
        { name: 'COSMOS_DATABASE', value: cosmosDatabase }
        { name: 'COSMOS_CONTAINER', value: cosmosContainer }
        { name: 'GLEIF_API_BASE_URL', value: gleifApiBaseUrl }
        { name: 'LANDING_STORAGE_ACCOUNT_NAME', value: landingStorageAccountName }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'false' }
        { name: 'ENABLE_ORYX_BUILD', value: 'false' }
      ]
    }
  }
}

var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var storageBlobDataReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource keyVaultExisting 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource keyVaultAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVaultExisting.id, functionApp.id, keyVaultSecretsUserRoleId)
  scope: keyVaultExisting
  properties: {
    principalId: functionApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalType: 'ServicePrincipal'
  }
}

resource landingStorageExisting 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: landingStorageAccountName
}

resource landingStorageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(landingStorageExisting.id, functionApp.id, storageBlobDataReaderRoleId)
  scope: landingStorageExisting
  properties: {
    principalId: functionApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataReaderRoleId)
    principalType: 'ServicePrincipal'
  }
}

output functionAppName string = functionApp.name
