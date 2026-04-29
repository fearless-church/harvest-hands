import os
import re
import requests
from datetime import datetime, timezone

OVERFLOW_CLIENT_ID = os.environ["OVERFLOW_CLIENT_ID"]
OVERFLOW_API_KEY = os.environ["OVERFLOW_API_KEY"]
BASE_URL = "https://server.overflow.co/api/v3"

# Church contribution (dollars) — update only when Ben instructs
CHURCH_CONTRIBUTION = 141276.92

# Registered recurring commitments (dollars) — update only when Ben instructs
REGISTERED_COMMITMENTS = 71151.36

def get_all_campaigns(headers):
    resp = requests.get(
        f"{BASE_URL}/campaigns",
        headers=headers,
        params={"isSubcampaign": "false", "limit": 100}
    )
    resp.raise_for_status()
    return resp.json().get("data", [])

def get_subcampaigns_for_parent(headers, parent_id):
    resp = requests.get(
        f"{BASE_URL}/campaigns",
        headers=headers,
        params={
            "isSubcampaign": "true",
            "parentCampaignId": parent_id,
            "limit": 100
        }
    )
    resp.raise_for_status()
    return resp.json().get("data", [])

def get_harvest_hands_total():
    headers = {
        "x-client-id": OVERFLOW_CLIENT_ID,
        "x-api-key": OVERFLOW_API_KEY
    }

    all_campaigns = get_all_campaigns(headers)

    la_campaign = next(
        (c for c in all_campaigns if "los angeles" in c["name"].lower()),
        None
    )

    if not la_campaign:
        raise ValueError("Could not find Los Angeles parent campaign.")

    print(f"Found LA campaign: {la_campaign['name']} ({la_campaign['id']})")

    subcampaigns = get_subcampaigns_for_parent(headers, la_campaign["id"])
    hh = next(
        (c for c in subcampaigns if "harvest hands" in c["name"].lower()),
        None
    )

    if not hh:
        raise ValueError("Harvest Hands subcampaign not found under Los Angeles.")

    campaign_id = hh["id"]
    print(f"Found '{hh['name']}' ({campaign_id})")

    # Sum ALL individual contributions (Approved + Processing)
    # instead of relying on totalContributionValue which may exclude Processing
    total = 0.0
    count = 0
    page = 1
    while True:
        resp = requests.get(
            f"{BASE_URL}/contributions",
            headers=headers,
            params={
                "campaignId": campaign_id,
                "limit": 100,
                "page": page
            }
        )
        resp.raise_for_status()
        data = resp.json()
        contributions = data.get("data", [])
        if not contributions:
            break
        for c in contributions:
            amount = float(c.get("amount", 0))
            total += amount
            count += 1
        page += 1

    print(f"Summed {count} contributions: ${total:,.2f}")

    # Sanity check against campaign summary
    summary_total = float(hh.get("totalContributionValue", 0))
    if abs(total - summary_total) > 1:
        print(f"  Note: campaign summary says ${summary_total:,.2f} (delta: ${total - summary_total:,.2f})")

    return total

def format_display(dollars):
    if dollars >= 1_000_000:
        return f"${dollars/1_000_000:.1f}M"
    elif dollars >= 1_000:
        return f"${dollars/1_000:.0f}K"
    else:
        return f"${dollars:,.0f}"

def update_html(overflow_dollars, church_dollars, registered_dollars):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # "Given" total = Overflow + Church (actual money moved)
    given_total = overflow_dollars + church_dollars

    # "Combined" total = Given + Registered Commitments (for floating widget + bar)
    combined_total = given_total + registered_dollars

    goal = 3_000_000
    phase1_goal = 1_500_000

    # Percentages based on COMBINED total (given + registered)
    fill_pct = min((combined_total / goal) * 100, 100)
    fill_str = f"{fill_pct:.1f}%"
    pct_p1 = min((combined_total / phase1_goal) * 100, 100)
    pct_p1_str = f"{pct_p1:.1f}%"
    pct_p2_str = fill_str

    # Display strings
    combined_display = format_display(combined_total)
    given_display = format_display(given_total)
    registered_display = f"${registered_dollars:,.0f}"

    # Update timestamp comment
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = re.sub(
        r'<!-- GIVING_LAST_UPDATED:.*?-->',
        f'<!-- GIVING_LAST_UPDATED: {now} -->',
        html
    )

    # --- Floating widget updates ---
    # Update the raised amount to combined total
    html = re.sub(
        r'(<div class="hh-fp-raised" id="fpRaised">)\$[\d,.]+[KM]?(</div>)',
        rf'\g<1>{combined_display}\g<2>',
        html
    )

    # Update label to "total commitments"
    html = re.sub(
        r'(<div class="hh-fp-label" id="fpLabel">)[^<]*(</div>)',
        r'\g<1>total commitments\g<2>',
        html
    )

    # Update bar fill
    html = re.sub(
        r'(<div class="hh-fp-bar-fill" id="fpBarFill" style="width:\s*)[\d.]+%',
        rf'\g<1>{fill_str}',
        html
    )

    # Update phase percentages
    html = re.sub(
        r'(<span class="hh-fp-phase-pct" id="fpPctP1">)[\d.]+%(</span>)',
        rf'\g<1>{pct_p1_str}\g<2>',
        html
    )
    html = re.sub(
        r'(<span class="hh-fp-phase-pct" id="fpPctP2">)[\d.]+%(</span>)',
        rf'\g<1>{pct_p2_str}\g<2>',
        html
    )

    # --- Thermometer section updates ---
    # Update data-raised to combined total
    html = re.sub(
        r'data-raised="[\d.]+"',
        f'data-raised="{combined_total:.0f}"',
        html
    )

    # Update thermometer fill width
    html = re.sub(
        r'(class="hh-thermo-fill"[^>]*style="width:\s*)[\d.]+%',
        rf'\g<1>{fill_str}',
        html
    )

    # Update the committed text in thermo-meta to show given total
    html = re.sub(
        r'(<span id="thermoGiven">)\$[\d,.]+[KM]?(</span>)',
        rf'\g<1>{given_display}\g<2>',
        html
    )

    # Update the registered commitments amount
    html = re.sub(
        r'(<span id="thermoRegistered">)\$[\d,.]+[KM]?(</span>)',
        rf'\g<1>{registered_display}\g<2>',
        html
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"index.html updated:")
    print(f"  Given: {given_display} (Overflow ${overflow_dollars:,.2f} + Church ${church_dollars:,.2f})")
    print(f"  Registered Commitments: {registered_display}")
    print(f"  Combined: {combined_display} ({fill_str} of $3M goal)")

if __name__ == "__main__":
    overflow_total = get_harvest_hands_total()
    print(f"Overflow: ${overflow_total:,.2f} + Church: ${CHURCH_CONTRIBUTION:,.2f} + Registered: ${REGISTERED_COMMITMENTS:,.2f}")
    total = overflow_total + CHURCH_CONTRIBUTION + REGISTERED_COMMITMENTS
    print(f"Combined Total: ${total:,.2f}")
    update_html(overflow_total, CHURCH_CONTRIBUTION, REGISTERED_COMMITMENTS)
