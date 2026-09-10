"""Invoke the prompt agent from 06_deploy_prompt_agent.py.

Prompt agents are invoked differently from hosted agents. A hosted agent has its
own endpoint, so `get_openai_client(agent_name=...)` binds to it. A prompt agent
lives inside the project, so you use the project-level client and identify the
agent per request with an `agent_reference` in the request body.

This script also handles the two things the toolbox can throw back:
  * `mcp_approval_request` output items, when a tool has require_approval="always"
  * `content_filter` errors, when the guardrail blocks a prompt

Run: python 07_invoke_prompt_agent.py ["question"] ["follow-up"]
"""

import json
import sys

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential
from openai import APIStatusError
from openai.types.responses.response_input_param import (
    McpApprovalResponse,
    ResponseInputParam,
)

import config

DEFAULT_PROMPTS = [
    "My number is 555-0199. Why is my phone showing SOS only?",
    "Which plan would suit me if I use about 45 GB a month?",
]

# Approve tool calls without prompting. Set to False to review each one.
AUTO_APPROVE = True


def agent_reference() -> dict:
    return {"agent_reference": {"name": config.PROMPT_AGENT_NAME, "type": "agent_reference"}}


def describe_tool_calls(response) -> None:
    """Surface which toolbox tools ran, so a wrong answer is easy to trace."""
    for item in response.output:
        kind = getattr(item, "type", None)
        if kind == "mcp_list_tools":
            tools = getattr(item, "tools", None) or []
            print(f"  [discovered {len(tools)} toolbox tool(s)]")
        elif kind == "mcp_call":
            error = getattr(item, "error", None)
            status = "failed" if error else "ok"
            print(f"  [tool {getattr(item, 'name', '?')} -> {status}]")
            if error:
                print(f"    {error}")


def collect_approvals(response) -> ResponseInputParam:
    approvals: ResponseInputParam = []
    for item in response.output:
        if getattr(item, "type", None) != "mcp_approval_request" or not item.id:
            continue
        print("  approval requested")
        print(f"    server: {item.server_label}")
        print(f"    tool:   {getattr(item, 'name', '<unknown>')}")
        print(f"    args:   {json.dumps(getattr(item, 'arguments', None), default=str)}")

        approve = AUTO_APPROVE or input("    approve? (y/N): ").strip().lower() == "y"
        approvals.append(
            McpApprovalResponse(
                type="mcp_approval_response",
                approve=approve,
                approval_request_id=item.id,
            )
        )
    return approvals


def ask(openai, conversation_id: str, prompt: str) -> None:
    print(f"\n> {prompt}")
    try:
        response = openai.responses.create(
            conversation=conversation_id,
            input=prompt,
            extra_body=agent_reference(),
        )
    except APIStatusError as error:
        body = error.body if isinstance(error.body, dict) else {}
        if body.get("code") == "content_filter":
            print("  BLOCKED by the guardrail at the input stage.")
            print(f"  {body.get('message', error)}")
            return
        raise

    describe_tool_calls(response)

    # Settle any approval requests, then continue the same response chain.
    approvals = collect_approvals(response)
    while approvals:
        response = openai.responses.create(
            input=approvals,
            previous_response_id=response.id,
            extra_body=agent_reference(),
        )
        describe_tool_calls(response)
        approvals = collect_approvals(response)

    print(f"  {response.output_text or '(no text output)'}")


def main() -> None:
    config.require("PROJECT_ENDPOINT")
    prompts = sys.argv[1:] or DEFAULT_PROMPTS

    project = AIProjectClient(
        endpoint=config.PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )
    openai = project.get_openai_client()

    print(f"Agent: {config.PROMPT_AGENT_NAME}")
    conversation = openai.conversations.create()
    print(f"Conversation: {conversation.id}")

    for prompt in prompts:
        ask(openai, conversation.id, prompt)


if __name__ == "__main__":
    main()
