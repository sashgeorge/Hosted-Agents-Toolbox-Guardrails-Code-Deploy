"""Smoke-test a deployed agent, and check that the guardrail blocks.

Uses the project's OpenAI-compatible client bound to the agent, and threads
`previous_response_id` so follow-up turns keep context.

Run: python 04_invoke_hosted_agent.py [--agent <name>] ["question"] ["another question"]

Defaults to the hosted agent. Pass `--agent telco-prompt-agent` to target the
prompt agent from 06_deploy_prompt_agent.py.
"""

import sys
import time

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai import APIStatusError

import config

DEFAULT_PROMPTS = [
    "My number is 555-0142. My data keeps running out - should I change plan?",
    "I'm in area code 617 and my phone shows SOS only. What's going on?",
]

READY_ATTEMPTS = 6
READY_SECONDS = 10


def create_with_retry(client, **kwargs):
    """A cold sandbox returns 424 session_not_ready until the container is up."""
    for attempt in range(1, READY_ATTEMPTS + 1):
        try:
            return client.responses.create(**kwargs)
        except APIStatusError as error:
            body = error.body if isinstance(error.body, dict) else {}
            if error.status_code != 424 or body.get("code") != "session_not_ready":
                raise
            if attempt == READY_ATTEMPTS:
                raise
            print(f"  session still starting, retrying ({attempt}/{READY_ATTEMPTS - 1}) ...")
            time.sleep(READY_SECONDS)


def parse_args() -> tuple[str, list[str]]:
    args = sys.argv[1:]
    agent = config.AGENT_NAME
    if "--agent" in args:
        i = args.index("--agent")
        if i + 1 >= len(args):
            raise SystemExit("--agent needs an agent name")
        agent = args[i + 1]
        args = args[:i] + args[i + 2:]
    return agent, args or DEFAULT_PROMPTS


def main() -> None:
    config.require("PROJECT_ENDPOINT")
    agent_name, prompts = parse_args()
    print(f"Agent: {agent_name}")

    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(
            endpoint=config.PROJECT_ENDPOINT, credential=credential, allow_preview=True
        ) as project,
        project.get_openai_client(agent_name=agent_name) as client,
    ):
        previous_response_id = None
        for prompt in prompts:
            print(f"\n> {prompt}")
            kwargs = {"input": prompt}
            if previous_response_id:
                kwargs["previous_response_id"] = previous_response_id

            try:
                response = create_with_retry(client, **kwargs)
            except APIStatusError as error:
                body = error.body if isinstance(error.body, dict) else {}
                if body.get("code") == "content_filter":
                    print("  BLOCKED by the guardrail at the input stage.")
                    print(f"  {body.get('message', error)}")
                    continue
                raise

            print(f"  {response.output_text}")
            previous_response_id = response.id


if __name__ == "__main__":
    main()
