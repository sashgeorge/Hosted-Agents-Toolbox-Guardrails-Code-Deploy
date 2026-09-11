"""Create the long-term memory store for the telco agents.

A Foundry memory store gives agents recall that outlives a session. The platform
extracts memories from conversation turns and retrieves relevant ones later, so
you do not build an embedding pipeline yourself.

Three kinds of memory are extracted:
  * user_profile  durable facts about the person (plan, device, preferences)
  * chat_summary  condensed history of past conversations
  * procedural    what worked when solving this customer's problems before

Memories are partitioned by `scope`. Everything written under one scope is only
ever retrieved for that scope, so a scope should identify one customer.

The store does its own extraction and retrieval, so it needs a chat model and an
embedding model deployment of its own. Both are required.

Run: python 09_create_memory_store.py
"""

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    MemoryStoreDefaultDefinition,
    MemoryStoreDefaultOptions,
)
from azure.identity import DefaultAzureCredential

import config

# What the extractor should pull out of a telco support conversation.
USER_PROFILE_DETAILS = (
    "Contoso Telco customer facts worth remembering across conversations: "
    "current plan and add-ons, number of lines, typical monthly data usage, "
    "device model, home area code, roaming and travel habits, billing "
    "preferences such as autopay or paperless, accessibility needs, and "
    "recurring problems the customer has reported. "
    "Never store passwords, SIM PINs, PUK codes, or payment card numbers."
)

OPTIONS = MemoryStoreDefaultOptions(
    user_profile_enabled=True,
    user_profile_details=USER_PROFILE_DETAILS,
    chat_summary_enabled=True,
    procedural_memory_enabled=True,
    # 0 means memories never expire. Set a TTL if retention policy requires one.
    default_ttl_seconds=0,
)


def main() -> None:
    config.require("PROJECT_ENDPOINT")

    project = AIProjectClient(
        endpoint=config.PROJECT_ENDPOINT,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )
    stores = project.beta.memory_stores

    existing = None
    try:
        existing = stores.get(name=config.MEMORY_STORE_NAME)
    except Exception:  # noqa: BLE001 - a missing store is the expected first-run case
        existing = None

    if existing:
        print(f"Memory store '{config.MEMORY_STORE_NAME}' already exists; updating metadata.")
        store = stores.update(
            name=config.MEMORY_STORE_NAME,
            description="Long-term memory for the Contoso Telco support agents.",
        )
    else:
        print(f"Creating memory store '{config.MEMORY_STORE_NAME}' ...")
        print(f"  chat model:      {config.MEMORY_CHAT_MODEL}")
        print(f"  embedding model: {config.MEMORY_EMBEDDING_MODEL}")
        store = stores.create(
            name=config.MEMORY_STORE_NAME,
            description="Long-term memory for the Contoso Telco support agents.",
            definition=MemoryStoreDefaultDefinition(
                chat_model=config.MEMORY_CHAT_MODEL,
                embedding_model=config.MEMORY_EMBEDDING_MODEL,
                options=OPTIONS,
            ),
        )

    print(f"  name: {store.name}")
    print("  extracting: user_profile, chat_summary, procedural")
    print("  retention: no expiry")

    print("\nScope convention used by this sample:")
    print("  subscriber-<SUB-ID>     once a phone number is recognised")
    print("  conversation-<id>       before the customer is identified")
    print("  (scope allows only A-Z a-z 0-9 - _)")

    print("\nNext:")
    print("  python 03_deploy_hosted_agent.py   # hosted agent reads/writes memory")
    print("  python 06_deploy_prompt_agent.py   # prompt agent gets a memory_search tool")


if __name__ == "__main__":
    main()
