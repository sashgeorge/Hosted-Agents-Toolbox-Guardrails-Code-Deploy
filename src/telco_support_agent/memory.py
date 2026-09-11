"""Long-term memory for the hosted agent.

Wraps the Foundry memory store with two calls the agent loop needs:

    recall(scope, user_input)   -> text to fold into the system prompt
    remember(scope, turn)       -> queue extraction from the finished turn

Memory is an enhancement, never a dependency. Every method here swallows its own
failures: if the store is unreachable the agent answers without recall rather
than erroring.
"""

import logging
import os
import re

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MemorySearchOptions

logger = logging.getLogger(__name__)

# Scope partitions the store. Everything written under one scope is only ever
# retrieved for that scope, so it must identify a single customer.
# Validation differs per endpoint: writes accept more characters than reads do.
# The read path is the strictest, so keep scopes to A-Z a-z 0-9 - _ only.
_PHONE = re.compile(r"\b\d{3}-\d{4}\b")
_UNSAFE_SCOPE = re.compile(r"[^A-Za-z0-9_-]")

MAX_MEMORIES = 5
# Seconds the service waits before extracting, so a multi-turn exchange batches
# into one extraction pass instead of one per turn.
UPDATE_DELAY = 60


def scope_for(text: str, subscribers: dict, fallback: str) -> str:
    """Prefer a durable per-subscriber scope; fall back to the conversation.

    A conversation-scoped memory is not long-term memory, so this is only a
    placeholder until the customer identifies themselves. In a real deployment,
    scope on the authenticated user instead of a phone number in the transcript.
    """
    for match in _PHONE.findall(text or ""):
        record = subscribers.get(match)
        if record:
            return _sanitize(f"subscriber-{record['subscriber_id']}")
    return _sanitize(f"conversation-{fallback}")


def _sanitize(scope: str) -> str:
    return _UNSAFE_SCOPE.sub("-", scope)[:256]


class Memory:
    def __init__(self, project: AIProjectClient, store_name: str):
        self._stores = project.beta.memory_stores
        self._name = store_name
        self.enabled = bool(store_name)
        if not self.enabled:
            logger.info("MEMORY_STORE_NAME not set; long-term memory disabled")

    def recall(self, scope: str, user_input: str) -> str:
        """Return a prompt-ready block of relevant memories, or an empty string."""
        if not self.enabled:
            return ""
        try:
            result = self._stores.search_memories(
                name=self._name,
                scope=scope,
                items=user_input,
                options=MemorySearchOptions(max_memories=MAX_MEMORIES),
            )
        except Exception as exc:  # noqa: BLE001 - recall is best-effort
            logger.warning("memory search failed for %s: %s", scope, exc)
            return ""

        lines = []
        for entry in getattr(result, "memories", None) or []:
            item = getattr(entry, "memory_item", None)
            if item is not None and getattr(item, "content", None):
                lines.append(f"- ({item.kind}) {item.content}")
        if not lines:
            return ""

        logger.info("recalled %d memory item(s) for %s", len(lines), scope)
        return (
            "\n\n# What you already know about this customer\n\n"
            "Recalled from earlier conversations. Treat it as context, not as "
            "verified account data, and confirm anything you act on.\n\n"
            + "\n".join(lines)
        )

    def remember(self, scope: str, user_input: str, assistant_reply: str) -> None:
        """Queue extraction from this turn. Returns without waiting for the result."""
        if not self.enabled:
            return
        try:
            self._stores.begin_update_memories(
                name=self._name,
                scope=scope,
                items=[
                    {"type": "message", "role": "user", "content": user_input},
                    {"type": "message", "role": "assistant", "content": assistant_reply},
                ],
                update_delay=UPDATE_DELAY,
            )
            logger.info("queued memory update for %s", scope)
        except Exception as exc:  # noqa: BLE001 - never fail a turn over memory
            logger.warning("memory update failed for %s: %s", scope, exc)


def from_environment(project: AIProjectClient) -> Memory:
    return Memory(project, os.getenv("MEMORY_STORE_NAME", ""))
