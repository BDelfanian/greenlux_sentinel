# infra/

Bicep IaC for the Azure service map in [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#azure-service-map).
Phase 5 in [docs/ROADMAP.md](../docs/ROADMAP.md) — not implemented yet; `main.bicep` is a
placeholder listing the resources to provision, not a deployable template.

Intended deployment flow (once implemented): Azure Developer CLI (`azd up`) against this
directory, with secrets sourced from Key Vault rather than checked-in parameter files.
