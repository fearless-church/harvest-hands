# Harvest Hands: Project Memory

## What this is
Harvest Hands is the Fearless building campaign site at harvesthands.fearless.church.
It is a static HTML site. The main page is index.html. A real time stage display
(live.html) shows giving data during services.

## Source of truth rule (read this before trusting anything below)
The deployed files in this repo are the source of truth for all current numbers,
widget labels, copy, and which sections exist. This file deliberately does NOT list
live dollar amounts, because they change every cycle. If you need a current value,
read it from index.html or the automation output. Never repeat a specific dollar
figure from prose or from older notes without confirming it against the file first.

## Repository and hosting
- Repo: fearless-church/harvest-hands (public)
- Host: Netlify
- Deploy: Netlify CLI deploy, run from a GitHub Actions workflow. Netlify auto builds
  are OFF on purpose to save credits. The ONLY path to production is the workflow.
- Schedule: a GitHub Actions cron runs every 30 minutes to refresh giving data and deploy.
- Key files (confirm exact paths with a directory listing before editing):
  - index.html ............... main campaign page
  - live.html ................ real time stage display, polls every 10s during services
  - netlify/functions/giving.js  CORS safe proxy that feeds giving data to live.html
  - update_giving.py ......... fetches Overflow totals and writes them into the site
  - .github/workflows/update_giving.yml  the scheduled fetch and deploy workflow

## Overflow API rules (hard won, do not deviate)
- The /contributions endpoint requires the param `subcampaignId`. Using `campaignId`
  silently returns $0.
- Never use the campaign summary field `totalContributionValue`. It excludes
  "Processing" transactions and will undercount.
- Always paginate individual contributions: `limit` 100, increment `page` until
  `page * 100 >= totalCount`.
- The status filter must include ALL of: CONFIRMED, PAID_OUT, PROCESSING, PENDING,
  APPROVED. APPROVED is undocumented but real; it captures recent card and Apple Pay
  transactions still in transition.
- Auth requires BOTH headers: `x-client-id` and `x-api-key`.
- Contribution amounts come back in dollars, not cents.
- Safety guard: NEVER write or commit a $0 total to the site. Treat a $0 result as a
  fetch failure and abort the update.

## Secrets
- OVERFLOW_CLIENT_ID and OVERFLOW_API_KEY are stored in GitHub Actions secrets and in
  Netlify environment variables.
- Never print, log, echo, or commit these values. Use the existing env wiring only.

## How to deploy from Claude Code
- Edit files directly in the repo, then commit and push.
- A plain push does NOT deploy, because Netlify auto build is off. Production updates
  go through the Actions workflow (the scheduled run, or a manual dispatch if one is
  defined, e.g. `gh workflow run update_giving.yml`).
- Before committing, diff against the prior version and confirm ONLY intended lines
  changed. Verify the current file state instead of assuming it.
- The money and widget rendering in index.html is the most fragile part of the site.
  Do not change displayed numbers or how they are calculated unless that is the
  explicit task.

## Brand and copy conventions
- Use "Fearless" or "Fearless LA" in new marketing copy. Avoid "Fearless Church" and
  "Fearless Church LA" unless there is a strong reason (legal text, brand lockup, or
  checks payable). The live site still uses "Fearless Church" in legal and payment
  spots; leave those as they are unless asked.

## Collaborators
- Clayton: creative director and GitHub collaborator. Handles design and manual
  content updates.
