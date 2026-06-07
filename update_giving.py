import os
import re
import time
import requests
from datetime import datetime, timezone

OVERFLOW_CLIENT_ID = os.environ["OVERFLOW_CLIENT_ID"]
OVERFLOW_API_KEY = os.environ["OVERFLOW_API_KEY"]
BASE_URL = "https://server.overflow.co/api/v3"

# Overflow's bot-protection layer intermittently returns a transient 403 to the
# default python-requests client. Send a normal browser User-Agent and reuse one
# Session so the auth headers + UA are always attached to every call.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
RETRY_STATUSES = {403, 429, 500, 502, 503, 504}

SESSION = requests.Session()
SESSION.headers.update({
    "x-client-id": OVERFLOW_CLIENT_ID,
    "x-api-key": OVERFLOW_API_KEY,
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
})

MAX_BACKOFF = 30  # seconds — cap so a single run never stalls too long

def _retry_wait(resp, attempt):
    """Prefer the server's Retry-After hint (rate limits), else exponential backoff."""
    retry_after = resp.headers.get("Retry-After") if resp is not None else None
    if retry_after:
        try:
            return min(int(retry_after), MAX_BACKOFF)
        except (TypeError, ValueError):
            pass
    return min(2 ** attempt, MAX_BACKOFF)

def api_get(url, params=None, tries=5):
    """GET an Overflow endpoint with retry + backoff.

    A transient 403/429/5xx should not kill the whole run, so retry a few times
    with exponential backoff (honoring a Retry-After header when present) before
    giving up. The auth headers and User-Agent come from SESSION.
    """
    resp = None
    for attempt in range(1, tries + 1):
        try:
            resp = SESSION.get(url, params=params, timeout=30)
        except requests.exceptions.RequestException as e:
            if attempt < tries:
                wait = min(2 ** attempt, MAX_BACKOFF)
                print(f"Overflow API request error on attempt {attempt}/{tries} ({e}); retrying in {wait}s...")
                time.sleep(wait)
                continue
            raise
        if resp.status_code in RETRY_STATUSES and attempt < tries:
            wait = _retry_wait(resp, attempt)
            print(f"Overflow API {resp.status_code} on attempt {attempt}/{tries}; retrying in {wait}s...")
            time.sleep(wait)
            continue
        return resp
    return resp

# Church contribution (dollars) — update only when Ben instructs
CHURCH_CONTRIBUTION = 141276.92

# Registered recurring commitments (dollars) — update only when Ben instructs
REGISTERED_COMMITMENTS = 71151.36

# Statuses to include in the total
INCLUDE_STATUSES = {"CONFIRMED", "PAID_OUT", "PROCESSING", "PENDING", "APPROVED"}

def get_harvest_hands_campaign_id():
    """Find the Harvest Hands subcampaign ID under Los Angeles."""
    resp = api_get(
        f"{BASE_URL}/campaigns",
        params={"isSubcampaign": "false", "limit": 100}
    )
    resp.raise_for_status()
    campaigns = resp.json().get("data", [])

    la = next((c for c in campaigns if "los angeles" in c["name"].lower()), None)
    if not la:
        raise ValueError("Los Angeles campaign not found.")

    resp = api_get(
        f"{BASE_URL}/campaigns",
        params={"isSubcampaign": "true", "parentCampaignId": la["id"], "limit": 100}
    )
    resp.raise_for_status()
    subs = resp.json().get("data", [])

    hh = next((c for c in subs if "harvest hands" in c["name"].lower()), None)
    if not hh:
        raise ValueError("Harvest Hands subcampaign not found.")

    print(f"Found subcampaign: {hh['name']} ({hh['id']})")
    return hh["id"], hh

def get_summary_total(subcampaign_id):
    """Get the totalContributionValue from the campaign summary endpoint."""
    try:
        resp = api_get(f"{BASE_URL}/campaigns/{subcampaign_id}")
        resp.raise_for_status()
        data = resp.json()
        summary_val = float(data.get("totalContributionValue", 0))
        print(f"Campaign summary totalContributionValue: ${summary_val:,.2f}")
        return summary_val
    except Exception as e:
        print(f"Warning: Could not fetch campaign summary: {e}")
        return 0.0

def get_all_contributions(subcampaign_id):
    """Page through all contributions for this subcampaign and sum valid ones."""
    total = 0.0
    page = 1
    included = 0
    skipped = 0
    all_statuses = {}

    while True:
        resp = api_get(
            f"{BASE_URL}/contributions",
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
            contrib_id = c.get("id", "")

            # Track all statuses
            if status not in all_statuses:
                all_statuses[status] = {"count": 0, "total": 0.0}
            all_statuses[status]["count"] += 1
            all_statuses[status]["total"] += amount

            # Look for Christy's $2,500 contribution
            if contrib_id == "6a032866bb98a3fb32a98ccc":
                print(f"  *** FOUND target contribution {contrib_id}: status={repr(status)} amount=${amount:,.2f} in_filter={status in INCLUDE_STATUSES}")

            if status in INCLUDE_STATUSES:
                total += amount
                included += 1
            else:
                skipped += 1
                print(f"  Skipped: status={status} amount=${amount:,.2f}")

        print(f"Page {page}: {len(contributions)} contributions, running total ${total:,.2f}")

        if len(contributions) < 100:
            break
        page += 1

    print(f"Done: {included} included, {skipped} skipped, total ${total:,.2f}")

    # Print all unique statuses the API returned
    print(f"=== ALL API STATUSES ===")
    for status, info in sorted(all_statuses.items()):
        in_filter = "INCLUDED" if status in INCLUDE_STATUSES else "EXCLUDED"
        print(f"  {repr(status)}: {info['count']} contributions, ${info['total']:,.2f} [{in_filter}]")
    if "6a032866bb98a3fb32a98ccc" not in str(data):
        print(f"  *** Christy's contribution (6a032866bb98a3fb32a98ccc) was NOT in any API response ***")

    # Safety guard
    if total <= 0:
        raise ValueError(f"API returned ${total} for Harvest Hands. Refusing to update.")

    return total

def format_display(dollars):
    return f"${dollars:,.2f}"

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
    subcampaign_id, subcampaign_data = get_harvest_hands_campaign_id()

    # Method 1: Paginate individual contributions and sum valid statuses
    paginated_total = get_all_contributions(subcampaign_id)

    # Method 2: Campaign summary totalContributionValue (may include APPROVED)
    summary_total = get_summary_total(subcampaign_id)

    # Use whichever is higher (summary may include APPROVED contributions
    # that the paginated endpoint doesn't return)
    if summary_total > paginated_total:
        print(f"Using SUMMARY total: ${summary_total:,.2f} (higher than paginated ${paginated_total:,.2f} by ${summary_total - paginated_total:,.2f})")
        overflow_total = summary_total
    else:
        print(f"Using PAGINATED total: ${paginated_total:,.2f} (>= summary ${summary_total:,.2f})")
        overflow_total = paginated_total

    print(f"Overflow: ${overflow_total:,.2f} + Church: ${CHURCH_CONTRIBUTION:,.2f} + Registered: ${REGISTERED_COMMITMENTS:,.2f}")
    total = overflow_total + CHURCH_CONTRIBUTION + REGISTERED_COMMITMENTS
    print(f"Combined Total: ${total:,.2f}")
    update_html(overflow_total, CHURCH_CONTRIBUTION, REGISTERED_COMMITMENTS)
