"""Central config loader — reads from environment (.env in dev, Key Vault in prod).

TODO(Phase 1): implement using pydantic-settings, with an AZURE_KEY_VAULT_URL branch
that overrides local env vars when present (see docs/ARCHITECTURE.md#azure-service-map).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    postgres_host: str = os.getenv("POSTGRES_HOST", "")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_db: str = os.getenv("POSTGRES_DB", "greenlux")
    postgres_user: str = os.getenv("POSTGRES_USER", "")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "")

    cosmos_endpoint: str = os.getenv("COSMOS_ENDPOINT", "")
    cosmos_key: str = os.getenv("COSMOS_KEY", "")
    cosmos_database: str = os.getenv("COSMOS_DATABASE", "greenlux")
    cosmos_container: str = os.getenv("COSMOS_CONTAINER", "esg_holdings")

    azure_openai_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_openai_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_openai_deployment: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")

    gleif_api_base_url: str = os.getenv("GLEIF_API_BASE_URL", "https://api.gleif.org/api/v1")


def get_settings() -> Settings:
    return Settings()
