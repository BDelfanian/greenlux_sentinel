// Azure AI Search -- document-evidence retrieval index for the Phase 8a/8b evidence agent
// (docs/ARCHITECTURE.md#azure-service-map, docs/PROGRESS_LOG.md's Phase 8a entry). Authored as
// part of Phase 8a but NOT deployed yet -- see infra/README.md's "Phase 8 -- not provisioned"
// note, same treatment Power BI already got before it was live-verified.
//
// Free (F0) SKU: the document corpus this indexes is deliberately small (~11 issuer-verified
// fund disclosures + general SFDR/CSSF regulatory PDFs, docs/DATA.md#document-corpus), well
// within F0's 50MB/3-index cap. Revisit only if the corpus genuinely grows past that.
//
// Key-based auth (not AAD-only) for parity with this repo's existing per-resource secret
// pattern (cosmos-key, azure-openai-api-key) -- see config.py's _KEY_VAULT_SECRET_NAMES.

param location string
param namePrefix string
param environmentName string
param uniqueSuffix string
param skuName string = 'free'

var searchServiceName = 'srch-${namePrefix}-${environmentName}-${uniqueSuffix}'

resource searchService 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: searchServiceName
  location: location
  sku: {
    name: skuName
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    publicNetworkAccess: 'enabled'
    disableLocalAuth: false
  }
}

output searchServiceName string = searchService.name
output endpoint string = 'https://${searchService.name}.search.windows.net'
#disable-next-line outputs-should-not-contain-secrets // consumed only by the module that writes it into Key Vault, never a deployment output surfaced to the caller
output adminKey string = searchService.listAdminKeys().primaryKey
#disable-next-line outputs-should-not-contain-secrets // consumed only by the module that writes it into Key Vault, never a deployment output surfaced to the caller
output queryKey string = searchService.listQueryKeys().value[0].key
