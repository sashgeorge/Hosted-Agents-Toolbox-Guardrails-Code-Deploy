# Deploying this sample with Terraform

Whether this sample can be expressed as Terraform depends on which **plane** a
resource lives on:

- **Control plane** (Azure Resource Manager) — the Foundry account, project, model
  deployment, guardrail, connections, and role assignments. These are ARM
  resources with first-class AzureRM provider support.
- **Data plane** (`{project_endpoint}/...`) — skills, toolboxes, and agent
  versions. These have **no ARM resource type at all**, so neither `azurerm` nor
  `azapi` can manage them.

The practical answer: use Terraform for the control plane, keep the Python
scripts (or `azd`) for the data plane.

> This repo ships a working Bicep implementation of exactly that split. See
> [IAC.md](IAC.md) — the constraints documented there (preflight ordering,
> CognitiveServices concurrency, quota SKUs, connection `audience`) apply equally
> to a Terraform implementation.

## Coverage map

| Sample artifact | Script | Terraform |
|---|---|---|
| Foundry account | — | `azurerm_cognitive_account` |
| Foundry project | — | `azurerm_cognitive_account_project` |
| Model deployment | — | `azurerm_cognitive_deployment` |
| Guardrail (RAI policy) | `01_create_guardrail.py` | `azurerm_cognitive_account_rai_policy` |
| MCP server credential | `05_update_toolbox.py` | `azurerm_cognitive_account_connection_custom_keys` |
| Toolbox connection (agent identity) | `06_deploy_prompt_agent.py` | `azurerm_cognitive_account_connection_entra_id` |
| Agent RBAC | manual `az role assignment` | `azurerm_role_assignment` |
| Skills | `02_create_toolbox.py` | **No resource** — data plane |
| Toolbox versions | `02` / `05` | **No resource** — data plane |
| Hosted agent version | `03_deploy_hosted_agent.py` | **No resource** — data plane |
| Prompt agent version | `06_deploy_prompt_agent.py` | **No resource** — data plane |

Provider versions: `azurerm` 4.x. The Cognitive Services resources above use the
`Microsoft.CognitiveServices` API provider at `2026-03-01`.

## Control plane in Terraform

### Account and project

The new Foundry project requires an `AIServices` account with project management
turned on, a custom subdomain, and a managed identity:

```hcl
resource "azurerm_cognitive_account" "foundry" {
  name                       = var.account_name
  location                   = azurerm_resource_group.this.location
  resource_group_name        = azurerm_resource_group.this.name
  kind                       = "AIServices"
  sku_name                   = "S0"
  project_management_enabled = true
  custom_subdomain_name      = var.account_name

  identity { type = "SystemAssigned" }
}

resource "azurerm_cognitive_account_project" "proj" {
  name                 = var.project_name
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  location             = azurerm_resource_group.this.location
  display_name         = "Contoso Telco"

  identity { type = "SystemAssigned" }
}
```

Do **not** use `azurerm_ai_foundry` / `azurerm_ai_foundry_project`. Those manage
hub-based (classic) Foundry on `Microsoft.MachineLearningServices` and are not
compatible with the hosted-agent and toolbox features this sample uses.

### Model deployment

```hcl
resource "azurerm_cognitive_deployment" "chat" {
  name                 = var.model_deployment_name
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "GlobalStandard"
    capacity = 10
  }
}
```

### Guardrail

`01_create_guardrail.py` maps almost line-for-line onto
`azurerm_cognitive_account_rai_policy`. The Python dicts become `content_filter`
blocks:

```hcl
locals {
  core_categories = ["Hate", "Sexual", "Violence", "Selfharm"]
  sources         = ["Prompt", "Completion"]

  core_filters = [
    for pair in setproduct(local.sources, local.core_categories) : {
      source   = pair[0]
      category = pair[1]
    }
  ]
}

resource "azurerm_cognitive_account_rai_policy" "telco" {
  name                 = var.guardrail_name
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  base_policy_name     = "Microsoft.DefaultV2"
  mode                 = "Blocking"

  dynamic "content_filter" {
    for_each = local.core_filters
    content {
      name               = content_filter.value.category
      filter_enabled     = true
      block_enabled      = true
      severity_threshold = "Medium"
      source             = content_filter.value.source
    }
  }

  # Prompt shields take no severity threshold.
  dynamic "content_filter" {
    for_each = ["Jailbreak", "Indirect Attack", "Profanity"]
    content {
      name           = content_filter.value
      filter_enabled = true
      block_enabled  = true
      source         = "Prompt"
    }
  }
}
```

The provider documents the same constraint the script comments note:
`severity_threshold` does not apply to `Jailbreak`, `Indirect Attack`,
`Protected Material Text`, or `Protected Material Code`.

Its ARM ID is what the toolbox and both agents reference:

```hcl
output "guardrail_id" {
  value = azurerm_cognitive_account_rai_policy.telco.id
}
```

### Connections

The key-authenticated MCP connection from `05_update_toolbox.py`:

```hcl
resource "azurerm_cognitive_account_connection_custom_keys" "mcp" {
  name                 = var.mcp_connection_name
  cognitive_account_id = azurerm_cognitive_account.foundry.id
  category             = "RemoteTool"
  target               = var.mcp_url

  custom_keys = {
    "x-api-key" = var.mcp_api_key
  }
}
```

Note two differences from the script:

1. **Scope.** This resource is *account*-scoped. `05_update_toolbox.py` creates a
   *project*-scoped connection (`.../projects/{p}/connections/{n}`). Projects
   inherit account connections, so a toolbox reference by name still resolves,
   but they are not the same resource. For a project-scoped connection you need
   `azapi_resource`.
2. **Secrets in state.** `custom_keys` values are written to Terraform state in
   plaintext. Use an encrypted remote backend, and source the value from Key
   Vault rather than a `.tfvars` file.

### Role assignments

The toolbox call at runtime needs the agent identity to hold **Azure AI User** on
the project. The catch is that the agent identity does not exist until the agent
version is created on the data plane, so this cannot be in the same apply as the
account:

```hcl
resource "azurerm_role_assignment" "agent_toolbox" {
  scope                = azurerm_cognitive_account.foundry.id
  role_definition_name = "Azure AI User"
  principal_id         = var.agent_principal_id # from the data-plane step
}
```

## What Terraform cannot do

Skills, toolbox versions, and agent versions are created against the project
data-plane endpoint:

```text
POST {project_endpoint}/skills/{name}/versions
POST {project_endpoint}/toolboxes/{name}/versions
POST {project_endpoint}/agents/{name}/versions
```

There is no corresponding `Microsoft.CognitiveServices/.../toolboxes` or
`.../agents` ARM type, so `azapi_resource` does not help either — `azapi` is a
generic ARM client, not a generic HTTP client.

The only Terraform-shaped option is to shell out:

```hcl
resource "terraform_data" "toolbox" {
  triggers_replace = [
    filesha256("${path.module}/../../skills/telco-plan-advisor/SKILL.md"),
    filesha256("${path.module}/../../skills/telco-troubleshooting/SKILL.md"),
    filesha256("${path.module}/../../02_create_toolbox.py"),
  ]

  provisioner "local-exec" {
    working_dir = "${path.module}/../.."
    command     = "python 02_create_toolbox.py"
  }
}
```

Understand what this does and does not give you:

- It gives you ordering and re-run-on-change.
- It does **not** give you a plan-time diff, drift detection, or destroy
  semantics. Terraform knows only that a command ran, not what it produced.

This is orchestration, not infrastructure as code. It is reasonable glue for CI,
but do not mistake it for managed state.

## Why the split is the right shape

Toolbox and agent versions are **immutable, promotable artifacts**. You create a
version, test it, then point `default_version` or an endpoint traffic rule at it.
That is a release model, not a converge-to-desired-state model, and it fights
Terraform's core abstraction. It is the same reason `azd ai agent` exists
alongside Bicep and Terraform rather than inside them.

A workable pipeline:

```text
terraform apply          # account, project, model, guardrail, connections
python 02_create_toolbox.py       # skills + toolbox version
python 03_deploy_hosted_agent.py  # hosted agent version
python 06_deploy_prompt_agent.py  # prompt agent version
terraform apply -var agent_principal_id=...   # RBAC, second phase
```

## Gaps to plan around

| Gap | Impact | Workaround |
|---|---|---|
| No `egressPolicy` in the RAI policy schema | `ENABLE_EGRESS_GUARDRAIL=true` is unsupported | `azapi_resource` at `2026-05-15-preview`, or keep `01_create_guardrail.py` |
| Secrets in state | MCP API key stored plaintext | Encrypted remote backend + Key Vault data source |
| Project-scoped connections | Only account scope in `azurerm` | `azapi_resource` |
| Agent principal ID unknown at plan time | RBAC cannot be in the first apply | Two-phase apply, or `local-exec` after deploy |
| Data-plane drift invisible | A toolbox changed in the portal is not detected | Treat scripts as the source of truth; re-run in CI |

## References

- [azurerm_cognitive_account_rai_policy](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/cognitive_account_rai_policy)
- [azurerm_cognitive_account_project](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/cognitive_account_project)
- [azurerm_cognitive_account_connection_custom_keys](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/cognitive_account_connection_custom_keys)
- [Create and manage a toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox)
- [Add guardrails to a hosted agent](https://learn.microsoft.com/azure/foundry/agents/how-to/add-hosted-agent-guardrails)
