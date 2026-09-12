# Infrastructure as code

How this sample is deployed declaratively, what each file does, and every
constraint found by actually running it against Azure.

`azd up` provisions the platform and all data-plane artifacts **without running
any Python**. The hosted agent is deployed separately.

## Contents

- [What runs where](#what-runs-where)
- [Files](#files)
- [Commands](#commands)
- [Resource naming](#resource-naming)
- [Why the split](#why-the-split)
- [Constraints found by running it](#constraints-found-by-running-it)
- [Verification](#verification)
- [What is still manual](#what-is-still-manual)
- [Teardown](#teardown)

## What runs where

| Phase | Creates | Mechanism |
|---|---|---|
| provision | resource group, Foundry account, project, chat + embedding deployments, **guardrail**, toolbox connection, MCP connection, RBAC | Bicep |
| postprovision | skills → toolbox → memory store → prompt agent | `azd ai` CLI + `az rest` |
| *(separate)* | hosted agent | `python 03_deploy_hosted_agent.py` |

Order matters and is enforced: the guardrail must exist before the toolbox
references it, the toolbox before the prompt agent, and the memory store before
the prompt agent's memory tool.

## Files

```
azure.yaml                     azd manifest: infra provider + postprovision hook
infra/
  main.bicep                   subscription scope: resource group + naming + outputs
  foundry.bicep                resource group scope: all Foundry resources
  main.parameters.json         binds azd env vars to Bicep parameters
iac/
  toolbox.yaml                 tools + skills + MCP connection + guardrail policy
  memory-store.json            memory store definition
  prompt-agent.json            prompt agent: toolbox MCP tool + memory tool + guardrail
scripts/
  postprovision.ps1            renders the templates and applies them
```

### azure.yaml

Deliberately has **no `services:` block**. It carries only `infra` and the
`postprovision` hook, so `azd up` stops after the data plane.

### infra/main.bicep

Subscription-scoped. Creates the resource group, derives resource names, and
exports outputs. Outputs become azd environment variables automatically, which is
how `AZURE_RAI_POLICY_ID` and `AZURE_AI_PROJECT_ENDPOINT` reach the hook without
any write-back step.

### infra/foundry.bicep

Every ARM resource:

| Resource | Type |
|---|---|
| Foundry account | `Microsoft.CognitiveServices/accounts` |
| Project | `.../accounts/projects` |
| Chat + embedding deployments | `.../accounts/deployments` |
| **Guardrail** | `.../accounts/raiPolicies` |
| Toolbox connection | `.../accounts/projects/connections` |
| MCP connection | `.../accounts/projects/connections` |
| Memory model access | `Microsoft.Authorization/roleAssignments` |

### iac/ templates

Placeholders of the form `@@NAME@@` are replaced by `postprovision.ps1` from
environment variables. Do not write that pattern in comments — the renderer scans
the whole file, including comments, and will fail on a placeholder it cannot
resolve.

## Commands

```powershell
azd auth login --tenant-id <tenant of your subscription>
azd env new telco-dev
azd env set AZURE_SUBSCRIPTION_ID <subscription id>
azd env set AZURE_LOCATION westus3

# Optional: include the remote MCP server in the toolbox
azd env set DYNAMIC_WF_MCP_URL https://<host>/mcp
azd env set DYNAMIC_WF_MCP_KEY <secret>

azd provision --preview     # check first
azd up                      # provision + postprovision

python 03_deploy_hosted_agent.py   # hosted agent, separately
```

Tunables, all optional:

| Variable | Default |
|---|---|
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | `gpt-5.5-1` |
| `CHAT_MODEL_NAME` | `gpt-5.5` |
| `CHAT_SKU_NAME` | `DataZoneStandard` |
| `CHAT_CAPACITY` | `10` |
| `MEMORY_EMBEDDING_MODEL` | `text-embedding-3-large` |
| `EMBEDDING_SKU_NAME` | `GlobalStandard` |
| `GUARDRAIL_NAME` | `telco-agent-guardrail` |
| `TOOLBOX_NAME` | `telco-toolbox` |
| `MEMORY_STORE_NAME` | `telco-memory` |

## Resource naming

Everything keys off the azd environment name:

```bicep
var abbrev = toLower(take(replace(environmentName, '-', ''), 12))
var uniqueSuffix = take(uniqueString(subscription().id, environmentName), 6)
var accountName = '${abbrev}${uniqueSuffix}'
var projectName = '${abbrev}proj'
resource rg ... name: 'rg-${environmentName}'
```

`azd env new telco-dev` produces `rg-telco-dev`, account `telcodev<hash>`,
project `telcodevproj`. The hash exists because the account name becomes a global
DNS subdomain. Choose the environment name deliberately — it is the only knob.

## Why the split

Resources divide by **plane**, and the boundary is not negotiable:

- **Control plane (ARM).** The account, project, deployments, guardrail,
  connections, and role assignments are real ARM resources, so Bicep or Terraform
  can manage them with full state and drift detection.
- **Data plane.** Skills, toolboxes, memory stores, and agents are created
  against `{project_endpoint}/...` and have **no ARM resource type**. Neither
  Bicep nor `azapi` can reach them — `azapi` is a generic ARM client, not a
  generic HTTP client.

Within the data plane, the CLI covers most of it:

| Artifact | Mechanism |
|---|---|
| Skills | `azd ai skill create` / `update` |
| Toolbox | `azd ai toolbox create --from-file` |
| Memory store | `az rest` — no `azd ai memory` command group exists |
| Prompt agent | `az rest` |

For the same analysis applied to Terraform, see [TERRAFORM.md](TERRAFORM.md).

## Constraints found by running it

Each of these caused a real failure.

### Bicep

**Do not set `raiPolicyName` on a model deployment.** ARM preflight validates the
deployment before the guardrail exists in the same template:

```
InvalidResourceProperties: The specified RaiPolicyName 'telco-agent-guardrail'
is not found, please update it to a valid value.
```

The guardrail belongs on the agents via `rai_config`, not on the deployment.

**Serialize child resources.** A CognitiveServices account accepts one child
operation at a time. Bicep deploys children in parallel by default, which fails:

```
RequestConflict: Another operation is being performed on the parent resource
```

`foundry.bicep` chains them explicitly:

```
account → project → chat deployment → embedding deployment
        → guardrail → toolbox connection → MCP connection
```

**Check quota before choosing a SKU.** `GlobalStandard` fills up first:

```powershell
az cognitiveservices usage list -l westus3 -o table
```

Defaults target SKUs with headroom: `DataZoneStandard` for chat,
`GlobalStandard` for embeddings. Model, SKU, and capacity are all parameters.

**`azd provision --preview` output is not exhaustive.** It omits `raiPolicies`
and `roleAssignments` even when they are in the compiled template. Verify against
the template or the API, not the preview summary.

### Connections

**`audience` is mandatory** on identity-based connection auth. Without it the
platform cannot mint a token and the agent fails at runtime with:

```
Failed to fetch agentic identity access token with status code: 400
```

Use `UserEntraToken` with `audience: https://ai.azure.com` for a toolbox
connection.

**MCP `target` must be the full path**, not the host. Most servers answer on
`/mcp`; pointing at the bare host makes Foundry POST to `/`, which returns `405`
and surfaces as `Initialization timed out` when the agent enumerates tools.

### Identity

**`azd` and `az` hold separate tokens.** If `azd` lands in your home tenant while
the resources live in another, every `azd ai` call fails while `az rest` calls
succeed:

```
403 ... does not have permissions for
Microsoft.CognitiveServices/accounts/AIServices/agents/write
```

The object id in that error will not match `az ad signed-in-user show`. Fix with
`azd auth login --tenant-id <tenant>`.

**`azd ai skill create --force` deletes first**, which needs `agents/delete`. The
hook checks for existence and picks `create` or `update` instead, so it works
with create-only permissions.

### az rest on Windows

**Only `--body "@file.json"` is reliable.** Inline JSON has its quotes stripped by
PowerShell and fails with misleading parse errors:

```
'n' is an invalid start of a property name. Expected a '"'
```

Multi-line JSON passed as a variable fails differently:

```
Expected depth to be zero at the end of the JSON payload
```

`@file` also silently falls back to a literal string if the file does not exist,
producing `'@' is an invalid start of a value`.

**Preview features need a header.** The memory store requires:

```
Foundry-Features: MemoryStores=V1Preview
```

Without it: `preview_feature_required`. The hook sends
`Skills=V1Preview, Toolboxes=V1Preview, MemoryStores=V1Preview` on every
data-plane call.

### Prompt agent

**`memory_search_preview` requires `scope`.** Use `{{$userId}}` to scope memories
to the signed-in caller — safer than deriving a scope from anything in the
transcript.

**Do not set `search_options`.** Agent creation accepts it; the runtime rejects
it on every request:

```
Unknown parameter: 'tools[1].search_options'
```

## Verification

The `azd` output does not show everything. Check directly:

```powershell
# Guardrail
az rest --method get --url "https://management.azure.com/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>/raiPolicies?api-version=2026-05-15-preview" --query "value[].name" -o tsv

# Connections
az rest --method get --url "https://management.azure.com/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>/projects/<project>/connections?api-version=2026-05-01" --query "value[].{name:name, auth:properties.authType, audience:properties.audience}" -o table

# Toolbox, skills, memory store, agents
azd ai toolbox list
azd ai skill list
az rest --method get --resource https://ai.azure.com --url "<project-endpoint>/memory_stores?api-version=v1" --headers "Foundry-Features=MemoryStores=V1Preview" --query "data[].name" -o tsv

# Smoke test the prompt agent
python 07_invoke_prompt_agent.py "Which plan suits 45 GB a month?"
```

## What is still manual

**The hosted agent's role assignment.** Its Entra agent identity does not exist
until deploy time, so Bicep cannot reference it. After
`python 03_deploy_hosted_agent.py`, grant that identity **Azure AI User** on the
account or every toolbox call returns `401`.

This is the one genuine chicken-and-egg in the design. Options are a second
`azd provision` pass after the agent exists, or a post-deploy role assignment in
CI.

**`.env` is independent of azd.** The numbered Python scripts read `.env`, not the
azd environment. After `azd up` creates a new project, update
`AZURE_AI_PROJECT_ENDPOINT`, `AZURE_RESOURCE_GROUP`, and `AZURE_AI_ACCOUNT_NAME`
or the scripts will target the old one:

```powershell
azd env get-values
```

## Teardown

```powershell
azd down
```

Removes the resource group and everything in it. Data-plane artifacts live inside
the project, so they go with it — no separate cleanup.

Foundry accounts soft-delete. To reuse the same name immediately:

```powershell
az cognitiveservices account purge -n <account> -g <rg> -l <location>
```
