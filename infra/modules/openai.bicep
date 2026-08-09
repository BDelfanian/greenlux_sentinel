// Azure AI Foundry / Azure OpenAI resource -- LLM backing every agent (docs/ARCHITECTURE.md#azure-service-map).
// Default deployment name/model mirrors the one already live-verified in Phase 2-4
// (docs/PROGRESS_LOG.md) so AZURE_OPENAI_DEPLOYMENT can point at it unchanged.

param location string
param namePrefix string
param environmentName string
param uniqueSuffix string
param deploymentName string = 'gpt-5-mini'
param modelName string = 'gpt-5-mini'
param modelVersion string = '2025-08-07'
// GlobalStandard, not the classic per-region 'Standard' -- confirmed via
// `az cognitiveservices account list-models`: gpt-5-mini in this subscription/region only
// offers GlobalStandard, DataZoneStandard, or the Provisioned-Managed SKUs, no plain 'Standard'.
param deploymentSkuName string = 'GlobalStandard'
param skuCapacity int = 10
// Phase 8a: embedding model backing the document-evidence search index (docs/PROGRESS_LOG.md).
// Same account, a second deployment -- no new Cognitive Services resource needed.
param embeddingDeploymentName string = 'text-embedding-3-small'
param embeddingModelVersion string = '1'
param embeddingSkuCapacity int = 10

var accountName = 'oai-${namePrefix}-${environmentName}-${uniqueSuffix}'

resource openAiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: accountName
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'None'
  }
  properties: {
    customSubDomainName: accountName
    publicNetworkAccess: 'Enabled'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openAiAccount
  name: deploymentName
  sku: {
    name: deploymentSkuName
    capacity: skuCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openAiAccount
  name: embeddingDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: embeddingSkuCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingDeploymentName
      version: embeddingModelVersion
    }
  }
  // Deployments on the same account provision sequentially, not in parallel -- avoids a
  // transient "another deployment operation is in progress on this account" conflict.
  dependsOn: [
    modelDeployment
  ]
}

output accountName string = openAiAccount.name
output endpoint string = openAiAccount.properties.endpoint
output deploymentName string = modelDeployment.name
output embeddingDeploymentName string = embeddingDeployment.name
#disable-next-line outputs-should-not-contain-secrets // consumed only by the module that writes it into Key Vault, never a deployment output surfaced to the caller
output apiKey string = openAiAccount.listKeys().key1
