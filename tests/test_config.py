"""Unit tests for config.py -- the Key Vault overlay (a missing secret should be skipped, not
fatal), and env-var-name/field-name round trips for the plain (non-Key-Vault) settings that
infra/*.bicep sets directly as Container App/Function App app settings.

Real bugs found live in Phase 5, both worth guarding against here:
- infra/main.bicep deliberately doesn't populate langchain-api-key/powerbi-client-secret (see
  infra/README.md), so a freshly deployed environment is expected to be missing those two until
  someone sets them by hand -- the original _apply_key_vault_overrides() let any single
  ResourceNotFoundError kill settings resolution entirely, which would have taken down every
  agent endpoint except /healthz.
- config.py's field was named `landing_storage_account` while every Bicep module and
  .env.example used the env var name `LANDING_STORAGE_ACCOUNT_NAME` -- pydantic-settings maps a
  field to its exact uppercased name by default, so the mismatch meant the env var was silently
  never read (settings.landing_storage_account_name stayed empty in a live Function App run even
  though `az functionapp config appsettings list` showed the value was set). A mock-based test
  can't catch this class of bug -- only a real Settings() + real env var round trip can, hence
  TestEnvVarFieldNamesMatch below, not just the patched-collaborator style used elsewhere.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from azure.core.exceptions import ResourceNotFoundError

from greenlux_sentinel.config import Settings, _apply_key_vault_overrides


def _fake_secret(value: str) -> MagicMock:
    secret = MagicMock()
    secret.value = value
    return secret


class TestApplyKeyVaultOverrides:
    def test_missing_secret_is_skipped_not_fatal(self):
        settings = Settings(_env_file=None, azure_key_vault_url="https://kv-test.vault.azure.net/")

        def fake_get_secret(name: str):
            if name in ("langchain-api-key", "powerbi-client-secret"):
                raise ResourceNotFoundError(f"secret {name} not found")
            return _fake_secret(f"value-for-{name}")

        mock_client = MagicMock()
        mock_client.get_secret.side_effect = fake_get_secret

        with (
            patch("azure.keyvault.secrets.SecretClient", return_value=mock_client),
            patch("azure.identity.DefaultAzureCredential", return_value=MagicMock()),
        ):
            result = _apply_key_vault_overrides(settings)

        assert result.postgres_password == "value-for-postgres-password"
        assert result.cosmos_key == "value-for-cosmos-key"
        assert result.azure_openai_api_key == "value-for-azure-openai-api-key"
        assert result.api_auth_token == "value-for-api-auth-token"
        # Missing secrets fall back to the field's untouched default, not an error.
        assert result.langchain_api_key == ""
        assert result.powerbi_client_secret == ""

    def test_all_secrets_present_populates_everything(self):
        settings = Settings(_env_file=None, azure_key_vault_url="https://kv-test.vault.azure.net/")
        mock_client = MagicMock()
        mock_client.get_secret.side_effect = lambda name: _fake_secret(f"value-for-{name}")

        with (
            patch("azure.keyvault.secrets.SecretClient", return_value=mock_client),
            patch("azure.identity.DefaultAzureCredential", return_value=MagicMock()),
        ):
            result = _apply_key_vault_overrides(settings)

        assert result.langchain_api_key == "value-for-langchain-api-key"
        assert result.powerbi_client_secret == "value-for-powerbi-client-secret"


class TestEnvVarFieldNamesMatch:
    """Real env-var round trips (no mocking of Settings itself) for the plain app settings
    infra/*.bicep sets directly -- catches field/env-var name drift a mocked test can't."""

    def test_landing_storage_account_name(self, monkeypatch):
        monkeypatch.setenv("LANDING_STORAGE_ACCOUNT_NAME", "greenluxlanddevidckowude")
        settings = Settings(_env_file=None)
        assert settings.landing_storage_account_name == "greenluxlanddevidckowude"

    def test_postgres_host(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "psql-greenlux-dev.postgres.database.azure.com")
        settings = Settings(_env_file=None)
        assert settings.postgres_host == "psql-greenlux-dev.postgres.database.azure.com"

    def test_cosmos_endpoint(self, monkeypatch):
        monkeypatch.setenv("COSMOS_ENDPOINT", "https://cosmos-greenlux-dev.documents.azure.com:443/")
        settings = Settings(_env_file=None)
        assert settings.cosmos_endpoint == "https://cosmos-greenlux-dev.documents.azure.com:443/"
