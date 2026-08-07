// Log Analytics workspace + workspace-based Application Insights.
// Feeds Azure Monitor/Log Analytics "alongside the Postgres audit log" (docs/ROADMAP.md Phase 5,
// docs/ARCHITECTURE.md#azure-service-map) -- infra/app-level logging lives here; agent-level
// business events (who/what tool/what input/output) stay in the Postgres audit_log table and
// LangSmith, cross-referenced by trace ID per docs/RESPONSIBLE_AI.md. This workspace is also the
// log sink every other module's diagnosticSettings resource points at.

param location string
param namePrefix string
param environmentName string
param logRetentionDays int = 30

var workspaceName = 'log-${namePrefix}-${environmentName}'
var appInsightsName = 'appi-${namePrefix}-${environmentName}'

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: workspaceName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: logRetentionDays
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspace.id
    IngestionMode: 'LogAnalytics'
  }
}

output logAnalyticsWorkspaceId string = logAnalyticsWorkspace.id
output logAnalyticsCustomerId string = logAnalyticsWorkspace.properties.customerId
#disable-next-line outputs-should-not-contain-secrets // consumed only by the container-apps module to wire the managed environment's log destination, never surfaced to the deployment caller
output logAnalyticsSharedKey string = logAnalyticsWorkspace.listKeys().primarySharedKey
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output appInsightsInstrumentationKey string = appInsights.properties.InstrumentationKey
