// Azure Database for PostgreSQL Flexible Server -- Tier 1 breadth data (docs/DATA.md#two-tier-data-architecture):
// the ~67k-row Morningstar fund universe plus the audit_log table
// (src/greenlux_sentinel/db/schema.sql, audit_log_schema.sql).
//
// Burstable B1ms is a deliberate cost choice for a portfolio project's demo-scale traffic, not a
// production sizing recommendation -- bump the SKU if this is ever used under real load.

param location string
param namePrefix string
param environmentName string
param uniqueSuffix string
param logAnalyticsWorkspaceId string
param administratorLogin string = 'glxadmin'

@secure()
param administratorPassword string

param postgresVersion string = '16'
param skuName string = 'Standard_B1ms'
param skuTier string = 'Burstable'
param storageSizeGB int = 32

var serverName = 'psql-${namePrefix}-${environmentName}-${uniqueSuffix}'
var databaseName = 'greenlux'

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: serverName
  location: location
  sku: {
    name: skuName
    tier: skuTier
  }
  properties: {
    version: postgresVersion
    administratorLogin: administratorLogin
    administratorLoginPassword: administratorPassword
    storage: {
      storageSizeGB: storageSizeGB
    }
    backup: {
      backupRetentionDays: 7
      geoRedundantBackup: 'Disabled'
    }
    highAvailability: {
      mode: 'Disabled'
    }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2022-12-01' = {
  parent: postgresServer
  name: databaseName
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// Portfolio-project convenience: lets the Container App / Function App (both use dynamic
// outbound IPs unless a NAT gateway / VNet integration is added) reach the server without a
// private endpoint. Tighten this to specific egress IPs or move to VNet integration + private
// access before any real credential-bearing use.
resource allowAzureServices 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = {
  parent: postgresServer
  name: 'AllowAllAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: 'diag-${serverName}'
  scope: postgresServer
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
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

output serverName string = postgresServer.name
output fqdn string = postgresServer.properties.fullyQualifiedDomainName
output databaseName string = database.name
output administratorLogin string = administratorLogin
