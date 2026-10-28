import os
import json
import re
import time
import requests
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

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

# NOTE: Pledges/registered commitments are intentionally NOT part of the
# displayed number anymore (the site shows Received only). If pledges ever need
# to be shown again, reintroduce a constant and add it back in update_html().

# Statuses to include in the total
INCLUDE_STATUSES = {"CONFIRMED", "PAID_OUT", "PROCESSING", "PENDING", "APPROVED"}

# Shared with the live display. Entries are confirmed net deposits keyed by
# Overflow transaction ID, never blanket additions to the campaign total.
VERIFIED_RECEIPTS = json.loads(
    (Path(__file__).parent / "netlify/lib/verified-receipts.json").read_text()
)
REVERSED_STATUSES = {"FAILED", "REFUNDED", "CHARGEBACK", "CANCELLED", "CANCELED"}

def contribution_cents(contribution):
    status = contribution.get("status", "")
    receipt = VERIFIED_RECEIPTS.get(contribution.get("id"))
    if receipt is not None:
        if status in REVERSED_STATUSES:
            return 0
        if contribution.get("type") != receipt["type"]:
            raise ValueError("Verified receipt type changed; reconciliation required.")
        if status not in INCLUDE_STATUSES | {"CONTRIBUTION_RECEIVED"}:
            raise ValueError("Verified receipt status changed; reconciliation required.")
        return receipt["receivedCents"]
    if status not in INCLUDE_STATUSES:
        return 0
    amount = Decimal(str(contribution["amount"]))
    if not amount.is_finite() or amount < 0:
        raise ValueError("Invalid contribution amount.")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

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

def get_all_contributions(subcampaign_id):
    """Sum unique transactions, substituting verified net deposits by ID."""
    total_cents = 0
    page = 1
    seen = {}
    while True:
        resp = api_get(
            f"{BASE_URL}/contributions",
            params={"subcampaignId": subcampaign_id, "limit": 100, "page": page}
        )
        resp.raise_for_status()
        contributions = resp.json().get("data")
        if not isinstance(contributions, list):
            raise ValueError("Invalid contributions response; refusing to update.")
        for contribution in contributions:
            contribution_id = contribution.get("id")
            if not contribution_id:
                raise ValueError("Missing transaction ID; cannot prevent duplicate counting.")
            fingerprint = (contribution.get("status"), contribution.get("amount"), contribution.get("type"))
            if contribution_id in seen:
                if seen[contribution_id] != fingerprint:
                    raise ValueError("Transaction changed during pagination; retry a fresh snapshot.")
                continue
            seen[contribution_id] = fingerprint
            cents = contribution_cents(contribution)
            total_cents += cents
            if contribution_id in VERIFIED_RECEIPTS:
                print(f"Verified receipt counted: ${cents / 100:,.2f}; status={contribution.get('status')}")
        print(f"Page {page}: {len(contributions)} records, running total ${total_cents / 100:,.2f}")
        # Overflow totalCount can exclude failed records that are still returned.
        # Continue through the actual final page rather than stopping at totalCount.
        if len(contributions) < 100:
            break
        page += 1
    if total_cents <= 0:
        raise ValueError("API returned no positive total. Refusing to update.")
    return total_cents / 100

def format_display(dollars):
    return f"${dollars:,.2f}"

def update_html(overflow_dollars, church_dollars):
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()

    # Received = Overflow (auto-calculated) + Church (actual money in hand).
    # This is the ONLY figure the site displays. Pledges are intentionally not
    # shown — a note on the page explains the number rises as pledges arrive.
    received_total = overflow_dollars + church_dollars

    # Update timestamp
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    html = re.sub(
        r'<!-- GIVING_LAST_UPDATED:.*?-->',
        f'<!-- GIVING_LAST_UPDATED: {now} -->',
        html
    )

    # The page's progress renderer (in index.html) reads data-received on
    # .hh-thermo and paints the bar, label, and floating widget from it.
    # data-received carries cents; data-raised is the same Received amount as a
    # whole number so progress.html's integer regex keeps matching.
    html = re.sub(r'data-received="[\d.]+"', f'data-received="{received_total:.2f}"', html)
    html = re.sub(r'data-raised="[\d.]+"', f'data-raised="{received_total:.0f}"', html)

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("index.html updated:")
    print(f"  Received (shown): ${received_total:,.2f} (Overflow ${overflow_dollars:,.2f} + Church ${church_dollars:,.2f})")

if __name__ == "__main__":
    subcampaign_id, subcampaign_data = get_harvest_hands_campaign_id()

    # Only reconciled individual transactions can determine the displayed total.
    # An aggregate campaign summary cannot preserve receipt-specific net values.
    overflow_total = get_all_contributions(subcampaign_id)

    received = overflow_total + CHURCH_CONTRIBUTION
    print(f"Received (shown on site): ${received:,.2f} (Overflow ${overflow_total:,.2f} + Church ${CHURCH_CONTRIBUTION:,.2f})")
    update_html(overflow_total, CHURCH_CONTRIBUTION)
