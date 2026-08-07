// Cosmos DB, NoSQL/Core (SQL) API -- deliberately not Gremlin, see CLAUDE.md decision #3 and
// src/greenlux_sentinel/mcp_servers/cosmos_server.py's header comment. Tier 2 depth data
// (docs/DATA.md#two-tier-data-architecture): ETF holdings nested with company-level ESG ratings,
// one document per ETF/fund.
//
// Serverless capacity mode -- this project's read volume is low and bursty (agent-driven, not
// constant traffic), so pay-per-request beats provisioned RU/s for cost. Revisit if usage ever
// becomes sustained/high-throughput.

param location string
param namePrefix string
param environmentName string
param uniqueSuffix string
param logAnalyticsWorkspaceId string

var accountName = 'cosmos-${namePrefix}-${environmentName}-${uniqueSuffix}'
var databaseName = 'greenlux'
var containerName = 'esg_holdings'

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  name: accountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    publicNetworkAccess: 'Enabled'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-04-15' = {
  parent: cosmosAccount
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

resource container 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: containerName
  properties: {
    resource: {
      id: containerName
      partitionKey: {
        paths: [
          '/isin'
        ]
        kind: 'Hash'
      }
    }
  }
}

resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${accountName}'
  scope: cosmosAccount
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'Requests'
        enabled: true
      }
    ]
  }
}

output accountName string = cosmosAccount.name
output endpoint string = cosmosAccount.properties.documentEndpoint
output databaseName string = database.name
output containerName string = container.name
#disable-next-line outputs-should-not-contain-secrets // consumed only by the module that writes it into Key Vault, never a deployment output surfaced to the caller
output primaryKey string = cosmosAccount.listKeys().primaryMasterKey
