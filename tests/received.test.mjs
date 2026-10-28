import test from 'node:test';
import assert from 'node:assert/strict';
import { contributionCents } from '../netlify/lib/contribution-amount.mjs';
import handler from '../netlify/functions/giving.js';

const id = '6ac9402b7845f45a9ae9d1e8';
const stock = (status='CONTRIBUTION_RECEIVED', changes={}) => ({id, type:'STOCK', status, amount:96897.72, ...changes});
const cash = (id='cash', amount=100) => ({id, type:'CASH', status:'PAID_OUT', amount});
const included = ['CONFIRMED','PAID_OUT','PROCESSING','PENDING','APPROVED'];

test('verified net amount persists across included status transitions', () => {
  for (const status of [...included, 'CONTRIBUTION_RECEIVED']) assert.equal(contributionCents(stock(status)),9399079);
});
test('reported amount changes never override confirmed net receipt', () => {
  for (const amount of [96897.72,93990.79,100000]) assert.equal(contributionCents(stock(undefined,{amount})),9399079);
});
test('reversed gifts are excluded', () => {
  for (const status of ['FAILED','REFUNDED','CHARGEBACK','CANCELLED','CANCELED']) assert.equal(contributionCents(stock(status)),0);
});
test('unexpected type or status requires reconciliation', () => {
  assert.throws(()=>contributionCents(stock('UNRECOGNIZED')));
  assert.throws(()=>contributionCents(stock(undefined,{type:'CASH'})));
});
test('another stock gift does not inherit the override', () => {
  assert.equal(contributionCents(stock(undefined,{id:'another'})),0);
  assert.equal(contributionCents(stock('PAID_OUT',{id:'another'})),9689772);
});
test('normal cash and cents retain existing behavior', () => {
  for (const status of included) assert.equal(contributionCents({...cash('a',10.29),status}),1029);
});

async function invoke(pages) {
  const originalFetch=globalThis.fetch;
  const originalNetlify=globalThis.Netlify;
  globalThis.Netlify={env:{get:()=> 'test'}};
  globalThis.fetch=async url=> {
    const u=new URL(url);
    if (u.pathname.endsWith('/campaigns')) return Response.json({data:[{id:'campaign',name:u.searchParams.get('isSubcampaign')==='true'?'Harvest Hands':'Los Angeles'}]});
    const page=Number(u.searchParams.get('page'));
    assert.equal(u.searchParams.get('subcampaignId'),'campaign');
    assert.equal(u.searchParams.get('limit'),'100');
    const body=pages[page-1];
    return body instanceof Response ? body : Response.json(body);
  };
  try { const r=await handler(new Request('https://example.com'),{}); return {status:r.status,body:await r.json()}; }
  finally { globalThis.fetch=originalFetch;globalThis.Netlify=originalNetlify; }
}
test('stage display matches corrected site total and deduplicates stock', async()=> {
  const r=await invoke([{data:[cash('a',608606.13),stock(),stock()]}]);
  assert.equal(r.status,200);
  assert.equal(r.body.overflow,702596.92);
  assert.equal(r.body.church,141276.92);
  assert.equal(r.body.total,843873.84);
});
test('missing stock record never causes a blanket addition',async()=> {
  const r=await invoke([{data:[cash()]}]);assert.equal(r.body.total,141376.92);
});
test('paginate past inaccurate totalCount and ignore repeat IDs across pages',async()=> {
  const first=Array.from({length:100},(_,i)=>cash(String(i),1));
  const r=await invoke([{data:first,totalCount:1},{data:[stock(),first[0]],totalCount:1}]);
  assert.equal(r.body.total,235367.71);
});
test('conflicting duplicate, empty response, and failed API never publish a partial total', async()=> {
  for (const pages of [
    [{data:[stock(),stock('PAID_OUT')]}],
    [{data:[]}],
    [{}],
    [new Response('Forbidden',{status:403})],
    [{data:[{...cash(),id:''}]}]
  ]) {
    const r=await invoke(pages);assert.equal(r.status,500);assert.equal(r.body.total,undefined);
  }
});
