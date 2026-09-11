// Resource-group scoped Foundry resources.

param location string
param accountName string
param projectName string
param chatDeploymentName string
param embeddingDeploymentName string
param guardrailName string
param mcpUrl string
param mcpHeaderName string
@secure()
param mcpApiKey string
param mcpConnectionName string
param toolboxConnectionName string
param toolboxName string

var deployMcpConnection = !empty(mcpUrl) && !empty(mcpApiKey)

resource account 'Microsoft.CognitiveServices/accounts@2026-07-01' = {
  name: accountName
  location: location
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-07-01' = {
  parent: account
  name: projectName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Contoso Telco'
    description: 'Telco support agents, toolbox, guardrail, and memory.'
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: account
  name: chatDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.5'
    }
    raiPolicyName: guardrail.name
  }
}

// The memory store cannot be created without an embedding deployment.
resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2026-07-01' = {
  parent: account
  name: embeddingDeploymentName
  sku: {
    name: 'Standard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-large'
    }
  }
  dependsOn: [
    chatDeployment
  ]
}

// The guardrail. Referenced by the toolbox and by both agents via its ARM id.
// Prompt shields take no severityThreshold; the four core harms take Medium.
resource guardrail 'Microsoft.CognitiveServices/accounts/raiPolicies@2026-05-15-preview' = {
  parent: account
  name: guardrailName
  properties: {
    mode: 'Blocking'
    basePolicyName: 'Microsoft.DefaultV2'
    contentFilters: [
      { name: 'Hate', enabled: true, severityThreshold: 'Medium', blocking: true, source: 'Prompt' }
      { name: 'Sexual', enabled: true, severityThreshold: 'Medium', blocking: true, source: 'Prompt' }
      { name: 'Violence', enabled: true, severityThreshold: 'Medium', blocking: true, source: 'Prompt' }
      { name: 'Selfharm', enabled: true, severityThreshold: 'Medium', blocking: true, source: 'Prompt' }
      { name: 'Hate', enabled: true, severityThreshold: 'Medium', blocking: true, source: 'Completion' }
      { name: 'Sexual', enabled: true, severityThreshold: 'Medium', blocking: true, source: 'Completion' }
      { name: 'Violence', enabled: true, severityThreshold: 'Medium', blocking: true, source: 'Completion' }
      { name: 'Selfharm', enabled: true, severityThreshold: 'Medium', blocking: true, source: 'Completion' }
      { name: 'Jailbreak', enabled: true, blocking: true, source: 'Prompt' }
      { name: 'Indirect Attack', enabled: true, blocking: true, source: 'Prompt' }
      { name: 'Profanity', enabled: true, blocking: true, source: 'Prompt' }
    ]
  }
}

// Fronts the toolbox MCP endpoint for the prompt agent. UserEntraToken passes the
// caller's identity through. An audience is mandatory: without it the platform
// cannot mint a token and the agent fails at runtime with HTTP 400.
resource toolboxConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01' = {
  parent: project
  name: toolboxConnectionName
  properties: {
    category: 'RemoteTool'
    target: '${account.properties.endpoints['AI Foundry API']}api/projects/${projectName}/toolboxes/${toolboxName}/mcp?api-version=v1'
    authType: 'UserEntraToken'
    audience: 'https://ai.azure.com'
    isSharedToAll: false
  }
}

// Carries the API key for the remote MCP server, so no secret reaches the
// toolbox definition or the agent image.
resource mcpConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01' = if (deployMcpConnection) {
  parent: project
  name: mcpConnectionName
  properties: {
    category: 'RemoteTool'
    target: mcpUrl
    authType: 'CustomKeys'
    isSharedToAll: false
    credentials: {
      keys: {
        '${mcpHeaderName}': mcpApiKey
      }
    }
  }
}

// The memory store calls the chat and embedding deployments as the project's
// managed identity. Without this, recall fails with HTTP 401.
resource memoryModelAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, project.id, 'Cognitive Services OpenAI User')
  properties: {
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    )
  }
}

output projectEndpoint string = '${account.properties.endpoints['AI Foundry API']}api/projects/${projectName}'
output raiPolicyId string = guardrail.id
output projectPrincipalId string = project.identity.principalId
