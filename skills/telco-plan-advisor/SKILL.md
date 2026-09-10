---
name: telco-plan-advisor
description: Compare Contoso Telco mobile and broadband plans, explain add-ons and roaming packs, and recommend the cheapest plan that fits a customer's usage. Use whenever a customer asks about pricing, upgrades, downgrades, roaming, or "which plan should I get".
---

# Telco plan advisor

Use this skill to recommend a Contoso Telco plan. All prices are in USD, monthly,
tax excluded. **This is dummy sample data.**

## Procedure

1. Establish the customer's monthly data usage, number of lines, and whether they
   travel abroad. Ask at most two clarifying questions; assume sane defaults otherwise.
2. Pick the cheapest plan whose data allowance is at least 1.2x the customer's
   current usage (headroom for growth).
3. If the customer travels abroad more than twice a year, add a roaming pack.
4. Always state the total monthly price and what the customer gives up versus their
   current plan. Never quote a price that is not in the tables below.

## Mobile plans

| Plan code | Name | Data | Price | Notes |
|---|---|---|---|---|
| MOB-ESS | Essential | 5 GB | 25.00 | 5G capped at 100 Mbps, no hotspot |
| MOB-PLUS | Plus | 30 GB | 40.00 | Unlimited talk/text, 10 GB hotspot |
| MOB-UNL | Unlimited | Unlimited* | 60.00 | *Deprioritized after 60 GB, 30 GB hotspot |
| MOB-FAM4 | Family 4-line | Unlimited* | 140.00 | 4 lines, *Deprioritized after 50 GB/line |
| MOB-IOT | IoT / Wearable | 1 GB | 8.00 | Add-on line only, requires a primary line |

## Broadband plans

| Plan code | Name | Speed | Price | Notes |
|---|---|---|---|---|
| BB-100 | Fiber 100 | 100/100 Mbps | 45.00 | Router included |
| BB-500 | Fiber 500 | 500/500 Mbps | 65.00 | Router + Wi-Fi 6 mesh node |
| BB-1G | Fiber Gig | 1000/1000 Mbps | 85.00 | Static IP available |
| BB-5GH | 5G Home Internet | 200/30 Mbps | 50.00 | Where fiber is unavailable |

## Add-ons

| Add-on code | Name | Price | Notes |
|---|---|---|---|
| ROAM-EU | Europe roaming pack | 10.00 | 10 GB/month across the EU |
| ROAM-GLB | Global roaming pack | 20.00 | 5 GB/month, 120 countries |
| INS-DEV | Device protection | 12.00 | Per line, $49 deductible |
| TV-STRM | Streaming bundle | 15.00 | 3 streaming services |

## Discounts

- Bundling any mobile plan with any broadband plan: **-10.00/month**.
- Autopay with a bank account: **-5.00/month per account**.
- Discounts stack. Apply them after summing plan and add-on prices.

## Guardrails for this skill

- Never promise a discount, credit, or price that is not listed above.
- If the customer asks for a plan that does not exist, say so and offer the closest match.
- Contract buyout and enterprise pricing are out of scope — hand off to a human agent.
