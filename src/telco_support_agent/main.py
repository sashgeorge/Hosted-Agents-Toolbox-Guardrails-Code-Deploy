"""Contoso Telco support agent — a Foundry hosted agent on the Responses protocol.

At startup the agent connects to the Foundry Toolbox MCP endpoint created in
step 2, discovers its tools, and loads the attached skills as procedural
instructions. At request time it runs a tool-calling loop over:

  * toolbox tools  — Foundry-managed (code interpreter, MCP servers, ...)
  * local tools    — the dummy telco back-office functions in telco_data.py

Conversation history is managed by the platform and retrieved with
`context.get_history()`.

Environment variables (set on the agent version at deploy time):
  FOUNDRY_PROJECT_ENDPOINT        auto-injected in hosted containers
  AZURE_AI_MODEL_DEPLOYMENT_NAME  model deployment used for reasoning
  TOOLBOX_NAME                    toolbox to connect to
  TOOLBOX_ENDPOINT                optional full MCP URL override (local runs)
"""

import asyncio
import json
import logging
import os

from azure.ai.projects import AIProjectClient
from azure.ai.agentserver.responses import (
    CreateResponse,
    ResponseContext,
    ResponseEventStream,
    ResponsesAgentServerHost,
    ResponsesServerOptions,
)
from azure.ai.agentserver.responses.models import get_input_expanded
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv

import telco_data
import toolbox_mcp

load_dotenv(override=False)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("telco-agent")

PROJECT_ENDPOINT = os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")
MODEL = os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"]
MAX_TOOL_ROUNDS = 8

_credential = DefaultAzureCredential()
_responses = AIProjectClient(
    endpoint=PROJECT_ENDPOINT, credential=_credential
).get_openai_client().responses
_toolbox_token = get_bearer_token_provider(_credential, "https://ai.azure.com/.default")

BASE_INSTRUCTIONS = """You are Max, a customer support agent for Contoso Telco.

You handle mobile and broadband questions: plans and pricing, billing and overages,
data usage, network outages, SIM/eSIM activation, and connectivity troubleshooting.

Rules:
- Always ground answers in tool results. Never invent a price, allowance, outage,
  or account detail.
- Look up the account before discussing anything account-specific. Ask for the
  phone number if you do not have it.
- Check for a network outage before walking anyone through device troubleshooting.
- Use the telco_calculator tool for any arithmetic the customer will rely on.
- Politely decline anything outside Contoso Telco support and offer a handoff.
- Never ask for a password, full payment card number, SIM PIN, or PUK.
- Keep replies short and concrete: the answer first, then at most three next steps."""

# --- Lazy startup state ----------------------------------------------------
_toolbox: toolbox_mcp.ToolboxClient | None = None
_tool_definitions: list[dict] = []
_instructions = BASE_INSTRUCTIONS
_ready = False


def _ensure_ready() -> None:
    """Connect to the toolbox on first request so health checks pass immediately."""
    global _toolbox, _tool_definitions, _instructions, _ready
    if _ready:
        return

    endpoint = toolbox_mcp.resolve_toolbox_endpoint()
    logger.info("Connecting to toolbox: %s", endpoint)
    _toolbox = toolbox_mcp.connect_with_retry(endpoint, _toolbox_token)

    definitions = list(telco_data.TOOL_DEFINITIONS)
    for tool in _toolbox.list_tools():
        definitions.append({
            "type": "function",
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
        })
    _tool_definitions = definitions

    _instructions = BASE_INSTRUCTIONS + _load_skills(_toolbox)
    _ready = True
    logger.info("Agent ready with %d tool(s)", len(_tool_definitions))


def _load_skills(toolbox: toolbox_mcp.ToolboxClient) -> str:
    """Fold the toolbox's skills into the system prompt as procedural playbooks."""
    skills = toolbox.list_skills()
    if not skills:
        return ""

    sections = ["\n\n# Playbooks\n\nFollow the playbook that matches the request."]
    for skill in skills:
        uri = skill.get("uri", "")
        try:
            body = toolbox.read_skill(uri)
        except Exception as exc:  # noqa: BLE001 - a bad skill must not break startup
            logger.warning("Could not read skill %s: %s", uri, exc)
            continue
        sections.append(f"\n## {skill.get('name', uri)}\n\n{body}")
    logger.info("Loaded %d skill(s) from the toolbox", len(sections) - 1)
    return "\n".join(sections)


def _dispatch_tool(name: str, arguments: dict) -> str:
    if name in {d["name"] for d in telco_data.TOOL_DEFINITIONS}:
        return json.dumps(telco_data.call_local_tool(name, arguments))
    assert _toolbox is not None
    return _toolbox.call_tool(name, arguments)


def _run_agent_loop(input_items: list[dict]) -> str:
    _ensure_ready()
    for _ in range(MAX_TOOL_ROUNDS):
        response = _responses.create(
            model=MODEL,
            instructions=_instructions,
            input=input_items,
            tools=_tool_definitions,
            tool_choice="auto",
            store=False,
        )

        tool_calls = [i for i in response.output
                      if getattr(i, "type", None) == "function_call"]
        if not tool_calls:
            return response.output_text or "(No response)"

        for call in tool_calls:
            raw_args = call.arguments
            try:
                arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                output = _dispatch_tool(call.name, arguments or {})
            except Exception as exc:  # noqa: BLE001 - surface failures to the model
                logger.error("Tool '%s' failed: %s", call.name, exc)
                output = f"Error calling tool: {exc}"

            input_items.append({
                "type": "function_call",
                "id": call.id,
                "call_id": call.call_id,
                "name": call.name,
                "arguments": raw_args if isinstance(raw_args, str) else json.dumps(raw_args),
            })
            input_items.append({
                "type": "function_call_output",
                "call_id": call.call_id,
                "output": output,
            })

    return "I could not finish that request. Please rephrase or ask for a human agent."


# --- Responses protocol handler -------------------------------------------

app = ResponsesAgentServerHost(
    options=ResponsesServerOptions(default_fetch_history_count=20),
)


def _input_text(request: CreateResponse) -> str:
    raw = request.get("input")
    if isinstance(raw, str):
        return raw
    for item in get_input_expanded(request):
        content = item.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in content:
                if part.get("text"):
                    return part["text"]
    return ""


def _build_input(current: str, history: list) -> list[dict]:
    items: list[dict] = []
    for item in history:
        for content in item.get("content") or []:
            text = content.get("text")
            if not text:
                continue
            if content.get("type") == "output_text":
                items.append({"role": "assistant", "content": text})
            elif content.get("type") == "input_text":
                items.append({"role": "user", "content": text})
    items.append({"role": "user", "content": current})
    return items


@app.response_handler
async def handler(
    request: CreateResponse,
    context: ResponseContext,
    cancellation_signal: asyncio.Event,
):
    stream = ResponseEventStream(response_id=context.response_id, request=request)
    yield stream.emit_created()
    yield stream.emit_in_progress()

    user_input = _input_text(request)
    if not user_input:
        message = stream.add_output_item_message()
        yield message.emit_added()
        for event in message.text_content("How can I help with your Contoso Telco service?"):
            yield event
        yield message.emit_done()
        yield stream.emit_completed()
        return

    try:
        history = await context.get_history()
    except Exception as exc:  # noqa: BLE001 - history is best-effort
        logger.warning("get_history failed: %s", exc)
        history = []

    loop = asyncio.get_running_loop()
    try:
        reply = await asyncio.wait_for(
            loop.run_in_executor(None, _run_agent_loop, _build_input(user_input, history)),
            timeout=240.0,
        )
    except asyncio.TimeoutError:
        reply = "That took too long on my side. Please try a simpler question."
    except Exception as exc:  # noqa: BLE001
        logger.exception("Agent loop failed")
        reply = f"Something went wrong handling that request: {exc}"

    message = stream.add_output_item_message()
    yield message.emit_added()
    text = message.add_text_content()
    yield text.emit_added()
    yield text.emit_delta(reply)
    yield text.emit_text_done()
    yield text.emit_done()
    yield message.emit_done()
    yield stream.emit_completed()


app.run()
