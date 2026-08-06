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

    azure_key_vault_url: str = ""

    @property
    def postgres_dsn(self) -> str:
        return (
            f"host={self.postgres_host} port={self.postgres_port} "
            f"dbname={self.postgres_db} user={self.postgres_user} "
            f"password={self.postgres_password}"
        )


def _apply_key_vault_overrides(settings: Settings) -> Settings:
    """Overlay Key Vault secret values onto settings resolved from the environment."""
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    credential = DefaultAzureCredential()
    client = SecretClient(vault_url=settings.azure_key_vault_url, credential=credential)

    overrides = {
        field: client.get_secret(secret_name).value
        for field, secret_name in _KEY_VAULT_SECRET_NAMES.items()
    }
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
