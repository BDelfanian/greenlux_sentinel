// Container Apps Environment + Container App -- hosts the agent API (Dockerfile, src/greenlux_sentinel/api/app.py)
// (docs/ARCHITECTURE.md#azure-service-map). System-assigned managed identity is how the deployed
// app authenticates to Key Vault via config.py's DefaultAzureCredential path -- no secret
// material is baked into the container image or its env vars, only AZURE_KEY_VAULT_URL plus the
// non-secret settings (hosts, endpoints, IDs). The same identity also pulls the image from ACR
// (AcrPull role assignment below) -- no registry admin credentials anywhere in this template.
//
// TODO before this is a real deployment: `containerImage` defaults to a placeholder public
// "hello world" image so `az deployment group create` succeeds without an image already having
// been pushed. Build and push the real image first (see infra/README.md), then redeploy with
// `--parameters containerImage=<acr-login-server>/greenlux-agents:<tag>`.

param location string
param namePrefix string
param environmentName string
param logAnalyticsCustomerId string
@secure()
param logAnalyticsSharedKey string
param appInsightsConnectionString string
param keyVaultUri string
param keyVaultName string
param containerRegistryName string
param containerRegistryLoginServer string
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param landingStorageAccountName string
param postgresFqdn string
param postgresDatabase string
param postgresAdministratorLogin string
param cosmosEndpoint string
param cosmosDatabase string
param cosmosContainer string
param openAiEndpoint string
param openAiDeploymentName string
param openAiEmbeddingDeploymentName string
param azureSearchEndpoint string
param azureSearchIndexName string
param langchainProject string
param langchainEndpoint string
param gleifApiBaseUrl string

var environmentNameResource = 'cae-${namePrefix}-${environmentName}'
var containerAppName = 'ca-${namePrefix}-agents-${environmentName}'

// Only declare the ACR registry entry once containerImage actually points at it. Declaring it
// unconditionally (even for the placeholder public image, which needs no auth at all) made the
// platform try to resolve ACR credentials via the container app's own not-yet-granted
// AcrPull role assignment during the very first revision's provisioning -- a chicken-and-egg
// ordering problem (the role assignment below needs this resource's principalId to exist first)
// that manifested as "Operation expired" and a permanently unhealthy first revision. Once a real
// image is pushed and `containerImage` is overridden to point at this ACR, this becomes true on
// a second deploy -- by then the role assignment from *this* deploy has long since propagated.
var usesContainerRegistry = startsWith(containerImage, containerRegistryLoginServer)

resource managedEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: environmentNameResource
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalyticsSharedKey
      }
    }
  }
}

resource containerApp 'Microsoft.App/containerApps@2023-05-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
      }
      activeRevisionsMode: 'Single'
      registries: usesContainerRegistry
        ? [
            {
              server: containerRegistryLoginServer
              identity: 'system'
            }
          ]
        : []
    }
    template: {
      containers: [
        {
          // Placeholder default -- see module header TODO.
          name: 'agents'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'AZURE_KEY_VAULT_URL', value: keyVaultUri }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'POSTGRES_HOST', value: postgresFqdn }
            { name: 'POSTGRES_PORT', value: '5432' }
            { name: 'POSTGRES_DB', value: postgresDatabase }
            { name: 'POSTGRES_USER', value: postgresAdministratorLogin }
            { name: 'COSMOS_ENDPOINT', value: cosmosEndpoint }
            { name: 'COSMOS_DATABASE', value: cosmosDatabase }
            { name: 'COSMOS_CONTAINER', value: cosmosContainer }
            { name: 'AZURE_OPENAI_ENDPOINT', value: openAiEndpoint }
            { name: 'AZURE_OPENAI_DEPLOYMENT', value: openAiDeploymentName }
            { name: 'AZURE_OPENAI_EMBEDDING_DEPLOYMENT', value: openAiEmbeddingDeploymentName }
            { name: 'AZURE_SEARCH_ENDPOINT', value: azureSearchEndpoint }
            { name: 'AZURE_SEARCH_INDEX_NAME', value: azureSearchIndexName }
            { name: 'LANGCHAIN_TRACING_V2', value: 'true' }
            { name: 'LANGCHAIN_PROJECT', value: langchainProject }
            { name: 'LANGCHAIN_ENDPOINT', value: langchainEndpoint }
            { name: 'GLEIF_API_BASE_URL', value: gleifApiBaseUrl }
            { name: 'LANDING_STORAGE_ACCOUNT_NAME', value: landingStorageAccountName }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var storageBlobDataReaderRoleId = '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'

resource keyVaultExisting 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource keyVaultAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVaultExisting.id, containerApp.id, keyVaultSecretsUserRoleId)
  scope: keyVaultExisting
  properties: {
    principalId: containerApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalType: 'ServicePrincipal'
  }
}

resource containerRegistryExisting 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: containerRegistryName
}

resource acrPullAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistryExisting.id, containerApp.id, acrPullRoleId)
  scope: containerRegistryExisting
  properties: {
    principalId: containerApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalType: 'ServicePrincipal'
  }
}

resource landingStorageExisting 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: landingStorageAccountName
}

resource landingStorageAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(landingStorageExisting.id, containerApp.id, storageBlobDataReaderRoleId)
  scope: landingStorageExisting
  properties: {
    principalId: containerApp.identity.principalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataReaderRoleId)
    principalType: 'ServicePrincipal'
  }
}

output containerAppName string = containerApp.name
output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn
