import { contributionCents } from '../lib/contribution-amount.mjs';

export default async (request, context) => {
  const CLIENT_ID = Netlify.env.get("OVERFLOW_CLIENT_ID");
  const API_KEY = Netlify.env.get("OVERFLOW_API_KEY");
  const BASE = "https://server.overflow.co/api/v3";
  const CHURCH_CONTRIBUTION = 141276.92;
  // Pledges/registered commitments are intentionally NOT included — the live
  // display shows Received only (Overflow + Church), matching the website.

  try {
    const headers = { "x-client-id": CLIENT_ID, "x-api-key": API_KEY };

    const campResp = await fetch(`${BASE}/campaigns?isSubcampaign=false&limit=100`, { headers });
    if (!campResp.ok) throw new Error(`Overflow campaign request failed: ${campResp.status}`);
    const camps = (await campResp.json()).data || [];
    const la = camps.find(c => c.name.toLowerCase().includes("los angeles"));
    if (!la) return Response.json({ error: "LA campaign not found" }, { status: 500 });

    const subResp = await fetch(`${BASE}/campaigns?isSubcampaign=true&parentCampaignId=${la.id}&limit=100`, { headers });
    if (!subResp.ok) throw new Error(`Overflow subcampaign request failed: ${subResp.status}`);
    const subs = (await subResp.json()).data || [];
    const hh = subs.find(c => c.name.toLowerCase().includes("harvest hands"));
    if (!hh) return Response.json({ error: "Harvest Hands not found" }, { status: 500 });

    let totalCents = 0;
    const seen = new Map();
    let page = 1;
    while (true) {
      const cResp = await fetch(`${BASE}/contributions?subcampaignId=${hh.id}&limit=100&page=${page}`, { headers });
      if (!cResp.ok) throw new Error(`Overflow contributions request failed: ${cResp.status}`);
      const cData = await cResp.json();
      const contribs = cData.data;
      if (!Array.isArray(contribs)) throw new Error("Invalid contributions response.");
      if (!contribs.length) break;

      for (const c of contribs) {
        if (!c.id) throw new Error('Missing transaction ID; cannot prevent duplicate counting.');
        const fingerprint = JSON.stringify([c.status, c.amount, c.type]);
        if (seen.has(c.id)) {
          if (seen.get(c.id) !== fingerprint) throw new Error('Transaction changed during pagination; retry a fresh snapshot.');
          continue;
        }
        seen.set(c.id, fingerprint);
        totalCents += contributionCents(c);
      }

      if (contribs.length < 100) break;
      page++;
    }

    if (totalCents <= 0) throw new Error('API returned no positive total. Refusing to publish.');
    const total = totalCents / 100;
    const received = (totalCents + Math.round(CHURCH_CONTRIBUTION * 100)) / 100;

    return Response.json({
      overflow: Math.round(total * 100) / 100,
      church: CHURCH_CONTRIBUTION,
      total: Math.round(received * 100) / 100,
      phase1Goal: 1500000,
      phase2Goal: 3000000,
      timestamp: new Date().toISOString()
    }, {
      headers: { "Cache-Control": "no-cache, no-store" }
    });

  } catch (err) {
    return Response.json({ error: err.message }, { status: 500 });
  }
};
