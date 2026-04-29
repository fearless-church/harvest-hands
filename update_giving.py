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

# Statuses to include in the total
INCLUDE_STATUSES = {"CONFIRMED", "PAID_OUT", "PROCESSING", "PENDING"}

def get_harvest_hands_campaign_id():
    """Find the Harvest Hands subcampaign ID under Los Angeles."""
    headers = {
        "x-client-id": OVERFLOW_CLIENT_ID,
        "x-api-key": OVERFLOW_API_KEY
    }

    resp = requests.get(
        f"{BASE_URL}/campaigns",
        headers=headers,
        params={"isSubcampaign": "false", "limit": 100}
    )
    resp.raise_for_status()
    campaigns = resp.json().get("data", [])

    la = next((c for c in campaigns if "los angeles" in c["name"].lower()), None)
    if not la:
        raise ValueError("Los Angeles campaign not found.")

    resp = requests.get(
        f"{BASE_URL}/campaigns",
        headers=headers,
        params={"isSubcampaign": "true", "parentCampaignId": la["id"], "limit": 100}
    )
    resp.raise_for_status()
    subs = resp.json().get("data", [])

    hh = next((c for c in subs if "harvest hands" in c["name"].lower()), None)
    if not hh:
        raise ValueError("Harvest Hands subcampaign not found.")

    print(f"Found subcampaign: {hh['name']} ({hh['id']})")
    return hh["id"]

def get_all_contributions(subcampaign_id):
    """Page through all contributions for this subcampaign and sum valid ones."""
    headers = {
        "x-client-id": OVERFLOW_CLIENT_ID,
        "x-api-key": OVERFLOW_API_KEY
    }

    total = 0.0
    page = 1
    included = 0
    skipped = 0

    while True:
        resp = requests.get(
            f"{BASE_URL}/contributions",
            headers=headers,
            params={
                "subcampaignId": subcampaign_id,
                "limit": 100,
                "page": page
            }
        )
        resp.raise_for_status()
        data = resp.json()
        contributions = data.get("data", [])
        total_count = data.get("totalCount", 0)

        if not contributions:
            break

        for c in contributions:
            status = c.get("status", "")
            amount = float(c.get("amount", 0))
            if status in INCLUDE_STATUSES:
                total += amount
                included += 1
            else:
                skipped += 1
                print(f"  Skipped: status={status} amount=${amount:,.2f}")

        print(f"Page {page}: {len(contributions)} contributions, running total ${total:,.2f}")

        if page * 100 >= total_count:
            break
        page += 1

    print(f"Done: {included} included, {skipped} skipped, total ${total:,.2f}")

    # Safety guard
    if total <= 0:
        raise ValueError(f"API returned ${total} for Harvest Hands. Refusing to update.")

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

    # Percentages based on COMBINED total
    fill_pct = min((combined_total / goal) * 100, 100)
    fill_str = f"{fill_pct:.1f}%"
    pct_p1 = min((combined_total / phase1_goal) * 100, 100)
    pct_p1_str = f"{pct_p1:.1f}%"

    # Display strings
    combined_display = format_display(combined_total)
    given_display = format_display(given_total)
    registered_display = f"${registered_dollars:,.0f}"

    # Update timestamp
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = re.sub(
        r'<!-- GIVING_LAST_UPDATED:.*?-->',
        f'<!-- GIVING_LAST_UPDATED: {now} -->',
        html
    )

    # --- Floating widget ---
    html = re.sub(
        r'(<div class="hh-fp-raised" id="fpRaised">)\$[\d,.]+[KM]?(</div>)',
        rf'\g<1>{combined_display}\g<2>',
        html
    )
    html = re.sub(
        r'(<div class="hh-fp-bar-fill" id="fpBarFill" style="width:\s*)[\d.]+%',
        rf'\g<1>{fill_str}',
        html
    )
    html = re.sub(
        r'(<span class="hh-fp-phase-pct" id="fpPctP1">)[\d.]+%(</span>)',
        rf'\g<1>{pct_p1_str}\g<2>',
        html
    )
    html = re.sub(
        r'(<span class="hh-fp-phase-pct" id="fpPctP2">)[\d.]+%(</span>)',
        rf'\g<1>{fill_str}\g<2>',
        html
    )

    # --- Thermometer section ---
    html = re.sub(
        r'data-raised="[\d.]+"',
        f'data-raised="{combined_total:.0f}"',
        html
    )
    html = re.sub(
        r'(class="hh-thermo-fill"[^>]*style="width:\s*)[\d.]+%',
        rf'\g<1>{fill_str}',
        html
    )
    html = re.sub(
        r'(<span id="thermoGiven">)\$[\d,.]+[KM]?(</span>)',
        rf'\g<1>{given_display}\g<2>',
        html
    )
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
    subcampaign_id = get_harvest_hands_campaign_id()
    overflow_total = get_all_contributions(subcampaign_id)
    print(f"Overflow: ${overflow_total:,.2f} + Church: ${CHURCH_CONTRIBUTION:,.2f} + Registered: ${REGISTERED_COMMITMENTS:,.2f}")
    total = overflow_total + CHURCH_CONTRIBUTION + REGISTERED_COMMITMENTS
    print(f"Combined Total: ${total:,.2f}")
    update_html(overflow_total, CHURCH_CONTRIBUTION, REGISTERED_COMMITMENTS)
