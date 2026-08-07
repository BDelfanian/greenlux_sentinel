// Writes one secret value into an existing Key Vault. Used only for the three secrets that
// originate *within* this same deployment (postgres-password, cosmos-key,
// azure-openai-api-key) -- see infra/modules/key-vault.bicep's header comment. The other two
// entries in config.py's _KEY_VAULT_SECRET_NAMES (langchain-api-key, powerbi-client-secret) come
// from external systems this Bicep doesn't provision and must be set post-deploy, e.g.:
//   az keyvault secret set --vault-name <kv-name> --name langchain-api-key --value <...>

param keyVaultName string
param secretName string

@secure()
param secretValue string

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource secret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: secretName
  properties: {
    value: secretValue
  }
}
