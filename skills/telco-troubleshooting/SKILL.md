---
name: telco-troubleshooting
description: Diagnose Contoso Telco connectivity problems — no signal, slow data, dropped calls, broadband outages, SIM and eSIM activation. Use whenever a customer reports something not working rather than asking about pricing.
---

# Telco troubleshooting

Structured triage for Contoso Telco network and device problems. **Dummy sample data.**

## Procedure

1. Call `check_network_outage` for the customer's area code **before** any device
   troubleshooting. If there is an active outage, report the ETA and stop — device
   steps will not help.
2. If there is no outage, identify the symptom in the decision table below and walk
   the customer through the listed steps in order.
3. Escalate with a ticket only after every step for the symptom has failed.

## Symptom decision table

| Symptom | Step 1 | Step 2 | Step 3 | Escalate as |
|---|---|---|---|---|
| No signal / SOS only | Toggle airplane mode for 15 s | Reseat SIM or re-download eSIM profile | Reset network settings | `NET-NOSVC` |
| Slow mobile data | Check usage against plan cap (deprioritization) | Switch 5G/LTE preference | Reset APN to `internet.contoso` | `NET-SLOW` |
| Dropped calls | Enable Wi-Fi calling | Disable VoLTE, retest, re-enable | Capture 3 call timestamps | `VOI-DROP` |
| Broadband down | Power-cycle ONT then router, 60 s apart | Check WAN LED (solid green = line OK) | Test with a direct ethernet cable | `BB-DOWN` |
| Broadband slow | Test wired speed at the router | Move mesh node off channel 1 | Check for >25 connected devices | `BB-SLOW` |
| eSIM won't activate | Confirm device is carrier-unlocked | Re-issue the activation QR code | Verify account has no billing hold | `SIM-ACT` |
| Can't send MMS | Enable mobile data (MMS needs it) | Reset APN | Confirm number is not on a block list | `MSG-MMS` |

## Escalation ticket format

When escalating, produce exactly these fields:

```
ticket_type: <code from the table>
subscriber_id: <from lookup_subscriber>
area_code: <from the customer>
steps_attempted: <comma-separated>
customer_impact: <one sentence>
priority: P1 if total loss of service, otherwise P3
```

## Service level expectations

| Ticket type | First response | Target resolution |
|---|---|---|
| P1 total loss of service | 1 hour | 8 hours |
| P2 degraded service | 4 hours | 24 hours |
| P3 single feature | 1 business day | 5 business days |

## Guardrails for this skill

- Never ask the customer for their full SIM PIN, PUK, account password, or payment card.
- Never promise a bill credit for an outage — say a credit "may be applied after review".
- If the customer describes an emergency, tell them to call local emergency services.
