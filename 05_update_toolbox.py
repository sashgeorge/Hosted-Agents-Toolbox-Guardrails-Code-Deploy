"""Update the existing toolbox: add a remote MCP server to it.

Adding an authenticated MCP server takes two resources:
  1. a project connection (ARM) that holds the API key, so the secret lives in
     the project rather than in the toolbox definition, and
  2. a new toolbox version whose `mcp` tool references that connection by name.

Toolbox versions are immutable, so this reads the current default version,
carries its tools and skills forward, appends the MCP tool, and promotes the
result. Re-running is safe: the connection is upserted and the MCP tool replaces
any earlier entry with the same server label.

Run: python 05_update_toolbox.py
"""

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPToolboxTool
from azure.identity import DefaultAzureCredential

import config
import foundry_client as fc

MCP_DESCRIPTION = (
    "Dynamic workflow MCP server. Use it to discover and run Contoso Telco "
    "back-office workflows such as provisioning, order status, and ticket updates."
)

# The sample agent has no approval UI, so tool calls are not gated. Switch to
# "always" once the caller can prompt the user before a workflow runs.
REQUIRE_APPROVAL = "never"


def upsert_connection() -> str:
    """Create or update the RemoteTool connection that carries the API key header."""
    connection_id = config.connection_arm_id(config.MCP_CONNECTION_NAME)
    body = {
        "properties": {
            "category": "RemoteTool",
            "target": config.MCP_URL,
            "authType": "CustomKeys",
            "isSharedToAll": False,
            "credentials": {"keys": {config.MCP_HEADER: config.MCP_KEY}},
        }
    }
    fc.arm("PUT", connection_id, config.CONNECTION_API_VERSION, body)
    print(f"  connection '{config.MCP_CONNECTION_NAME}' -> {config.MCP_URL}")
    print(f"  auth: CustomKeys, header '{config.MCP_HEADER}'")
    return connection_id


def current_default_version(project: AIProjectClient):
    """Return the toolbox's default version object, or None if the toolbox is new."""
    toolbox = project.toolboxes.get(name=config.TOOLBOX_NAME)
    if not toolbox.default_version:
        return None
    return project.toolboxes.get_version(
        name=config.TOOLBOX_NAME, version=toolbox.default_version
    )


def main() -> None:
    config.require(
        "PROJECT_ENDPOINT", "SUBSCRIPTION_ID", "RESOURCE_GROUP", "ACCOUNT_NAME",
        "MCP_URL", "MCP_KEY",
    )

    print(f"Registering the MCP credential on project '{config.PROJECT_NAME}' ...")
    upsert_connection()

    project = AIProjectClient(
        endpoint=config.PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )

    existing = current_default_version(project)
    if existing is None:
        raise SystemExit(
            f"Toolbox '{config.TOOLBOX_NAME}' has no default version. "
            "Run 02_create_toolbox.py first."
        )
    print(f"\nCarrying forward version {existing.version}: "
          f"{len(existing.tools or [])} tool(s), {len(existing.skills or [])} skill(s)")

    mcp_tool = MCPToolboxTool(
        server_label=config.MCP_SERVER_LABEL,
        server_url=config.MCP_URL,
        description=MCP_DESCRIPTION,
        require_approval=REQUIRE_APPROVAL,
        project_connection_id=config.MCP_CONNECTION_NAME,
    )

    kept = [t for t in (existing.tools or [])
            if t.get("server_label") != config.MCP_SERVER_LABEL]
    tools = kept + [mcp_tool]

    print(f"Creating a new version of toolbox '{config.TOOLBOX_NAME}' ...")
    created = project.toolboxes.create_version(
        name=config.TOOLBOX_NAME,
        description=existing.description or "Contoso Telco support toolbox.",
        tools=tools,
        skills=list(existing.skills or []),
        policies=existing.policies,
    )
    version = str(created.version)
    print(f"  version {version} created with {len(tools)} tool(s)")

    toolbox = project.toolboxes.update(name=config.TOOLBOX_NAME, default_version=version)
    print(f"  default version is now {toolbox.default_version}")

    print("\nVerify the new tools with:")
    print(f"  {config.PROJECT_ENDPOINT}/toolboxes/{config.TOOLBOX_NAME}"
          f"/versions/{version}/mcp?api-version={config.API_VERSION}")
    print(f"Tools from this server are namespaced '{config.MCP_SERVER_LABEL}.<tool_name>'.")
    print("\nThe agent picks the new version up on its next session; no redeploy needed.")


if __name__ == "__main__":
    main()
