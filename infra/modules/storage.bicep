// ADLS Gen2 landing zone for raw Kaggle files pre-ETL (docs/ARCHITECTURE.md#azure-service-map),
// plus a separate, non-HNS storage account for Azure Functions' own runtime state (AzureWebJobsStorage
// requires a "plain" blob/queue/table account, not hierarchical-namespace-enabled).

param location string
param namePrefix string
param environmentName string
param uniqueSuffix string

var landingStorageAccountName = take(toLower('${namePrefix}land${environmentName}${uniqueSuffix}'), 24)
var functionsStorageAccountName = take(toLower('${namePrefix}func${environmentName}${uniqueSuffix}'), 24)

resource landingStorage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: landingStorageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    isHnsEnabled: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
  }
}

resource landingContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  name: '${landingStorage.name}/default/landing'
  properties: {
    publicAccess: 'None'
  }
}

resource functionsStorage 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: functionsStorageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
  }
}

output landingStorageAccountName string = landingStorage.name
output landingStorageAccountId string = landingStorage.id
output functionsStorageAccountName string = functionsStorage.name
#disable-next-line outputs-should-not-contain-secrets // consumed only by the functions module to set AzureWebJobsStorage, never surfaced to the deployment caller
output functionsStorageConnectionString string = 'DefaultEndpointsProtocol=https;AccountName=${functionsStorage.name};AccountKey=${functionsStorage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'
