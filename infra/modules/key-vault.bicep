// Key Vault -- RBAC-authorized (not the legacy access-policy model), consistent with
// config.py's DefaultAzureCredential + SecretClient path (src/greenlux_sentinel/config.py).
// Only the fields listed in config.py's _KEY_VAULT_SECRET_NAMES are ever read from here at
// runtime; everything else (hosts, endpoints, IDs) is a plain, non-secret Container App /
// Function App environment variable. This is what makes "no local .env in any deployed path"
// true -- see docs/ROADMAP.md Phase 5.

param location string
param namePrefix string
param environmentName string
param uniqueSuffix string
param logAnalyticsWorkspaceId string

// Principal that gets Key Vault Secrets Officer (can write secret values post-deploy, e.g. the
// LangSmith API key and Power BI client secret -- see infra/README.md, both of which originate
// outside this deployment so Bicep cannot populate them itself).
param adminPrincipalId string = ''

var keyVaultName = take('kv-${namePrefix}-${environmentName}-${uniqueSuffix}', 24)

var secretsOfficerRoleId = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

resource adminSecretsOfficer 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(adminPrincipalId)) {
  name: guid(keyVault.id, adminPrincipalId, secretsOfficerRoleId)
  scope: keyVault
  properties: {
    principalId: adminPrincipalId
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsOfficerRoleId)
    principalType: 'User'
  }
}

resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${keyVaultName}'
  scope: keyVault
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        categoryGroup: 'audit'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
output keyVaultId string = keyVault.id
