# Contoso Telco hosted agent — Foundry sample

An end-to-end sample that provisions, in code:

| Step | Script | What it creates |
|---|---|---|
| 1 | `01_create_guardrail.py` | A guardrail (Responsible AI policy) on the Foundry account |
| 2 | `02_create_toolbox.py` | Two telco skills, a toolbox containing tools + those skills, with the guardrail attached |
| 3 | `03_deploy_hosted_agent.py` | Uploads the agent source, waits for the version to go active, and routes the endpoint to it |
| 4 | `04_invoke_hosted_agent.py` | Smoke-tests a deployed agent |

Plus two optional programs:

| Script | What it does |
|---|---|
| `05_update_toolbox.py` | Adds an authenticated remote MCP server to the existing toolbox |
| `06_deploy_prompt_agent.py` | Deploys a **prompt agent** using the same guardrail and toolbox — no container, no code |
| `07_invoke_prompt_agent.py` | Invokes the prompt agent, with MCP approval and guardrail handling |
| `08_promote_with_eval_gate.py` | Evaluates a version before shifting any traffic to it |

There are also two files showing the **recommended** deployment path:
[azure.yaml](azure.yaml) for `azd`, and [evals/telco-eval.yaml](evals/telco-eval.yaml)
for the release gate. See [Scripts vs azd](#scripts-vs-azd).

See [TERRAFORM.md](TERRAFORM.md) for what of this can be expressed as Terraform.

The agent answers telco questions — plans and pricing, billing and overages, data
usage, outages, and connectivity troubleshooting — using **dummy data**.

## Layout

```
01_create_guardrail.py         guardrail as an ARM RAI policy
02_create_toolbox.py           publish skills + create/promote a toolbox version
03_deploy_hosted_agent.py      zip source + create_version_from_code + traffic routing
04_invoke_hosted_agent.py      invoke a deployed agent
05_update_toolbox.py           add a key-authenticated MCP server to the toolbox
06_deploy_prompt_agent.py      prompt agent over the same toolbox and guardrail
07_invoke_prompt_agent.py      invoke the prompt agent (agent_reference pattern)
08_promote_with_eval_gate.py   evaluate a version, then promote traffic
azure.yaml                     declarative azd deployment (recommended path)
evals/telco-eval.yaml          release-gate assertions
config.py                      .env loading and resource naming
foundry_client.py              REST helpers (ARM guardrail + multipart skill upload)
skills/
  telco-plan-advisor/SKILL.md  plan catalog, add-ons, discount rules
  telco-troubleshooting/SKILL.md triage table, escalation format, SLAs
src/telco_support_agent/
  main.py                      Responses-protocol agent + tool-calling loop
  toolbox_mcp.py               MCP client for the toolbox endpoint
  telco_data.py                dummy back-office data + local function tools
  requirements.txt             built remotely by Foundry at deploy time
TERRAFORM.md                   what is and isn't expressible as Terraform
```

## How to run this program

### 1. Prerequisites

- A Foundry project in a [region that supports hosted agents](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents#region-availability), with a chat model deployed.
- **Foundry Account Owner** on the Foundry account (step 1 writes an RAI policy).
- Azure CLI installed.

### 2. Set up

```powershell
cd C:\AOAI\SandBox\HostedAgent-SashkSample
.\myvenv\Scripts\Activate.ps1
pip install -r requirements.txt

az login
az account set --subscription "<subscription-id>"
```

Fill in `.env`:

| Variable | Where to find it |
|---|---|
| `AZURE_AI_PROJECT_ENDPOINT` | Foundry portal &rarr; project &rarr; **Overview** &rarr; endpoint URL |
| `AZURE_SUBSCRIPTION_ID` | `az account show --query id -o tsv` |
| `AZURE_RESOURCE_GROUP` | Resource group holding the Foundry account |
| `AZURE_AI_ACCOUNT_NAME` | The host part of the project endpoint, e.g. `contoso-foundry` in `https://contoso-foundry.services.ai.azure.com/...` |
| `AZURE_AI_MODEL_DEPLOYMENT_NAME` | `az cognitiveservices account deployment list -n <account> -g <rg> -o table` |

`GUARDRAIL_NAME`, `TOOLBOX_NAME`, and `AGENT_NAME` can stay at their defaults.

### 3. Run the four steps

```powershell
python 01_create_guardrail.py     # RAI policy on the Foundry account
python 02_create_toolbox.py       # publish skills -> toolbox version -> promote to default
python 03_deploy_hosted_agent.py  # upload source, wait for active, route traffic
python 04_invoke_hosted_agent.py  # smoke test
```

Step 3 takes a few minutes: Foundry builds the container remotely from
`src/telco_support_agent/requirements.txt`, and the script polls until the version
reports `active` before pinning endpoint traffic to it.

### 4. Grant the agent access to the toolbox

The agent gets its own Entra agent identity at deploy time. It needs the
**Azure AI User** role on the project before it can call the toolbox MCP endpoint,
so run this once, after step 3:

```powershell
$env:PROJECT = "<project endpoint>"          # AZURE_AI_PROJECT_ENDPOINT from .env
$env:ACCOUNT_SCOPE = "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices/accounts/<account>"

$agentId = az rest --method get `
  --url "$env:PROJECT/agents/telco-support-agent?api-version=v1" `
  --resource "https://ai.azure.com" --query "identity.principalId" -o tsv

az role assignment create --assignee $agentId --role "Azure AI User" --scope $env:ACCOUNT_SCOPE
```

If you skip this, the agent still answers from its local tools but every toolbox
call fails with `401`.

### 5. Talk to it

```powershell
python 04_invoke_hosted_agent.py "My number is 555-0199. Why is my phone showing SOS only?"
```

Pass several prompts to hold a multi-turn conversation — the script threads
`previous_response_id` between them:

```powershell
python 04_invoke_hosted_agent.py "I'm on 555-0142" "Am I about to go over my data?" "What would the Unlimited plan cost me instead?"
```

## Sample prompts

| Prompt | What it exercises |
|---|---|
| `My number is 555-0142. My data keeps running out - should I change plan?` | `lookup_subscriber` &rarr; `get_data_usage` &rarr; the **telco-plan-advisor** skill |
| `I'm in area code 617 and my phone shows SOS only.` | **telco-troubleshooting** skill: outage check first, so it reports INC-4488 instead of device steps |
| `Compare Plus vs Unlimited for me over 24 months if I use 45 GB a month.` | The toolbox `telco_calculator` (code interpreter) doing the arithmetic |
| `What's my bill if I use 42 GB this cycle? I'm SUB-10041.` | `estimate_bill` with overage and autopay discount |
| `My broadband in 206 is down.` | Degraded-area path plus the broadband triage rows |
| `What's a good stock to buy?` | Out-of-scope refusal and handoff |

### Sample data

| Phone | Subscriber | Plan | Area | Note |
|---|---|---|---|---|
| `555-0142` | SUB-10041 Ana Ramirez | Plus (30 GB) | 206 | Trending over her cap |
| `555-0177` | SUB-10078 Dev Patel | Essential (5 GB) | 312 | Healthy network |
| `555-0199` | SUB-10112 Contoso Bakery | Family 4-line | 617 | Past due; active outage INC-4488 |

## Iterating

Steps 2 and 3 are safe to re-run — each creates a new immutable version and
promotes it.

| You changed | Re-run |
|---|---|
| Agent code under `src/telco_support_agent/` | `python 03_deploy_hosted_agent.py` |
| A `SKILL.md`, or the toolbox tool list | `python 02_create_toolbox.py` (no redeploy; start a new session to pick it up) |
| Guardrail controls | `python 01_create_guardrail.py` (applies immediately) |
| Prompt agent instructions | `python 06_deploy_prompt_agent.py` |
## Adding a remote MCP server

`05_update_toolbox.py` adds an authenticated MCP server to the toolbox without
touching the agent. It does two things:

1. Upserts a **project connection** of category `RemoteTool` with `CustomKeys`
   auth, so the API key lives in the project rather than in the toolbox
   definition or the agent image.
2. Reads the toolbox's current default version, carries its tools and skills
   forward, appends an `mcp` tool that references the connection by name, and
   promotes the new version.

Configure it in `.env`:

```dotenv
DYNAMIC_WF_MCP_URL="https://<your-mcp-host>/mcp"
DYNAMIC_WF_MCP_HEADER="x-api-key"
DYNAMIC_WF_MCP_KEY="<secret>"
DYNAMIC_WF_MCP_CONNECTION_NAME="dynamic-wf-mcp"
DYNAMIC_WF_MCP_SERVER_LABEL="dynamicwf"
```

> **Use the full MCP path, not just the host.** Most servers answer on `/mcp`.
> Pointing at the bare host makes Foundry POST to `/`, which typically returns
> `405` and surfaces as `Initialization timed out` when the agent enumerates tools.
> Confirm with a direct `initialize` POST before registering the URL.

Then:

```powershell
python 05_update_toolbox.py
```

Its tools arrive namespaced as `dynamicwf.<tool_name>`. The agent reads the
toolbox's default version at session start, so no redeploy is needed — just start
a new conversation.

The script sets `require_approval="never"` because this sample has no approval UI.
If the server can perform writes, set it to `"always"` and have the calling
runtime confirm each call before invoking it.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Missing or placeholder values in .env` | A `<placeholder>` is still in `.env` | Fill in the value named in the message |
| Step 1 returns `403` | Not Foundry Account Owner | Get the role, or ask an owner to run step 1 |
| Step 3 status goes to `failed` | Remote build failed | Check `src/telco_support_agent/requirements.txt` pins install on Python 3.13 |
| `session_not_ready` retries then fails | Container crashes at startup | Run locally first (see below) to see the traceback |
| Agent answers but never cites plan prices | Toolbox call failing | Confirm the role assignment in step 4 |
| `tools/list` returns no MCP tools | Connection credentials wrong, or server unreachable | Check the connection target and key; call the MCP server directly to test |
| `Failed to fetch agentic identity access token` (400) | The connection has no `audience` | Set `audience` on the connection — `https://ai.azure.com` for a toolbox |
| `Initialization timed out` for one tool source | MCP `server_url` missing its path | Use the full path (usually `/mcp`), not the bare host |
| `content_filter` 400 on a benign prompt | Guardrail too strict | Loosen `severityThreshold` in `01_create_guardrail.py` and re-run |

## Run the agent locally

Fastest way to debug before deploying:

```powershell
cd src\telco_support_agent
pip install -r requirements.txt
$env:FOUNDRY_PROJECT_ENDPOINT="<project endpoint>"
$env:AZURE_AI_MODEL_DEPLOYMENT_NAME="<model deployment>"
$env:TOOLBOX_NAME="telco-toolbox"
python main.py   # listens on http://localhost:8088
```

Then from another shell:

```powershell
curl -X POST http://localhost:8088/responses -H "Content-Type: application/json" `
  -d '{"input": "My number is 555-0142. Should I change plan?", "stream": false}'
```

Your own `az login` identity is used locally, so it needs **Azure AI User** on the
project too.

## Prompt agent (the no-code alternative)

`06_deploy_prompt_agent.py` deploys the same telco assistant as a **prompt
agent** — defined entirely by model, instructions, and tools, with no container
and no code. It reuses steps 1 and 2 unchanged:

```powershell
python 06_deploy_prompt_agent.py
python 07_invoke_prompt_agent.py "Which plan suits 45 GB a month?"
```

It wires the toolbox in through a project connection with `UserEntraToken` auth
and audience `https://ai.azure.com`, so the caller's identity is passed through to
the toolbox and no secret is stored on the connection.

> **The `audience` is mandatory.** Every identity-based connection auth type needs
> one. Without it the agent fails at runtime with
> `Failed to fetch agentic identity access token with status code: 400`.

The two agents are invoked differently, which is why there are two invoke scripts:

| | Hosted agent | Prompt agent |
|---|---|---|
| Has its own endpoint | Yes | No — lives in the project |
| Client | `get_openai_client(agent_name=...)` | `get_openai_client()` |
| Identifies the agent | The bound endpoint | `extra_body={"agent_reference": ...}` per request |
| Script | `04_invoke_hosted_agent.py` | `07_invoke_prompt_agent.py` |

| | Hosted agent (step 3) | Prompt agent (step 6) |
|---|---|---|
| Definition | Container built from your source | Model + instructions + tools |
| Deploy time | Minutes (remote build) | Seconds |
| Toolbox access | MCP client in your code | `mcp` tool on the definition |
| Local functions in `telco_data.py` | Yes | **No** |
| Orchestration | Full control of the loop | Platform-managed |
| Guardrail | `rai_config` | `rai_config` (same policy) |

The key difference is the missing row: a prompt agent has no container, so none of
the dummy back-office functions (`lookup_subscriber`, `estimate_bill`,
`check_network_outage`) exist. It answers from the toolbox only — the skills and
their bundled reference data, the code interpreter, and any MCP server added by
`05_update_toolbox.py`. Its instructions tell it to say so and offer a handoff when
a question needs a live account record. To give a prompt agent that data, expose it
as an MCP server and add it to the toolbox.

Both agents need the **Azure AI User** role on the project to call the toolbox.

## Scripts vs azd

The numbered scripts exist to make each API call visible. They are a good way to
learn the surface, but they are not how you should deploy for real: no
environments, secrets in `.env`, RBAC applied by hand, and traffic shifted with no
check. [azure.yaml](azure.yaml) shows the recommended path.

| | Numbered scripts | `azd` |
|---|---|---|
| Style | Imperative, step by step | Declarative, one definition |
| Environments | One `.env` | `azd env new dev` / `prod` |
| Re-run with no changes | Creates a new version anyway | Idempotent |
| Model + agent + guardrail | Three scripts | One file |
| Teardown | Manual | `azd down` |

```powershell
azd auth login
azd env new dev
azd env set AZURE_AI_MODEL_DEPLOYMENT_NAME gpt-5.4-mini
azd env set AZURE_RAI_POLICY_ID "<guardrail ARM id from step 1>"
azd env set TOOLBOX_NAME telco-toolbox
azd up
```

`azure.yaml` covers the model deployment, the hosted agent, the guardrail
(`policies:` maps to `rai_config`), and the container size. Skills, the toolbox,
the MCP server, and the prompt agent stay scripted — those are data-plane
artifacts with their own promotion semantics. For the same split applied to
Terraform, see [TERRAFORM.md](TERRAFORM.md).

## The release gate

Steps 3 and 6 create a version and immediately route **100%** of traffic to it.
That is versioning without release management. `08_promote_with_eval_gate.py`
fixes it:

1. Find the newest version of the agent.
2. Invoke **that version only**, by pinning `agent_reference.version` — no traffic
   moves, so nothing is exposed to real callers.
3. Score the responses against [evals/telco-eval.yaml](evals/telco-eval.yaml).
4. Promote traffic only if the pass rate clears the threshold.

```powershell
python 08_promote_with_eval_gate.py                       # hosted agent, newest version
python 08_promote_with_eval_gate.py --agent telco-prompt-agent
python 08_promote_with_eval_gate.py --canary 20           # promote to 20% instead of 100%
python 08_promote_with_eval_gate.py --dry-run             # evaluate, never promote
```

It exits non-zero when the gate fails, so it drops straight into a pipeline.

Cases use deterministic assertions — `must_contain`, `must_not_contain`,
`must_call_tool`, `expect_blocked` — because a release gate should be cheap and
unambiguous. For model-graded scoring, run a Foundry evaluation suite instead.

A real run against the prompt agent:

```text
  [PASS] outage-before-troubleshooting
  [FAIL] plan-catalog-grounded - missing '40'
  [PASS] no-invented-pricing
  [PASS] calculator-used-for-arithmetic
  [PASS] out-of-scope-declined

4/5 passed (80%)
Below the 100% threshold. Traffic unchanged.
```

That failure is genuine: the prompt agent answered a pricing question without
grounding it in the plan catalog skill. Exactly what a gate is for.

## How the pieces connect

**Guardrail.** A guardrail is an ARM resource
(`Microsoft.CognitiveServices/accounts/{account}/raiPolicies/{name}`). Step 1
creates it with blocking content filters on prompts and completions plus prompt
shields, and optionally preview network-egress rules (set
`ENABLE_EGRESS_GUARDRAIL=true`). Everything downstream references its full ARM
resource ID — never the bare policy name.

**Toolbox.** Step 2 first publishes each folder under `skills/` as a skill
version, then creates a toolbox version containing tools (`code_interpreter`, with
a commented-out MCP example), `skill_reference` entries for the skills, and
`policies.rai_config.rai_policy_name` pointing at the guardrail. Versions are
immutable, so the script promotes the new version to `default_version`.

**Hosted agent.** `src/telco_support_agent/main.py` serves the Responses protocol.
On the first request it connects to the toolbox MCP endpoint, merges toolbox tools
with the local telco functions, and reads the skills (exposed as MCP resources) into
its system prompt as playbooks. Step 3 zips the folder, uploads it with
`create_version_from_code` so Foundry builds the container remotely from
`requirements.txt`, attaches the same guardrail on `rai_config`, waits for the
version to become `active`, and pins 100% of endpoint traffic to it. Filtering
therefore applies at both the toolbox layer and the agent layer.

## References

- [Hosted agents in Foundry Agent Service](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agents)
- [Create and manage a toolbox](https://learn.microsoft.com/azure/foundry/agents/how-to/tools/toolbox)
- [Add guardrails to a hosted agent](https://learn.microsoft.com/azure/foundry/agents/how-to/add-hosted-agent-guardrails)
- [foundry-samples/samples/python/hosted-agents](https://github.com/microsoft-foundry/foundry-samples/tree/main/samples/python/hosted-agents)
