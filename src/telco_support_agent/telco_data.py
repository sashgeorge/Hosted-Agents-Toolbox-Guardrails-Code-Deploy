"""Dummy Contoso Telco back-office data and the local function tools over it.

In a real agent these would call CRM, billing, and network-operations APIs. Here
they are in-memory so the sample runs with no external dependencies.
"""

from datetime import date

SUBSCRIBERS = {
    "555-0142": {
        "subscriber_id": "SUB-10041",
        "name": "Ana Ramirez",
        "plan_code": "MOB-PLUS",
        "plan_name": "Plus (30 GB)",
        "monthly_price": 40.00,
        "add_ons": ["INS-DEV"],
        "area_code": "206",
        "account_status": "active",
        "autopay": True,
        "contract_end": "2026-11-30",
    },
    "555-0177": {
        "subscriber_id": "SUB-10078",
        "name": "Dev Patel",
        "plan_code": "MOB-ESS",
        "plan_name": "Essential (5 GB)",
        "monthly_price": 25.00,
        "add_ons": [],
        "area_code": "312",
        "account_status": "active",
        "autopay": False,
        "contract_end": None,
    },
    "555-0199": {
        "subscriber_id": "SUB-10112",
        "name": "Contoso Bakery LLC",
        "plan_code": "MOB-FAM4",
        "plan_name": "Family 4-line",
        "monthly_price": 140.00,
        "add_ons": ["ROAM-EU", "TV-STRM"],
        "area_code": "617",
        "account_status": "past_due",
        "autopay": False,
        "contract_end": "2027-02-28",
    },
}

# Last three billing cycles of data usage, in GB.
DATA_USAGE = {
    "SUB-10041": [22.4, 28.9, 31.6],
    "SUB-10078": [4.1, 5.0, 6.8],
    "SUB-10112": [88.2, 91.5, 79.4],
}

OUTAGES = {
    "206": {
        "status": "degraded",
        "cause": "Fiber cut during roadworks near Ballard.",
        "affected_services": ["broadband"],
        "eta": "2026-09-10T18:00:00Z",
        "incident_id": "INC-4471",
    },
    "312": {"status": "healthy"},
    "617": {
        "status": "outage",
        "cause": "Cell site power failure, generator en route.",
        "affected_services": ["mobile_voice", "mobile_data"],
        "eta": "2026-09-10T14:30:00Z",
        "incident_id": "INC-4488",
    },
}

OVERAGE_RATE_PER_GB = 10.00


def lookup_subscriber(phone_number: str) -> dict:
    record = SUBSCRIBERS.get(phone_number.strip())
    if not record:
        return {"found": False, "message": f"No subscriber found for {phone_number}."}
    return {"found": True, **record}


def get_data_usage(subscriber_id: str) -> dict:
    history = DATA_USAGE.get(subscriber_id.strip().upper())
    if not history:
        return {"found": False, "message": f"No usage history for {subscriber_id}."}
    return {
        "found": True,
        "subscriber_id": subscriber_id,
        "gb_last_three_cycles": history,
        "average_gb": round(sum(history) / len(history), 1),
        "trend": "increasing" if history[-1] > history[0] else "stable or decreasing",
    }


def check_network_outage(area_code: str) -> dict:
    record = OUTAGES.get(area_code.strip())
    if not record:
        return {"area_code": area_code, "status": "unknown",
                "message": "No monitoring data for this area code."}
    return {"area_code": area_code, **record}


def estimate_bill(subscriber_id: str, projected_gb: float = 0.0) -> dict:
    """Estimate the next bill, including overage if the projection exceeds the plan cap."""
    record = next(
        (r for r in SUBSCRIBERS.values() if r["subscriber_id"] == subscriber_id.strip().upper()),
        None,
    )
    if not record:
        return {"found": False, "message": f"No subscriber {subscriber_id}."}

    caps = {"MOB-ESS": 5.0, "MOB-PLUS": 30.0, "MOB-UNL": None, "MOB-FAM4": None}
    cap = caps.get(record["plan_code"])
    overage_gb = max(0.0, projected_gb - cap) if cap is not None else 0.0
    overage_cost = round(overage_gb * OVERAGE_RATE_PER_GB, 2)
    autopay_discount = 5.00 if record["autopay"] else 0.00
    total = round(record["monthly_price"] + overage_cost - autopay_discount, 2)

    return {
        "found": True,
        "subscriber_id": record["subscriber_id"],
        "plan_price": record["monthly_price"],
        "plan_cap_gb": cap,
        "projected_gb": projected_gb,
        "overage_gb": round(overage_gb, 1),
        "overage_cost": overage_cost,
        "autopay_discount": autopay_discount,
        "estimated_total": total,
        "billing_date": date.today().replace(day=1).isoformat(),
    }


_HANDLERS = {
    "lookup_subscriber": lookup_subscriber,
    "get_data_usage": get_data_usage,
    "check_network_outage": check_network_outage,
    "estimate_bill": estimate_bill,
}

# Responses-API tool definitions for the local functions above.
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "lookup_subscriber",
        "description": "Look up a Contoso Telco subscriber account by phone number.",
        "parameters": {
            "type": "object",
            "properties": {
                "phone_number": {"type": "string",
                                 "description": "Phone number, for example 555-0142."}
            },
            "required": ["phone_number"],
        },
    },
    {
        "type": "function",
        "name": "get_data_usage",
        "description": "Get the last three billing cycles of mobile data usage in GB.",
        "parameters": {
            "type": "object",
            "properties": {
                "subscriber_id": {"type": "string",
                                  "description": "Subscriber ID, for example SUB-10041."}
            },
            "required": ["subscriber_id"],
        },
    },
    {
        "type": "function",
        "name": "check_network_outage",
        "description": "Check for an active network outage or degradation in an area code.",
        "parameters": {
            "type": "object",
            "properties": {
                "area_code": {"type": "string", "description": "Three-digit area code."}
            },
            "required": ["area_code"],
        },
    },
    {
        "type": "function",
        "name": "estimate_bill",
        "description": "Estimate the next monthly bill, including any data overage charge.",
        "parameters": {
            "type": "object",
            "properties": {
                "subscriber_id": {"type": "string"},
                "projected_gb": {"type": "number",
                                 "description": "Projected data usage in GB for the cycle."},
            },
            "required": ["subscriber_id"],
        },
    },
]


def call_local_tool(name: str, arguments: dict) -> dict:
    handler = _HANDLERS.get(name)
    if not handler:
        return {"error": f"Unknown local tool '{name}'."}
    return handler(**arguments)
