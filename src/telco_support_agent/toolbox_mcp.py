"""Minimal MCP client for the Foundry Toolbox endpoint.

The toolbox exposes two things over one streamable-HTTP MCP endpoint:
  * tools     — discovered with `tools/list`, invoked with `tools/call`
  * resources — the attached skills, discovered with `resources/list` and read
                with `resources/read` (URIs look like `skill://<name>`)
"""

import json
import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

# The platform reserves the FOUNDRY_ prefix, so custom vars must avoid it.
_TOOLBOX_FEATURES = os.getenv("TOOLBOX_FEATURES", "Skills=V1Preview, Toolboxes=V1Preview")


def resolve_toolbox_endpoint() -> str:
    """Resolve the toolbox MCP URL from an explicit override or project endpoint + name."""
    explicit = os.getenv("TOOLBOX_ENDPOINT", "").strip()
    if explicit:
        return explicit if "api-version=" in explicit else (
            explicit + ("&" if "?" in explicit else "?") + "api-version=v1"
        )

    project = os.environ["FOUNDRY_PROJECT_ENDPOINT"].rstrip("/")
    name = os.environ["TOOLBOX_NAME"]
    return f"{project}/toolboxes/{name}/mcp?api-version=v1"


class ToolboxClient:
    """Synchronous JSON-RPC client against the toolbox MCP endpoint."""

    def __init__(self, endpoint: str, token_provider):
        self.endpoint = endpoint
        self._get_token = token_provider
        self._session_id: str | None = None
        self._request_id = 0

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self._get_token()}",
        }
        if _TOOLBOX_FEATURES:
            headers["Foundry-Features"] = _TOOLBOX_FEATURES
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    def _rpc(self, method: str, params: dict | None = None, timeout: float = 120.0) -> dict:
        self._request_id += 1
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.post(
                self.endpoint,
                headers=self._headers(),
                json={"jsonrpc": "2.0", "id": self._request_id,
                      "method": method, "params": params or {}},
            )
            response.raise_for_status()
            if not self._session_id:
                self._session_id = response.headers.get("mcp-session-id")
            payload = _parse_body(response)

        if payload.get("error"):
            raise RuntimeError(f"Toolbox {method} failed: {payload['error']}")
        return payload.get("result", {})

    def initialize(self) -> str:
        result = self._rpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "telco-support-agent", "version": "1.0.0"},
        })
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            client.post(self.endpoint, headers=self._headers(),
                        json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result.get("serverInfo", {}).get("name", "toolbox")

    def list_tools(self) -> list[dict]:
        return self._rpc("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise RuntimeError(f"Toolbox tool '{name}' returned an error result")
        return _flatten_content(result.get("content", [])) or json.dumps(result)

    def list_skills(self) -> list[dict]:
        """Skills attached to the toolbox, surfaced as MCP resources."""
        try:
            return self._rpc("resources/list").get("resources", [])
        except Exception as exc:  # noqa: BLE001 - resources are optional
            logger.warning("resources/list unavailable: %s", exc)
            return []

    def read_skill(self, uri: str) -> str:
        result = self._rpc("resources/read", {"uri": uri})
        return _flatten_content(result.get("contents", []))


def _parse_body(response: httpx.Response) -> dict:
    """Accept both a plain JSON body and a one-shot SSE frame."""
    text = response.text.strip()
    if text.startswith("{"):
        return response.json()
    for line in text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return {}


def _flatten_content(items: list) -> str:
    texts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("text"):
            texts.append(item["text"])
        elif isinstance(item.get("resource"), dict) and item["resource"].get("text"):
            texts.append(item["resource"]["text"])
    return "\n".join(texts)


def connect_with_retry(endpoint: str, token_provider, attempts: int = 5) -> ToolboxClient:
    """The toolbox proxy can return transient errors or an empty tool list while warming up."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            client = ToolboxClient(endpoint, token_provider)
            server = client.initialize()
            tools = client.list_tools()
            if tools:
                logger.info("Toolbox '%s' connected: %d tool(s)", server, len(tools))
                return client
            logger.warning("Toolbox returned 0 tools on attempt %d", attempt)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Toolbox connect attempt %d failed: %s", attempt, exc)
        time.sleep(min(2**attempt, 15))
    if last_error:
        raise last_error
    raise RuntimeError("Toolbox returned no tools after retries")
