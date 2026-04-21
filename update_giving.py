import os
import re
import requests

OVERFLOW_CLIENT_ID = os.environ["OVERFLOW_CLIENT_ID"]
OVERFLOW_API_KEY = os.environ["OVERFLOW_API_KEY"]
BASE_URL = "https://server.overflow.co/api/v3"

# Church contribution in dollars — update only when Ben instructs
CHURCH_CONTRIBUTION = 141276.92  # $141,276.92

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

    # Pull from LA only — same subcampaign appears under multiple parents
    # causing double counting. LA holds the real total.
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

    # API returns dollars, not cents
    amount = float(hh.get("totalContributionValue", 0))
    print(f"Found '{hh['name']}': ${amount:,.2f}")
    return amount

def format_display(dollars):
    if dollars >= 1_000_000:
        return f"${dollars/1_000_000:.1f}M"
    elif dollars >= 1_000:
        return f"${dollars/1_000:.0f}K"
    else:
        return f"${dollars:,.0f}"

def update_html(total_dollars):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    goal = 3_000_000
    fill_pct = min((total_dollars / goal) * 100, 100)
    fill_str = f"{fill_pct:.1f}%"
    display = format_display(total_dollars)

    html = re.sub(
        r'data-raised="[\d.]+"',
        f'data-raised="{total_dollars:.0f}"',
        html
    )

    html = re.sub(
        r'(class="hh-thermo-fill"[^>]*style="width:\s*)[\d.]+%',
        rf'\g<1>{fill_str}',
        html
    )

    html = re.sub(
        r'(<span>)\$[\d,.]+[KM]? committed(</span>)',
        rf'\g<1>{display} committed\g<2>',
        html
    )

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"index.html updated: {display} committed ({fill_str} of goal)")

if __name__ == "__main__":
    overflow_total = get_harvest_hands_total()
    total = overflow_total + CHURCH_CONTRIBUTION
    print(f"Overflow: ${overflow_total:,.2f} + Church: ${CHURCH_CONTRIBUTION:,.2f} = Total: ${total:,.2f}")
    update_html(total)
