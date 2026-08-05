// Placeholder — Phase 5 (docs/ROADMAP.md). Not a deployable template yet.
//
// Intended resources (docs/ARCHITECTURE.md#azure-service-map):
//   - Azure Database for PostgreSQL Flexible Server
//   - Azure Cosmos DB account (NoSQL/Core API)
//   - Storage Account (ADLS Gen2) for the raw-data landing zone
//   - Azure AI Foundry / Azure OpenAI resource
//   - Container Apps Environment + Container App (LangGraph service + MCP servers)
//   - API Management instance
//   - Key Vault
//   - Log Analytics workspace + Application Insights
//
// TODO(Phase 5): implement as modules, one per resource, parameterized by environment name.

targetScope = 'resourceGroup'

param location string = resourceGroup().location
param environmentName string = 'dev'
