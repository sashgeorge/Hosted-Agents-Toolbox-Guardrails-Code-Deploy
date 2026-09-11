"""Deploy a prompt agent that uses the same toolbox and guardrail.

A prompt agent is defined entirely by configuration — model, instructions, and
tools — with no container and no code. It is the counterpart to the hosted agent
in 03_deploy_hosted_agent.py, and it reuses the artifacts from steps 1 and 2:

  * the guardrail, attached with `rai_config`
  * the toolbox, reached through an `mcp` tool

A prompt agent authenticates to the toolbox through a project connection using
`UserEntraToken`: the caller's identity is passed through to the toolbox, so no
key or secret is stored on the connection. The connection must declare an
`audience` — identity-based auth without one fails at runtime with HTTP 400.

Because there is no container, this agent has none of the local telco functions
from telco_data.py. Everything it can do comes from the toolbox: the skills and
their bundled reference data, the code interpreter, and any MCP servers added
by 05_update_toolbox.py.

Run: python 06_deploy_prompt_agent.py
"""

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    FixedRatioVersionSelectionRule,
    MCPTool,
    MemorySearchPreviewTool,
    PromptAgentDefinition,
    RaiConfig,
    VersionSelector,
)
from azure.identity import DefaultAzureCredential

import config
import foundry_client as fc

INSTRUCTIONS = """You are Max, a customer support agent for Contoso Telco.

You handle mobile and broadband questions: plans and pricing, billing and overages,
network outages, SIM/eSIM activation, and connectivity troubleshooting.

Rules:
- Ground every answer in your attached playbooks and tools. Never invent a price,
  allowance, outage, or account detail.
- Follow the playbook that matches the request before answering.
- Use the calculator tool for any arithmetic the customer will rely on.
- You have no access to live account records. If a question needs one, say so and
  offer to hand off to a human agent.
- Politely decline anything outside Contoso Telco support.
- Never ask for a password, full payment card number, SIM PIN, or PUK.
- If you recall something about this customer from an earlier conversation, use it
  as context and confirm it rather than stating it as fact.
- Keep replies short and concrete: the answer first, then at most three next steps."""

# The sample has no approval UI, so toolbox tool calls are not gated.
REQUIRE_APPROVAL = "never"


def upsert_toolbox_connection() -> str:
    """Create or update the RemoteTool connection that fronts the toolbox MCP endpoint.

    `UserEntraToken` passes the caller's identity through to the toolbox, which is the
    documented pattern for a prompt agent calling a toolbox in the same project.

    `audience` is required for every identity-based auth type. Without it the platform
    cannot mint a token and the agent fails at runtime with:
        Failed to fetch agentic identity access token with status code: 400
    """
    connection_id = config.connection_arm_id(config.TOOLBOX_CONNECTION_NAME)
    body = {
        "properties": {
            "category": "RemoteTool",
            "target": config.toolbox_mcp_url(),
            "authType": config.TOOLBOX_CONNECTION_AUTH,
            "audience": config.TOOLBOX_AUDIENCE,
            "isSharedToAll": False,
        }
    }
    result = fc.arm("PUT", connection_id, config.CONNECTION_API_VERSION, body)
    props = result.get("properties", {})
    print(f"  connection '{config.TOOLBOX_CONNECTION_NAME}' -> {config.toolbox_mcp_url()}")
    print(f"  auth: {props.get('authType')}, audience: {props.get('audience')}")
    if not props.get("audience"):
        print("  WARNING: audience came back empty; toolbox calls will fail with 400")
    return connection_id


def build_tools() -> list:
    tools = [
        MCPTool(
            server_label=config.TOOLBOX_SERVER_LABEL,
            server_url=config.toolbox_mcp_url(),
            require_approval=REQUIRE_APPROVAL,
            project_connection_id=config.TOOLBOX_CONNECTION_NAME,
        )
    ]
    # The declarative counterpart to memory.py in the hosted agent: the platform
    # handles recall, so there is no retrieval code in a prompt agent.
    # {{$userId}} scopes memories to the signed-in caller, which is safer than
    # deriving a scope from anything in the transcript.
    # Do not add search_options here: create accepts it, the runtime rejects it.
    if config.MEMORY_STORE_NAME:
        tools.append(
            MemorySearchPreviewTool(
                memory_store_name=config.MEMORY_STORE_NAME,
                scope="{{$userId}}",
            )
        )
    return tools


def main() -> None:
    config.require(
        "PROJECT_ENDPOINT", "MODEL_DEPLOYMENT_NAME",
        "SUBSCRIPTION_ID", "RESOURCE_GROUP", "ACCOUNT_NAME",
    )

    print(f"Wiring the toolbox connection on project '{config.PROJECT_NAME}' ...")
    upsert_toolbox_connection()

    project = AIProjectClient(
        endpoint=config.PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )

    tools = build_tools()
    definition = PromptAgentDefinition(
        model=config.MODEL_DEPLOYMENT_NAME,
        instructions=INSTRUCTIONS,
        tools=tools,
        # The guardrail from step 1 — the same policy the hosted agent uses.
        rai_config=RaiConfig(rai_policy_name=config.rai_policy_arm_id()),
    )

    print(f"\nCreating a version of prompt agent '{config.PROMPT_AGENT_NAME}' ...")
    created = project.agents.create_version(
        agent_name=config.PROMPT_AGENT_NAME,
        description="Contoso Telco support agent, prompt-based, backed by the telco toolbox.",
        definition=definition,
    )
    version = str(created.version)
    print(f"  version {version} created")

    # A new version does not take traffic until the endpoint is pointed at it.
    project.agents.update_details(
        agent_name=config.PROMPT_AGENT_NAME,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[
                    FixedRatioVersionSelectionRule(
                        agent_version=version, traffic_percentage=100
                    )
                ]
            )
        ),
    )
    print(f"  endpoint now serving version {version}")

    print(f"\nGuardrail attached: {config.rai_policy_arm_id()}")
    print(f"Toolbox: {config.toolbox_mcp_url()}")
    print(f"Tools: {len(tools)} "
          f"({'with' if config.MEMORY_STORE_NAME else 'without'} long-term memory)")
    print("\nTry it with:")
    print("  python 07_invoke_prompt_agent.py")


if __name__ == "__main__":
    main()
