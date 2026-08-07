// Phase 5 (docs/ROADMAP.md) -- full service map from docs/ARCHITECTURE.md#azure-service-map,
// as composable modules under infra/modules/. Power BI itself is deliberately NOT provisioned
// here: the live workspace/dataset/service-principal already exist in a separate personal
// tenant (docs/PROGRESS_LOG.md's Phase 4 entry explains why -- the main subscription's
// university tenant has no Power BI license). Only POWERBI_CLIENT_SECRET's Key Vault entry is
// this template's concern, and even that must be set post-deploy since the app registration it
// belongs to isn't managed by this Bicep either.
//
// Deploy flow, resource-group scope: see infra/README.md.

targetScope = 'resourceGroup'

@description('Short environment tag used in resource names, e.g. dev, staging, prod.')
param environmentName string = 'dev'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Prefix used in every resource name for this project.')
param namePrefix string = 'greenlux'

@description('Postgres administrator login password. Supply via a secure parameters file or CLI prompt -- never commit it.')
@secure()
param postgresAdministratorPassword string

@description('Bearer token the agent API (api/app.py) checks incoming requests against. Supply via a secure parameters file or CLI prompt -- never commit it. Leave empty to deploy with auth disabled (matches the local-dev default -- see api/app.py).')
@secure()
param apiAuthToken string = ''

@description('Entra object ID of the human who should get Key Vault Secrets Officer (to set the two secrets this deployment cannot populate itself: langchain-api-key, powerbi-client-secret). Leave empty to skip.')
param adminPrincipalId string = ''

@description('Publisher email required by API Management.')
param apimPublisherEmail string

@description('Agent API container image (ACR-hosted once built and pushed — see infra/README.md). Defaults to a public placeholder so this template deploys before that image exists.')
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

var uniqueSuffix = uniqueString(resourceGroup().id)

// --- Observability (created first -- every other module's diagnosticSettings points at it) ---

module logAnalytics 'modules/log-analytics.bicep' = {
  name: 'log-analytics'
  params: {
    location: location
    namePrefix: namePrefix
    environmentName: environmentName
  }
}

// --- Secrets ---

module keyVault 'modules/key-vault.bicep' = {
  name: 'key-vault'
  params: {
    location: location
    namePrefix: namePrefix
    environmentName: environmentName
    uniqueSuffix: uniqueSuffix
    logAnalyticsWorkspaceId: logAnalytics.outputs.logAnalyticsWorkspaceId
    adminPrincipalId: adminPrincipalId
  }
}

// --- Data layer ---

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: {
    location: location
    namePrefix: namePrefix
    environmentName: environmentName
    uniqueSuffix: uniqueSuffix
  }
}

module postgres 'modules/postgres.bicep' = {
  name: 'postgres'
  params: {
    location: location
    namePrefix: namePrefix
    environmentName: environmentName
    uniqueSuffix: uniqueSuffix
    logAnalyticsWorkspaceId: logAnalytics.outputs.logAnalyticsWorkspaceId
    administratorPassword: postgresAdministratorPassword
  }
}

module cosmos 'modules/cosmos.bicep' = {
  name: 'cosmos'
  params: {
    location: location
    namePrefix: namePrefix
    environmentName: environmentName
    uniqueSuffix: uniqueSuffix
    logAnalyticsWorkspaceId: logAnalytics.outputs.logAnalyticsWorkspaceId
  }
}

module openAi 'modules/openai.bicep' = {
  name: 'openai'
  params: {
    location: location
    namePrefix: namePrefix
    environmentName: environmentName
    uniqueSuffix: uniqueSuffix
  }
}

module containerRegistry 'modules/container-registry.bicep' = {
  name: 'container-registry'
  params: {
    location: location
    namePrefix: namePrefix
    environmentName: environmentName
    uniqueSuffix: uniqueSuffix
  }
}

// Secrets generated within this same deployment get written to Key Vault automatically.
// langchain-api-key and powerbi-client-secret come from outside this deployment (LangSmith SaaS,
// a separate-tenant app registration) and must be set post-deploy -- see infra/README.md.

module postgresPasswordSecret 'modules/key-vault-secret.bicep' = {
  name: 'postgres-password-secret'
  params: {
    keyVaultName: keyVault.outputs.keyVaultName
    secretName: 'postgres-password'
    secretValue: postgresAdministratorPassword
  }
}

module cosmosKeySecret 'modules/key-vault-secret.bicep' = {
  name: 'cosmos-key-secret'
  params: {
    keyVaultName: keyVault.outputs.keyVaultName
    secretName: 'cosmos-key'
    secretValue: cosmos.outputs.primaryKey
  }
}

module openAiKeySecret 'modules/key-vault-secret.bicep' = {
  name: 'openai-key-secret'
  params: {
    keyVaultName: keyVault.outputs.keyVaultName
    secretName: 'azure-openai-api-key'
    secretValue: openAi.outputs.apiKey
  }
}

// apiAuthToken is caller-supplied (not generated within this deployment like the three above),
// but it's still written here rather than being one of the "set post-deploy" secrets in
// infra/README.md -- unlike langchain-api-key/powerbi-client-secret, its value is known at
// deploy time, there's just no Azure resource that generates it for us. Conditional: Key Vault
// rejects an empty-string secret value, and an empty apiAuthToken is a valid choice (auth
// disabled -- see api/app.py) that just means "don't create this secret at all."
module apiAuthTokenSecret 'modules/key-vault-secret.bicep' = if (!empty(apiAuthToken)) {
  name: 'api-auth-token-secret'
  params: {
    keyVaultName: keyVault.outputs.keyVaultName
    secretName: 'api-auth-token'
    secretValue: apiAuthToken
  }
}

// --- Compute layer ---

module containerApps 'modules/container-apps.bicep' = {
  name: 'container-apps'
  params: {
    location: location
    namePrefix: namePrefix
    environmentName: environmentName
    logAnalyticsCustomerId: logAnalytics.outputs.logAnalyticsCustomerId
    logAnalyticsSharedKey: logAnalytics.outputs.logAnalyticsSharedKey
    appInsightsConnectionString: logAnalytics.outputs.appInsightsConnectionString
    keyVaultUri: keyVault.outputs.keyVaultUri
    keyVaultName: keyVault.outputs.keyVaultName
    containerRegistryName: containerRegistry.outputs.registryName
    containerRegistryLoginServer: containerRegistry.outputs.loginServer
    containerImage: containerImage
    landingStorageAccountName: storage.outputs.landingStorageAccountName
    postgresFqdn: postgres.outputs.fqdn
    postgresDatabase: postgres.outputs.databaseName
    postgresAdministratorLogin: postgres.outputs.administratorLogin
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabase: cosmos.outputs.databaseName
    cosmosContainer: cosmos.outputs.containerName
    openAiEndpoint: openAi.outputs.endpoint
    openAiDeploymentName: openAi.outputs.deploymentName
    langchainProject: 'greenlux-sentinel'
    langchainEndpoint: 'https://eu.api.smith.langchain.com'
    gleifApiBaseUrl: 'https://api.gleif.org/api/v1'
  }
}

module functionApp 'modules/functions.bicep' = {
  name: 'functions'
  params: {
    location: location
    namePrefix: namePrefix
    environmentName: environmentName
    uniqueSuffix: uniqueSuffix
    functionsStorageConnectionString: storage.outputs.functionsStorageConnectionString
    appInsightsConnectionString: logAnalytics.outputs.appInsightsConnectionString
    keyVaultUri: keyVault.outputs.keyVaultUri
    keyVaultName: keyVault.outputs.keyVaultName
    landingStorageAccountName: storage.outputs.landingStorageAccountName
    postgresFqdn: postgres.outputs.fqdn
    postgresDatabase: postgres.outputs.databaseName
    postgresAdministratorLogin: postgres.outputs.administratorLogin
    cosmosEndpoint: cosmos.outputs.endpoint
    cosmosDatabase: cosmos.outputs.databaseName
    cosmosContainer: cosmos.outputs.containerName
    gleifApiBaseUrl: 'https://api.gleif.org/api/v1'
  }
}

module apim 'modules/apim.bicep' = {
  name: 'apim'
  params: {
    location: location
    namePrefix: namePrefix
    environmentName: environmentName
    uniqueSuffix: uniqueSuffix
    publisherEmail: apimPublisherEmail
    containerAppFqdn: containerApps.outputs.containerAppFqdn
  }
}

// Key Vault RBAC for the two compute identities (Key Vault Secrets User) is granted inside
// container-apps.bicep / functions.bicep themselves, scoped to the identity each module creates
// -- see those modules' keyVaultAccess resource. Keeping it there (rather than here, reading a
// module output back into an `existing` resource + roleAssignment name/scope) sidesteps Bicep's
// BCP120 restriction on using cross-module runtime outputs in an extension resource's name/scope.

output keyVaultName string = keyVault.outputs.keyVaultName
output keyVaultUri string = keyVault.outputs.keyVaultUri
output postgresFqdn string = postgres.outputs.fqdn
output cosmosEndpoint string = cosmos.outputs.endpoint
output openAiEndpoint string = openAi.outputs.endpoint
output containerAppFqdn string = containerApps.outputs.containerAppFqdn
output containerRegistryLoginServer string = containerRegistry.outputs.loginServer
output functionAppName string = functionApp.outputs.functionAppName
output apimGatewayUrl string = apim.outputs.gatewayUrl
output landingStorageAccountName string = storage.outputs.landingStorageAccountName
output logAnalyticsWorkspaceId string = logAnalytics.outputs.logAnalyticsWorkspaceId
