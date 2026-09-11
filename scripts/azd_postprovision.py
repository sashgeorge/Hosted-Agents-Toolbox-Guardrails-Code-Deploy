"""azd postprovision hook — everything `azure.yaml` cannot declare.

`azd up` runs provision, then this hook, then deploy. Guardrails, skills,
toolboxes, MCP servers, memory stores, and prompt agents have no declarative
service type in azure.yaml, so they are created here, in dependency order:

    1. guardrail       nothing else can reference it until it exists
    2. skills+toolbox  the toolbox carries the guardrail as a policy
    3. MCP server      added to the existing toolbox (skipped if no key)
    4. memory store    the prompt agent attaches a memory tool to it
    5. prompt agent    needs the toolbox, guardrail, and memory store

azd then deploys the hosted agent, which consumes the same toolbox, guardrail,
and memory store.

The guardrail's ARM id is written back with `azd env set` so `azure.yaml` can
reference it as ${AZURE_RAI_POLICY_ID} when the hosted agent is deployed.

Not run directly — invoked by the hook in azure.yaml.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402  - needs ROOT on the path first


def run(script: str, label: str) -> None:
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    result = subprocess.run([sys.executable, script], cwd=ROOT, check=False)
    if result.returncode != 0:
        raise SystemExit(f"{script} failed with exit code {result.returncode}")


def azd_env_set(name: str, value: str) -> None:
    """Publish a value back to the azd environment for later phases to consume."""
    env_name = os.getenv("AZURE_ENV_NAME")
    if not env_name:
        # Running outside `azd up`; setting it would prompt for an environment.
        print(f"  (not in an azd environment; skipping azd env set {name})")
        return
    result = subprocess.run(
        ["azd", "env", "set", name, value, "-e", env_name, "--no-prompt"],
        cwd=ROOT, check=False, shell=sys.platform == "win32",
    )
    if result.returncode != 0:
        print(f"WARNING: could not set {name} in the azd environment")
    else:
        print(f"  azd env set {name}")


def main() -> None:
    print(f"Project: {config.PROJECT_ENDPOINT}")

    run("01_create_guardrail.py", "1/5  Guardrail")
    azd_env_set("AZURE_RAI_POLICY_ID", config.rai_policy_arm_id())

    run("02_create_toolbox.py", "2/5  Skills and toolbox")

    if config.MCP_KEY and config.MCP_URL:
        run("05_update_toolbox.py", "3/5  MCP server on the toolbox")
    else:
        print("\n3/5  MCP server — skipped (DYNAMIC_WF_MCP_KEY/URL not set)")

    if config.MEMORY_STORE_NAME:
        run("09_create_memory_store.py", "4/5  Memory store")
    else:
        print("\n4/5  Memory store — skipped (MEMORY_STORE_NAME not set)")

    run("06_deploy_prompt_agent.py", "5/5  Prompt agent")

    print(f"\n{'=' * 70}")
    print("Postprovision complete. azd now deploys the hosted agent.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
