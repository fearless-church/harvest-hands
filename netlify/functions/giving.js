export default async (request, context) => {
  const CLIENT_ID = Netlify.env.get("OVERFLOW_CLIENT_ID");
  const API_KEY = Netlify.env.get("OVERFLOW_API_KEY");
  const BASE = "https://server.overflow.co/api/v3";
  const CHURCH_CONTRIBUTION = 141276.92;
  const INCLUDE = new Set(["CONFIRMED", "PAID_OUT", "PROCESSING", "PENDING"]);

  try {
    const headers = { "x-client-id": CLIENT_ID, "x-api-key": API_KEY };

    // Find LA campaign
    const campResp = await fetch(`${BASE}/campaigns?isSubcampaign=false&limit=100`, { headers });
    const camps = (await campResp.json()).data || [];
    const la = camps.find(c => c.name.toLowerCase().includes("los angeles"));
    if (!la) return Response.json({ error: "LA campaign not found" }, { status: 500 });

    // Find Harvest Hands subcampaign
    const subResp = await fetch(`${BASE}/campaigns?isSubcampaign=true&parentCampaignId=${la.id}&limit=100`, { headers });
    const subs = (await subResp.json()).data || [];
    const hh = subs.find(c => c.name.toLowerCase().includes("harvest hands"));
    if (!hh) return Response.json({ error: "Harvest Hands not found" }, { status: 500 });

    // Sum all valid contributions
    let total = 0;
    let page = 1;
    while (true) {
      const cResp = await fetch(`${BASE}/contributions?subcampaignId=${hh.id}&limit=100&page=${page}`, { headers });
      const cData = await cResp.json();
      const contribs = cData.data || [];
      if (!contribs.length) break;

      for (const c of contribs) {
        if (INCLUDE.has(c.status)) total += parseFloat(c.amount || 0);
      }

      if (page * 100 >= (cData.totalCount || 0)) break;
      page++;
    }

    const grandTotal = total + CHURCH_CONTRIBUTION;

    return Response.json({
      overflow: Math.round(total * 100) / 100,
      church: CHURCH_CONTRIBUTION,
      total: Math.round(grandTotal * 100) / 100,
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
