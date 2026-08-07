// API Management, Consumption tier -- fronts the agent API (docs/ARCHITECTURE.md#azure-service-map).
// Consumption (sku "Consumption", capacity 0) is pay-per-call with near-zero idle cost, matching
// this project's demo-scale traffic; no VNet/availability-zone features needed here.
//
// The API is imported directly from the live Container App's FastAPI-generated OpenAPI document
// (api/app.py serves /openapi.json for free) rather than hand-written -- one real source of
// truth for the route surface instead of two definitions to keep in sync. subscriptionRequired
// is false: this project's auth model is the agent API's own shared bearer token (api/app.py's
// require_auth), not APIM subscription keys -- APIM is a pass-through gateway here, not a second
// auth layer. Import happens at *deploy* time against whatever the Container App is serving then,
// so a stale/unreachable Container App at deploy time means a stale/empty API definition here --
// acceptable for this project's scale, called out in infra/README.md.

param location string
param namePrefix string
param environmentName string
param uniqueSuffix string
param publisherEmail string
param publisherName string = 'GreenLux Sentinel'
param containerAppFqdn string

var apimServiceName = take('apim-${namePrefix}-${environmentName}-${uniqueSuffix}', 50)

resource apimService 'Microsoft.ApiManagement/service@2022-08-01' = {
  name: apimServiceName
  location: location
  sku: {
    name: 'Consumption'
    capacity: 0
  }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2022-08-01' = {
  parent: apimService
  name: 'agent-api'
  properties: {
    displayName: 'GreenLux Sentinel Agent API'
    path: 'agents'
    protocols: [
      'https'
    ]
    serviceUrl: 'https://${containerAppFqdn}'
    format: 'openapi-link'
    value: 'https://${containerAppFqdn}/openapi.json'
    subscriptionRequired: false
  }
}

output apimServiceName string = apimService.name
output gatewayUrl string = apimService.properties.gatewayUrl
output apiPath string = api.properties.path
