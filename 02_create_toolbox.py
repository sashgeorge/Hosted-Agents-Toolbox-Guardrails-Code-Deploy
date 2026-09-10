"""Step 2 — publish the telco skills, build a toolbox from them, and attach the guardrail.

A toolbox is a versioned bundle exposed to agents through a single managed MCP
endpoint. A version can contain:
  * tools    — Foundry-managed tools (code interpreter, MCP servers, search, ...)
  * skills   — procedural instructions published to the project, surfaced as MCP resources
  * policies — the guardrail (RAI policy) enforced at the toolbox layer

Because versions are immutable, this script creates a new version each run and
promotes it to `default_version` so the consumer endpoint picks it up.

Run: python 02_create_toolbox.py
"""

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    CodeInterpreterToolboxTool,
    RaiConfig,
    ToolboxPolicies,
    ToolboxSkillReference,
)
from azure.identity import DefaultAzureCredential

import config
import foundry_client as fc

# Foundry-managed tools in the toolbox. Code interpreter is connectionless, so the
# sample works without any extra project connections.
TOOLS = [
    CodeInterpreterToolboxTool(
        name="telco_calculator",
        description=(
            "Run Python to compute telco figures exactly: prorated charges, plan "
            "comparisons over 12/24 months, data-usage projections, and overage costs. "
            "Use this instead of doing arithmetic in your head."
        ),
    ),
    # Example of adding a remote MCP server to the same toolbox. It needs a project
    # connection, so it is left commented out.
    # MCPToolboxTool(
    #     server_label="crm",
    #     server_url="https://crm-mcp.contoso-telco.example.com",
    #     description="Contoso Telco CRM: accounts, tickets, entitlements.",
    #     require_approval="always",
    #     project_connection_id="telco-crm-connection",
    # ),
]


def publish_skills() -> list[str]:
    """Upload each skills/<name>/ folder as a new skill version (multipart REST API)."""
    folders = sorted(
        p for p in config.SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    )
    if not folders:
        raise SystemExit(f"No skills with a SKILL.md found under {config.SKILLS_DIR}")
    print(f"Publishing {len(folders)} skill(s) ...")
    return [fc.upload_skill(folder) for folder in folders]


def main() -> None:
    config.require("PROJECT_ENDPOINT", "SUBSCRIPTION_ID", "RESOURCE_GROUP", "ACCOUNT_NAME")

    skill_names = publish_skills()

    project = AIProjectClient(
        endpoint=config.PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )

    print(f"\nCreating a version of toolbox '{config.TOOLBOX_NAME}' ...")
    version_obj = project.toolboxes.create_version(
        name=config.TOOLBOX_NAME,
        description="Tools and skills for the Contoso Telco support agent.",
        tools=TOOLS,
        # Omit `version` on a skill reference to follow that skill's default version.
        skills=[ToolboxSkillReference(name=name) for name in skill_names],
        # The guardrail from step 1, applied at the toolbox layer. It runs
        # independently of the model-level and agent-level content filters.
        policies=ToolboxPolicies(
            rai_config=RaiConfig(rai_policy_name=config.rai_policy_arm_id())
        ),
    )
    version = str(version_obj.version)
    print(f"  version {version} created with {len(TOOLS)} tool(s) "
          f"and {len(skill_names)} skill(s)")

    toolbox = project.toolboxes.update(name=config.TOOLBOX_NAME, default_version=version)
    print(f"  default version is now {toolbox.default_version}")

    print("\nToolbox MCP endpoints:")
    print(f"  consumer (agents use this): {config.toolbox_mcp_url()}")
    print(f"  version  (test before promoting): "
          f"{config.PROJECT_ENDPOINT}/toolboxes/{config.TOOLBOX_NAME}"
          f"/versions/{version}/mcp?api-version={config.API_VERSION}")
    print(f"\nGuardrail attached: {config.rai_policy_arm_id()}")


if __name__ == "__main__":
    main()
