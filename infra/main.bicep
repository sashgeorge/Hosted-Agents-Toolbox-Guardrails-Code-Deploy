// Control-plane infrastructure for the telco agent sample.
//
// Everything here is a real ARM resource, so it is fully declarative:
//   Foundry account and project, chat + embedding deployments,
//   the guardrail (RAI policy), the project connections the toolbox needs,
//   and the role assignment the memory store requires.
//
// Data-plane artifacts (skills, toolbox, memory store, agents) have no ARM
// type. They are created after provisioning by scripts/postprovision.ps1.
//
// Outputs are surfaced as azd environment variables, which is how
// AZURE_RAI_POLICY_ID reaches the hosted agent definition in azure.yaml.

targetScope = 'subscription'

@minLength(1)
@description('Name of the azd environment; used to derive resource names.')
param environmentName string

@minLength(1)
@description('Azure region. Must support Foundry hosted agents.')
param location string

@description('Chat model deployment name used by the agents and by memory extraction.')
param chatDeploymentName string = 'gpt-5.5-1'

@description('Embedding deployment name required by the memory store.')
param embeddingDeploymentName string = 'text-embedding-3-large'

@description('Name of the guardrail (RAI policy).')
param guardrailName string = 'telco-agent-guardrail'

@description('Remote MCP server URL, including its path (usually /mcp). Empty skips the connection.')
param mcpUrl string = ''

@description('Header name the MCP server expects the API key in.')
param mcpHeaderName string = 'x-api-key'

@secure()
@description('API key for the remote MCP server.')
param mcpApiKey string = ''

@description('Project connection name for the MCP server.')
param mcpConnectionName string = 'dynamic-wf-mcp'

@description('Project connection name the prompt agent uses to reach the toolbox.')
param toolboxConnectionName string = 'telco-toolbox-connection'

@description('Toolbox name, used to build the toolbox MCP endpoint.')
param toolboxName string = 'telco-toolbox'

var abbrev = toLower(take(replace(environmentName, '-', ''), 12))
var uniqueSuffix = take(uniqueString(subscription().id, environmentName), 6)
var accountName = '${abbrev}${uniqueSuffix}'
var projectName = '${abbrev}proj'

resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-${environmentName}'
  location: location
}

module foundry 'foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    location: location
    accountName: accountName
    projectName: projectName
    chatDeploymentName: chatDeploymentName
    embeddingDeploymentName: embeddingDeploymentName
    guardrailName: guardrailName
    mcpUrl: mcpUrl
    mcpHeaderName: mcpHeaderName
    mcpApiKey: mcpApiKey
    mcpConnectionName: mcpConnectionName
    toolboxConnectionName: toolboxConnectionName
    toolboxName: toolboxName
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location
output AZURE_AI_ACCOUNT_NAME string = accountName
output AZURE_AI_PROJECT_NAME string = projectName
output AZURE_AI_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = chatDeploymentName
output MEMORY_CHAT_MODEL string = chatDeploymentName
output MEMORY_EMBEDDING_MODEL string = embeddingDeploymentName

// Consumed by azure.yaml as ${AZURE_RAI_POLICY_ID} on the hosted agent.
output AZURE_RAI_POLICY_ID string = foundry.outputs.raiPolicyId

output TOOLBOX_NAME string = toolboxName
output TOOLBOX_CONNECTION_NAME string = toolboxConnectionName
output DYNAMIC_WF_MCP_CONNECTION_NAME string = mcpConnectionName
output GUARDRAIL_NAME string = guardrailName
