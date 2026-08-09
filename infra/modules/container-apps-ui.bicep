// Operator UI (ui/, Next.js 16, CLAUDE.md decision #5) -- a second, independent Container App in
// the *same* Container Apps Environment as the agent API (infra/modules/container-apps.bicep),
// not a new environment. Talks to the agent API over its public FQDN (AGENT_API_URL); calls are
// authenticated server-side only (ui/src/lib/agent-api.ts, Server Actions) via AGENT_API_TOKEN,
// which is never sent to the browser.
//
// No managed-identity Key Vault integration here, unlike the agent API: this app has no Python
// config.py-style KV-reading layer, and reusing main.bicep's existing @secure() apiAuthToken
// deploy-time parameter as a native Container Apps secret (below) is simpler than adding one --
// same "@secure() param at deploy time" pattern main.bicep already uses for
// postgresAdministratorPassword/apiAuthToken itself.

param location string
param namePrefix string
param environmentName string
param containerRegistryLoginServer string
param containerRegistryName string
param containerImage string = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
param agentApiUrl string
@secure()
param agentApiToken string = ''

var containerAppName = 'ca-${namePrefix}-ui-${environmentName}'
var environmentNameResource = 'cae-${namePrefix}-${environmentName}'

// Same chicken-and-egg reasoning as container-apps.bicep's identical variable: only declare the
// ACR registry entry once containerImage actually points at it, so the first deploy (before a
// real image exists) doesn't need the AcrPull role assignment below to already exist.
var usesContainerRegistry = startsWith(containerImage, containerRegistryLoginServer)

resource managedEnvironment 'Microsoft.App/managedEnvironments@2023-05-01' existing = {
  name: environmentNameResource
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
        targetPort: 3000
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
      secrets: !empty(agentApiToken)
        ? [
            {
              name: 'agent-api-token'
              value: agentApiToken
            }
          ]
        : []
    }
    template: {
      containers: [
        {
          name: 'ui'
          image: containerImage
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: concat(
            [
              { name: 'AGENT_API_URL', value: agentApiUrl }
            ],
            !empty(agentApiToken)
              ? [
                  { name: 'AGENT_API_TOKEN', secretRef: 'agent-api-token' }
                ]
              : []
          )
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

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

output containerAppName string = containerApp.name
output containerAppFqdn string = containerApp.properties.configuration.ingress.fqdn
