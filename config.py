"""Shared configuration for the telco hosted-agent sample.

Every value comes from the .env file next to this module.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env", override=False)

# --- Foundry project -------------------------------------------------------
PROJECT_ENDPOINT = (os.getenv("AZURE_AI_PROJECT_ENDPOINT") or "").rstrip("/")
MODEL_DEPLOYMENT_NAME = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME", "")

# --- ARM coordinates of the Foundry account --------------------------------
SUBSCRIPTION_ID = os.getenv("AZURE_SUBSCRIPTION_ID", "")
RESOURCE_GROUP = os.getenv("AZURE_RESOURCE_GROUP", "")
ACCOUNT_NAME = os.getenv("AZURE_AI_ACCOUNT_NAME", "")

# --- Sample resource names -------------------------------------------------
GUARDRAIL_NAME = os.getenv("GUARDRAIL_NAME", "telco-agent-guardrail")
TOOLBOX_NAME = os.getenv("TOOLBOX_NAME", "telco-toolbox")
AGENT_NAME = os.getenv("AGENT_NAME", "telco-support-agent")
ENABLE_EGRESS_GUARDRAIL = os.getenv("ENABLE_EGRESS_GUARDRAIL", "false").lower() == "true"

# --- Remote MCP server added to the toolbox by 05_update_toolbox.py ---------
MCP_URL = os.getenv("DYNAMIC_WF_MCP_URL", "")
MCP_HEADER = os.getenv("DYNAMIC_WF_MCP_HEADER", "x-api-key")
MCP_KEY = os.getenv("DYNAMIC_WF_MCP_KEY", "")
MCP_CONNECTION_NAME = os.getenv("DYNAMIC_WF_MCP_CONNECTION_NAME", "dynamic-wf-mcp")
MCP_SERVER_LABEL = os.getenv("DYNAMIC_WF_MCP_SERVER_LABEL", "dynamicwf")

# --- Constants -------------------------------------------------------------
API_VERSION = "v1"
FOUNDRY_SCOPE = "https://ai.azure.com/.default"
ARM_SCOPE = "https://management.azure.com/.default"
ARM_BASE = "https://management.azure.com"
# Preview api-version is required for the egressPolicy property on an RAI policy.
RAI_API_VERSION = "2026-05-15-preview"
# ARM api-version for the CognitiveServices project connection sub-resource.
CONNECTION_API_VERSION = "2025-10-01-preview"

SKILLS_DIR = ROOT / "skills"
AGENT_SRC_DIR = ROOT / "src" / "telco_support_agent"

# Last path segment of the project endpoint, e.g. .../api/projects/<project-name>.
PROJECT_NAME = PROJECT_ENDPOINT.rsplit("/", 1)[-1] if PROJECT_ENDPOINT else ""


def rai_policy_arm_id(policy_name: str = "") -> str:
    """Full ARM resource ID of the guardrail. This is what agents and toolboxes reference."""
    return (
        f"/subscriptions/{SUBSCRIPTION_ID}"
        f"/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.CognitiveServices/accounts/{ACCOUNT_NAME}"
        f"/raiPolicies/{policy_name or GUARDRAIL_NAME}"
    )


def toolbox_mcp_url() -> str:
    """Consumer endpoint of the toolbox — always serves the default version."""
    return f"{PROJECT_ENDPOINT}/toolboxes/{TOOLBOX_NAME}/mcp?api-version={API_VERSION}"


def project_arm_id() -> str:
    return (
        f"/subscriptions/{SUBSCRIPTION_ID}"
        f"/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.CognitiveServices/accounts/{ACCOUNT_NAME}"
        f"/projects/{PROJECT_NAME}"
    )


def connection_arm_id(connection_name: str) -> str:
    return f"{project_arm_id()}/connections/{connection_name}"


def require(*names: str) -> None:
    """Abort early with a readable message when a required .env value is missing."""
    missing = [n for n in names if not (globals().get(n) or "").strip() or "<" in globals()[n]]
    if missing:
        print("Missing or placeholder values in .env: " + ", ".join(missing), file=sys.stderr)
        sys.exit(1)
