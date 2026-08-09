"""Central config loader — reads from environment (.env in dev, Key Vault in prod).

When AZURE_KEY_VAULT_URL is set (production deploys — see
docs/ARCHITECTURE.md#azure-service-map), secret-shaped fields are resolved from Key Vault
instead of the environment, using DefaultAzureCredential so it works unchanged under a
Container Apps managed identity. Local dev leaves AZURE_KEY_VAULT_URL blank and uses the
plain env vars / .env file.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Field names that come from Key Vault (as secret names, hyphenated) rather than plain
# env vars when AZURE_KEY_VAULT_URL is set.
_KEY_VAULT_SECRET_NAMES: dict[str, str] = {
    "postgres_password": "postgres-password",
    "cosmos_key": "cosmos-key",
    "azure_openai_api_key": "azure-openai-api-key",
    "langchain_api_key": "langchain-api-key",
    "powerbi_client_secret": "powerbi-client-secret",
    "api_auth_token": "api-auth-token",
    "azure_search_admin_key": "azure-search-admin-key",
    "azure_search_query_key": "azure-search-query-key",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_db: str = "greenlux"
    postgres_user: str = ""
    postgres_password: str = ""

    cosmos_endpoint: str = ""
    cosmos_key: str = ""
    cosmos_database: str = "greenlux"
    cosmos_container: str = "esg_holdings"

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = ""
    azure_openai_api_version: str = "2024-10-21"
    # Phase 8a: embedding model for the document-evidence search index -- a second deployment on
    # the same Azure OpenAI account (infra/modules/openai.bicep), not a separate resource.
    azure_openai_embedding_deployment: str = ""

    # Phase 8a: document-evidence retrieval index (mcp_servers/search_server.py). Two keys,
    # least-privilege -- admin is only used by the offline ingestion path, query is what the
    # running agent API uses at request time. Not yet live -- see infra/README.md's Phase 8 note.
    azure_search_endpoint: str = ""
    azure_search_admin_key: str = ""
    azure_search_query_key: str = ""
    azure_search_index_name: str = "greenlux-docs"

    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "greenlux-sentinel"
    # This project's LangSmith workspace is EU-hosted -- the SDK defaults to the US endpoint,
    # which 403s for an EU API key. Must be set explicitly.
    langchain_endpoint: str = "https://eu.api.smith.langchain.com"

    powerbi_tenant_id: str = ""
    powerbi_client_id: str = ""
    powerbi_client_secret: str = ""
    powerbi_workspace_id: str = ""
    powerbi_dataset_id: str = ""

    gleif_api_base_url: str = "https://api.gleif.org/api/v1"

    # ADLS Gen2 landing-zone storage account name (not a connection string/key -- access is via
    # DefaultAzureCredential + the caller's own "Storage Blob Data Reader" role, same
    # managed-identity pattern as Key Vault). Used by etl_agent.py to fetch the raw Kaggle CSVs
    # when running somewhere that doesn't have data/raw/ locally (a deployed Function App or
    # Container App) -- see infra/modules/storage.bicep, infra/modules/functions.bicep.
    landing_storage_account_name: str = ""

    # Bearer token the agent API (api/app.py) checks incoming requests against. Empty (the local
    # dev default) means auth is skipped -- see api/app.py's module docstring for why that's an
    # explicit, documented simplification and not an oversight.
    api_auth_token: str = ""

    azure_key_vault_url: str = ""

    @property
    def postgres_dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user} "
            f"password={self.postgres_password}"
        )


def _apply_key_vault_overrides(settings: Settings) -> Settings:
    """Overlay Key Vault secret values onto settings resolved from the environment.

    Missing secrets are skipped, not fatal: infra/main.bicep deliberately doesn't populate
    langchain-api-key/powerbi-client-secret (they come from systems it doesn't provision --
    LangSmith SaaS, a separate-tenant Power BI app registration -- see infra/README.md), so a
    freshly deployed environment is expected to be missing those two until someone sets them by
    hand. Failing settings resolution entirely over an optional, not-yet-configured integration
    would take down every endpoint that touches get_settings(), not just the ones that need it.
    """
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=settings.azure_key_vault_url, credential=credential)

    overrides = {}
    for field, secret_name in _KEY_VAULT_SECRET_NAMES.items():
        try:
            overrides[field] = client.get_secret(secret_name).value
        except ResourceNotFoundError:
            continue
    return settings.model_copy(update=overrides)


def _propagate_langsmith_env(settings: Settings) -> None:
    """LangChain/LangGraph's tracing instrumentation reads LANGCHAIN_* from os.environ directly
    at call time — it does not know about our pydantic Settings object. Push them through once
    so any agent that just calls an LLM gets tracing "for free" without importing langsmith."""
    if not settings.langchain_tracing_v2:
        return
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
    os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    if settings.azure_key_vault_url:
        settings = _apply_key_vault_overrides(settings)
    _propagate_langsmith_env(settings)
    return settings
