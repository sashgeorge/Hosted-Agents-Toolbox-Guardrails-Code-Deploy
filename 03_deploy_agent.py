"""Step 3 — deploy the agent source to Foundry as a hosted agent.

Follows the code-upload path: zip the agent folder, let Foundry build the
container remotely from `requirements.txt`, then wait for the version to go
`active` and pin the agent endpoint to it. No ACR and no local Docker involved.

The guardrail from step 1 is attached with `rai_config`, and the toolbox from
step 2 is wired in through environment variables.

Each run creates a new immutable version and routes 100% of endpoint traffic to it.

Run: python 03_deploy_agent.py
"""

import tempfile
import time
import zipfile
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    CodeConfiguration,
    CodeDependencyResolution,
    FixedRatioVersionSelectionRule,
    HostedAgentDefinition,
    ProtocolConfiguration,
    ProtocolVersionRecord,
    RaiConfig,
    ResponsesProtocolConfiguration,
    VersionSelector,
)
from azure.identity import DefaultAzureCredential

import config

EXCLUDED = {".git", ".venv", "myvenv", "__pycache__", ".env", ".dockerignore"}
POLL_ATTEMPTS = 60
POLL_SECONDS = 10


def create_code_zip(source_dir: Path) -> Path:
    if not source_dir.is_dir():
        raise SystemExit(f"Agent source folder not found: {source_dir}")

    zip_path = Path(tempfile.gettempdir()) / f"{config.AGENT_NAME}.zip"
    count = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_dir.rglob("*"):
            if not path.is_file() or any(part in EXCLUDED for part in path.parts):
                continue
            archive.write(path, path.relative_to(source_dir))
            count += 1

    if count == 0:
        raise SystemExit(f"No files to upload under {source_dir}")
    print(f"Packaged {count} file(s) from {source_dir}")
    return zip_path


def wait_for_active(project: AIProjectClient, version: str) -> None:
    for attempt in range(1, POLL_ATTEMPTS + 1):
        time.sleep(POLL_SECONDS)
        details = project.agents.get_version(
            agent_name=config.AGENT_NAME, agent_version=version
        )
        status = details["status"]
        print(f"  provisioning: {status} ({attempt}/{POLL_ATTEMPTS})")
        if status == "active":
            return
        if status == "failed":
            raise SystemExit(f"Provisioning failed: {dict(details)}")
    raise SystemExit("Timed out waiting for the agent version to become active.")


def route_traffic(project: AIProjectClient, version: str) -> None:
    """Pin the agent endpoint to this version. New versions do not take traffic on their own."""
    project.agents.update_details(
        agent_name=config.AGENT_NAME,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[
                    FixedRatioVersionSelectionRule(
                        agent_version=version, traffic_percentage=100
                    )
                ]
            ),
            protocol_configuration=ProtocolConfiguration(
                responses=ResponsesProtocolConfiguration()
            ),
        ),
    )
    print(f"  endpoint now serving version {version}")


def main() -> None:
    config.require(
        "PROJECT_ENDPOINT", "MODEL_DEPLOYMENT_NAME",
        "SUBSCRIPTION_ID", "RESOURCE_GROUP", "ACCOUNT_NAME",
    )

    code_zip = create_code_zip(config.AGENT_SRC_DIR)

    definition = HostedAgentDefinition(
        cpu="1",
        memory="2Gi",
        code_configuration=CodeConfiguration(
            runtime="python_3_13",
            entry_point=["python", "main.py"],
            dependency_resolution=CodeDependencyResolution.REMOTE_BUILD,
        ),
        protocol_versions=[
            ProtocolVersionRecord(protocol="responses", version="2.0.0")
        ],
        environment_variables={
            "FOUNDRY_PROJECT_ENDPOINT": config.PROJECT_ENDPOINT,
            "AZURE_AI_MODEL_DEPLOYMENT_NAME": config.MODEL_DEPLOYMENT_NAME,
            "TOOLBOX_NAME": config.TOOLBOX_NAME,
        },
        # The guardrail created in step 1. Omit rai_config to deploy without one.
        rai_config=RaiConfig(rai_policy_name=config.rai_policy_arm_id()),
    )

    with (
        code_zip.open("rb") as code_stream,
        DefaultAzureCredential() as credential,
        AIProjectClient(
            endpoint=config.PROJECT_ENDPOINT, credential=credential, allow_preview=True
        ) as project,
    ):
        print(f"Creating a version of agent '{config.AGENT_NAME}' ...")
        created = project.agents.create_version_from_code(
            agent_name=config.AGENT_NAME,
            description="Contoso Telco support agent (toolbox + guardrail).",
            definition=definition,
            code=code_stream,
        )
        print(f"  version {created.version} created")

        wait_for_active(project, created.version)
        route_traffic(project, created.version)

    print("\nResponses endpoint:")
    print(f"  {config.PROJECT_ENDPOINT}/agents/{config.AGENT_NAME}"
          f"/endpoint/protocols/openai/responses?api-version={config.API_VERSION}")
    print("\nThe agent has its own Entra agent identity. Grant it the 'Azure AI User'")
    print("role on this project so it can call the toolbox MCP endpoint at runtime.")


if __name__ == "__main__":
    main()
