// Azure Container Registry -- hosts the agent API image (Dockerfile) that
// container-apps.bicep's Container App pulls. Basic SKU, admin user disabled: the Container App
// pulls via its system-assigned managed identity + an AcrPull role assignment (created in
// container-apps.bicep, scoped to this registry -- see that module's header comment on why the
// role assignment lives with the identity that needs it, not here).

param location string
param namePrefix string
param environmentName string
param uniqueSuffix string

var registryName = take(toLower('${namePrefix}acr${environmentName}${uniqueSuffix}'), 50)

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  #disable-next-line BCP334 // registryName is namePrefix+'acr'+environmentName+13-char uniqueString — always well over ACR's 5-char minimum with this repo's actual params; the linter can't see that from the string params' unconstrained type alone
  name: registryName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

output registryName string = registry.name
output loginServer string = registry.properties.loginServer
