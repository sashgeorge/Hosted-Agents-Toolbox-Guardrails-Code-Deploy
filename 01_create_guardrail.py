"""Step 1 — create the guardrail (Responsible AI policy) in code.

A Foundry guardrail is an ARM resource:
  /subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.CognitiveServices
  /accounts/{account}/raiPolicies/{name}

This script creates one tuned for a telco customer-support agent:
  * content-safety controls on both prompts and completions,
  * a jailbreak (user prompt attack) shield on prompts,
  * optionally, preview network-egress rules that restrict the agent's
    outbound calls to the telco partner APIs it actually needs.

The resulting ARM resource ID is what steps 2 and 3 attach to the toolbox and to
the hosted agent.

Run: python 01_create_guardrail.py
"""

import config
import foundry_client as fc

# Block at Medium and above for the four core harm categories, on input and output.
_CORE_CATEGORIES = ["Hate", "Sexual", "Violence", "Selfharm"]
_SOURCES = ["Prompt", "Completion"]

CONTENT_FILTERS = [
    {
        "name": category,
        "enabled": True,
        "severityThreshold": "Medium",
        "blocking": True,
        "source": source,
    }
    for source in _SOURCES
    for category in _CORE_CATEGORIES
] + [
    # Prompt-shield controls have no severity threshold — they are detect/block only.
    {"name": "Jailbreak", "enabled": True, "blocking": True, "source": "Prompt"},
    {"name": "Indirect Attack", "enabled": True, "blocking": True, "source": "Prompt"},
    {"name": "Profanity", "enabled": True, "blocking": True, "source": "Prompt"},
]

# Preview: ordered outbound rules. First match wins; unmatched traffic hits defaultAction.
EGRESS_POLICY = {
    "mode": "Audit",  # switch to "Enforced" once the audit log looks clean
    "defaultAction": "Deny",
    "rules": [
        {
            "name": "allow-telco-billing-api",
            "ruleType": "Fqdn",
            "match": {"host": "*.contoso-telco.example.com"},
            "action": {"actionType": "Allow"},
        },
        {
            "name": "tag-partner-traffic",
            "ruleType": "Fqdn",
            "match": {"host": "partner-api.contoso-telco.example.com"},
            "action": {
                "actionType": "Transform",
                "headers": [
                    {"operation": "Set", "name": "X-Trace-Source", "value": "telco-agent"}
                ],
            },
        },
    ],
}


def build_policy_body() -> dict:
    properties = {
        "mode": "Blocking",
        "basePolicyName": "Microsoft.DefaultV2",
        "contentFilters": CONTENT_FILTERS,
    }
    if config.ENABLE_EGRESS_GUARDRAIL:
        properties["egressPolicy"] = EGRESS_POLICY
    return {"properties": properties}


def main() -> None:
    config.require("SUBSCRIPTION_ID", "RESOURCE_GROUP", "ACCOUNT_NAME")

    policy_id = config.rai_policy_arm_id()
    print(f"Creating guardrail '{config.GUARDRAIL_NAME}' on {config.ACCOUNT_NAME} ...")

    result = fc.arm("PUT", policy_id, config.RAI_API_VERSION, build_policy_body())

    filters = result.get("properties", {}).get("contentFilters", [])
    print(f"  guardrail ready with {len(filters)} control(s)")
    if config.ENABLE_EGRESS_GUARDRAIL:
        egress = result.get("properties", {}).get("egressPolicy", {})
        print(f"  egress policy: mode={egress.get('mode')} "
              f"default={egress.get('defaultAction')} rules={len(egress.get('rules', []))}")

    print("\nARM resource ID (used by the toolbox and the agent):")
    print(f"  {policy_id}")


if __name__ == "__main__":
    main()
