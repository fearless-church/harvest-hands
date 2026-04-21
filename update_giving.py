import os
import re
import requests

OVERFLOW_CLIENT_ID = os.environ["OVERFLOW_CLIENT_ID"]
OVERFLOW_API_KEY = os.environ["OVERFLOW_API_KEY"]
BASE_URL = "https://server.overflow.co/api/v3"

# Church contribution (in cents) — update only when Ben instructs
CHURCH_CONTRIBUTION_CENTS = 14127692  # $141,276.92

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

    target_parents = ["los angeles", "online"]
    matched_parents = [
        c for c in all_campaigns
        if any(t in c["name"].lower() for t in target_parents)
    ]

    if not matched_parents:
        raise ValueError("Could not find Los Angeles or Online parent campaigns.")

    print(f"Found {len(matched_parents)} parent campaign(s):")
    for p in matched_parents:
        print(f"  {p['name']} ({p['id']})")

    total_cents = 0
    found_count = 0

    for parent in matched_parents:
        subcampaigns = get_subcampaigns_for_parent(headers, parent["id"])
        hh = next(
            (c for c in subcampaigns if "harvest hands" in c["name"].lower()),
            None
        )
        if hh:
            amount = hh.get("totalContributionValue", 0)
            print(f"  Found '{hh['name']}' under '{parent['name']}': {amount} cents")
            total_cents += amount
            found_count += 1
        else:
            print(f"  No Harvest Hands subcampaign found under '{parent['name']}'")

    if found_count == 0:
        raise ValueError("Harvest Hands subcampaign not found under any parent campaign.")

    print(f"Overflow total across {found_count} campus(es): {total_cents} cents")
    return total_cents

def format_short(amount_cents):
    dollars = amount_cents / 100
    if dollars >= 1_000_000:
        return f"${dollars/1_000_000:.1f}M"
    elif dollars >= 1_000:
        return f"${dollars/1_000:.0f}K"
    else:
        return f"${dollars:,.0f}"

def update_html(total_cents):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    dollars = total_cents / 100
    goal = 3_000_000
    fill_pct = min((dollars / goal) * 100, 100)
    fill_str = f"{fill_pct:.1f}%"
    short = format_short(total_cents)

    html = re.sub(
        r'data-raised="[\d.]+"',
        f'data-raised="{dollars:.0f}"',
        html
    )

    html = re.sub(
        r'(class="hh-thermo-fill"[^>]*style="width:\s*)[\d.]+%',
        rf'\g<1>{fill_str}',
        html
    )

    html = re.sub(
        r'(<span>)\$[\d,.]+[KM]? committed(</span>)',
        rf'\g<1>{short} committed\g<2>',
        html
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"index.html updated: {short} committed ({fill_str} of goal)")

if __name__ == "__main__":
    overflow_total = get_harvest_hands_total()
    church = CHURCH_CONTRIBUTION_CENTS
    total = overflow_total + church
    print(f"Overflow: {format_short(overflow_total)} + Church: {format_short(church)} = Total: {format_short(total)}")
    update_html(total)
