import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
import { performance } from 'node:perf_hooks';

const origin = process.argv[2];
if (!origin || !/^https?:\/\//.test(origin)) throw new Error('Usage: node scripts/verify-http.mjs https://<actual-worker-origin>');
const source = JSON.parse(readFileSync(new URL('../../final-case-20261011/Build the Builder - Final Case/test-environment/test-customers.json', import.meta.url), 'utf8'));
const health = await fetch(new URL('/health', origin), { signal: AbortSignal.timeout(30000) });
assert.equal(health.status, 200);
assert.equal((await health.json()).ok, true);
let checked = 0;
let errors = 0;
let delayed = 0;
async function verify(service, data, entry) {
  const started = performance.now();
  const response = await fetch(new URL('/voice/v1/' + service, origin), { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ data, call: { lang: 'tr' } }), signal: AbortSignal.timeout(30000) });
  const elapsed = performance.now() - started;
  assert.equal(response.status, entry.http, service + ': ' + JSON.stringify(data));
  assert.deepEqual(await response.json(), entry.response, service + ': ' + JSON.stringify(data));
  if (entry.delaySeconds) { assert.ok(elapsed >= entry.delaySeconds * 1000 - 100, 'fixture delay missing'); delayed++; }
  if (entry.http !== 200) errors++;
  checked++;
}
for (const customer of source.customers) {
  for (const [service, entry] of Object.entries(customer.services)) {
    if (Number.isInteger(entry.http)) {
      const cardNumber = Object.keys(customer.services['cards.balance'] || {})[0] || '540000******1234';
      const balance = customer.services['cards.balance']?.[cardNumber]?.response?.data;
      const email = customer.services['contact.email.get']?.response?.data?.ibanEmail || 'synthetic@freyabank.example';
      const data = service === 'cards.list' ? { customerNo: customer.customerNo, aiFlow: 'CardOps' } : service === 'contact.email.get' ? { customerNo: customer.customerNo, intAddressInfoType: 'E' } : { customerNo: customer.customerNo, cardNumber, currencyType: 'TL', statementDate: balance?.statementDate || '05.10.2026', emailAddress: email };
      await verify(service, data, entry);
    } else {
      for (const [cardNumber, cardEntry] of Object.entries(entry)) {
        if (Number.isInteger(cardEntry.http)) await verify(service, { cardNumber }, cardEntry);
        else {
          const statementDay = customer.services['statement.week.get']?.[cardNumber]?.response?.data?.statementDay || 5;
          for (const [week, answer] of Object.entries(cardEntry)) await verify(service, { cardNumber, newStatementWeek: Number(week), statementDay }, answer);
        }
      }
    }
  }
}
console.log(JSON.stringify({ origin, checked, fixtureErrors: errors, delayedResponses: delayed, ok: true }));
