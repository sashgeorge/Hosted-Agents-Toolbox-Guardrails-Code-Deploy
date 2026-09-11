"""Gate traffic promotion on an evaluation run.

Steps 03 and 06 create an agent version and immediately route 100% of traffic to
it. That is versioning without release management: a bad version reaches every
caller before anyone looks at it.

This script closes that gap:

  1. Find the newest version of an agent.
  2. Invoke that version directly, without shifting any traffic, by pinning
     `agent_reference.version` on each request.
  3. Score the responses against evals/telco-eval.yaml.
  4. Promote traffic only if the pass rate clears the threshold.

Run:
  python 08_promote_with_eval_gate.py                      # hosted agent
  python 08_promote_with_eval_gate.py --agent telco-prompt-agent
  python 08_promote_with_eval_gate.py --version 3          # gate a specific version
  python 08_promote_with_eval_gate.py --canary 20          # promote to 20% instead of 100%
  python 08_promote_with_eval_gate.py --dry-run            # evaluate, never promote
"""

import sys
from pathlib import Path

import yaml
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    FixedRatioVersionSelectionRule,
    VersionSelector,
)
from azure.identity import DefaultAzureCredential
from openai import APIStatusError

import config

EVAL_FILE = Path(__file__).parent / "evals" / "telco-eval.yaml"


def parse_args() -> dict:
    args = sys.argv[1:]
    opts = {
        "agent": config.AGENT_NAME,
        "version": None,
        "canary": 100,
        "dry_run": "--dry-run" in args,
    }
    for flag, key, cast in (("--agent", "agent", str),
                            ("--version", "version", str),
                            ("--canary", "canary", int)):
        if flag in args:
            i = args.index(flag)
            if i + 1 >= len(args):
                raise SystemExit(f"{flag} needs a value")
            opts[key] = cast(args[i + 1])
    return opts


def latest_version(project: AIProjectClient, agent_name: str) -> str:
    versions = list(project.agents.list_versions(agent_name=agent_name))
    if not versions:
        raise SystemExit(f"Agent '{agent_name}' has no versions.")
    # Versions are numeric strings; sort numerically so 10 beats 9.
    newest = max(versions, key=lambda v: int(str(v.version)))
    return str(newest.version)


def run_case(openai, agent_name: str, version: str, case: dict) -> tuple[bool, str]:
    reference = {
        "agent_reference": {
            "name": agent_name,
            "version": version,
            "type": "agent_reference",
        }
    }
    try:
        response = openai.responses.create(input=case["prompt"], extra_body=reference)
    except APIStatusError as error:
        body = error.body if isinstance(error.body, dict) else {}
        if body.get("code") == "content_filter":
            return bool(case.get("expect_blocked")), "blocked by guardrail"
        raise

    if case.get("expect_blocked"):
        return False, "expected the guardrail to block this prompt, but it answered"

    text = (response.output_text or "").lower()
    called = {
        getattr(item, "name", "") or ""
        for item in response.output
        if getattr(item, "type", None) in ("mcp_call", "function_call")
    }

    for needle in case.get("must_contain", []):
        if needle.lower() not in text:
            return False, f"missing {needle!r}"
    for needle in case.get("must_not_contain", []):
        if needle.lower() in text:
            return False, f"contains forbidden {needle!r}"
    tool = case.get("must_call_tool")
    if tool and not any(tool in name for name in called):
        return False, f"did not call a tool matching {tool!r} (called: {sorted(called) or 'none'})"

    return True, "ok"


def promote(project: AIProjectClient, agent_name: str, version: str, percent: int) -> None:
    project.agents.update_details(
        agent_name=agent_name,
        agent_endpoint=AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[
                    FixedRatioVersionSelectionRule(
                        agent_version=version, traffic_percentage=percent
                    )
                ]
            )
        ),
    )


def main() -> None:
    config.require("PROJECT_ENDPOINT")
    opts = parse_args()

    suite = yaml.safe_load(EVAL_FILE.read_text(encoding="utf-8"))
    cases = suite["cases"]
    threshold = float(suite.get("pass_threshold", 1.0))

    project = AIProjectClient(
        endpoint=config.PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )
    openai = project.get_openai_client()

    agent_name = opts["agent"]
    version = opts["version"] or latest_version(project, agent_name)
    print(f"Agent:   {agent_name}")
    print(f"Version: {version} (not yet taking traffic)")
    print(f"Suite:   {len(cases)} case(s), threshold {threshold:.0%}\n")

    passed = 0
    for case in cases:
        ok, detail = run_case(openai, agent_name, version, case)
        passed += ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {case['name']}"
              f"{'' if ok else f' - {detail}'}")

    rate = passed / len(cases)
    print(f"\n{passed}/{len(cases)} passed ({rate:.0%})")

    if rate < threshold:
        print(f"Below the {threshold:.0%} threshold. Traffic unchanged.")
        raise SystemExit(1)

    if opts["dry_run"]:
        print("Gate passed. --dry-run set, so traffic is unchanged.")
        return

    promote(project, agent_name, version, opts["canary"])
    print(f"Gate passed. Version {version} now serving {opts['canary']}% of traffic.")


if __name__ == "__main__":
    main()
