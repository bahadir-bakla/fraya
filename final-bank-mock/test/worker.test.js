import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import worker, { createWorker, SERVICES } from '../src/index.js';
import bundledFixtures from '../src/fixtures.js';

const sourceBytes = readFileSync(new URL('../../final-case-20261011/Build the Builder - Final Case/test-environment/test-customers.json', import.meta.url));
const source = JSON.parse(sourceBytes.toString('utf8'));
const spec = JSON.parse(readFileSync(new URL('../openapi.json', import.meta.url), 'utf8'));
const ada = source.customers.find(customer => customer.customerNo === '90000001');
const adaCard = '540000******1234';
const adaDay = 5;
const basePdf = { customerNo: ada.customerNo, cardNumber: adaCard, currencyType: 'TL', statementDate: '05.10.2026', emailAddress: 'ornek@freyabank.example' };

async function post(service, data, selectedWorker = createWorker({ wait: async () => {} }), extras = {}) {
  return selectedWorker.fetch(new Request('https://mock.example/voice/v1/' + service, { method: 'POST', body: JSON.stringify({ data, ...extras }) }));
}
async function assertError(response, status, code, type = 'ERROR') {
  assert.equal(response.status, status);
  const body = await response.json();
  assert.deepEqual(Object.keys(body), ['result']);
  assert.equal(body.result.returnCode, code);
  assert.equal(body.result.code, code);
  assert.equal(body.result.type, type);
  assert.equal(body.result.messageText, body.result.message);
  assert.equal(body.result.guid, body.result.details.guid);
  assert.match(body.result.guid, /^[a-f0-9]{32}$/);
}

function* requests(service) {
  for (const customer of source.customers) {
    const entry = customer.services[service];
    if (!entry) continue;
    if (['cards.list', 'contact.email.get', 'statement.pdf.send'].includes(service)) {
      const cardNumber = Object.keys(customer.services['cards.balance'] || {})[0] || adaCard;
      const balance = customer.services['cards.balance']?.[cardNumber]?.response?.data;
      const email = customer.services['contact.email.get']?.response?.data?.ibanEmail || 'synthetic@freyabank.example';
      const data = service === 'cards.list' ? { customerNo: customer.customerNo, aiFlow: 'CardOps' }
        : service === 'contact.email.get' ? { customerNo: customer.customerNo, intAddressInfoType: 'E' }
          : { customerNo: customer.customerNo, cardNumber, currencyType: 'TL', statementDate: balance?.statementDate || '05.10.2026', emailAddress: email };
      yield { customer, data, entry };
    } else {
      for (const [cardNumber, cardEntry] of Object.entries(entry)) {
        if (service === 'statement.week.decide' || service === 'statement.week.change') {
          const statementDay = customer.services['statement.week.get']?.[cardNumber]?.response?.data?.statementDay || adaDay;
          for (const [newStatementWeek, weekEntry] of Object.entries(cardEntry)) yield { customer, data: { cardNumber, newStatementWeek: Number(newStatementWeek), statementDay }, entry: weekEntry };
        } else yield { customer, data: { cardNumber }, entry: cardEntry };
      }
    }
  }
}

test('fixture snapshot exactly matches immutable source JSON', () => {
  assert.deepEqual(bundledFixtures, source);
  assert.equal(spec['x-source-fixtures-sha256'], createHash('sha256').update(sourceBytes).digest('hex'));
  assert.equal(source.customers.length, 34);
});

const expectedCounts = { 'cards.list': 34, 'cards.balance': 65, 'statement.week.get': 65, 'statement.week.decide': 195, 'statement.week.change': 195, 'contact.email.get': 34, 'statement.pdf.send': 29 };
for (const service of SERVICES) {
  test(service + ': every fixture HTTP status and complete body', async () => {
    let count = 0;
    for (const { customer, data, entry } of requests(service)) {
      const delays = [];
      const selectedWorker = createWorker({ wait: async milliseconds => { delays.push(milliseconds); } });
      const response = await post(service, data, selectedWorker, { call: { ani: 'ignored', lang: 'tr' } });
      const context = service + ' customer=' + customer.customerNo + ' data=' + JSON.stringify(data);
      assert.equal(response.status, entry.http, context);
      assert.deepEqual(await response.json(), entry.response, context);
      assert.deepEqual(delays, entry.delaySeconds ? [entry.delaySeconds * 1000] : [], context);
      assert.match(response.headers.get('content-type'), /application\/json.*charset=utf-8/);
      count++;
    }
    assert.equal(count, expectedCounts[service]);
  });
}

test('customer and requested-week string/number variants select identical fixtures', async () => {
  for (const service of SERVICES) {
    for (const { data, entry } of requests(service)) {
      if ('customerNo' in data) data.customerNo = Number(data.customerNo);
      else if ('newStatementWeek' in data) data.newStatementWeek = String(data.newStatementWeek);
      else continue;
      const response = await post(service, data);
      assert.equal(response.status, entry.http);
      assert.deepEqual(await response.json(), entry.response);
    }
  }
});

test('every absent required field and empty value returns the contract 400 envelope', async () => {
  for (const service of SERVICES) {
    const data = requests(service).next().value.data;
    const fields = Object.keys(data).filter(key => key !== 'aiFlow');
    for (const field of fields) {
      for (const value of [undefined, null, '', '  ']) {
        const malformed = { ...data, [field]: value };
        await assertError(await post(service, malformed), 400, 'INVALID_ARGUMENTS_ERROR');
      }
    }
  }
});

test('unknown customer/card/no-entry follows each service contract', async () => {
  for (const [service, data, code, status] of [
    ['cards.list', { customerNo: '99999999' }, 'FB_IVR_CHANNEL_102', 404],
    ['cards.balance', { cardNumber: '540000******9999' }, 'FB_IVR_CHANNEL_120', 404],
    ['statement.week.get', { cardNumber: '540000******9999' }, 'FB_IVR_CHANNEL_121', 404],
    ['statement.week.decide', { cardNumber: '540000******9999', newStatementWeek: 2, statementDay: 5 }, 'INVALID_ARGUMENTS_ERROR', 400],
    ['statement.week.change', { cardNumber: '540000******9999', newStatementWeek: 2, statementDay: 5 }, 'INVALID_ARGUMENTS_ERROR', 400],
    ['contact.email.get', { customerNo: '99999999', intAddressInfoType: 'E' }, 'INVALID_ARGUMENTS_ERROR', 400],
    ['statement.pdf.send', { ...basePdf, customerNo: '99999999' }, 'FB_IVR_CHANNEL_107', 404],
    ['statement.pdf.send', { ...basePdf, customerNo: '94907600' }, 'FB_IVR_CHANNEL_107', 404]
  ]) await assertError(await post(service, data), status, code, status === 404 ? 'WARNING' : 'ERROR');
});

test('all current-week requests have no fixture and return 400', async () => {
  for (const customer of source.customers) {
    for (const [cardNumber, entry] of Object.entries(customer.services['statement.week.get'] || {})) {
      if (entry.http !== 200) continue;
      for (const service of ['statement.week.decide', 'statement.week.change']) {
        await assertError(await post(service, { cardNumber, newStatementWeek: entry.response.data.statementWeek, statementDay: entry.response.data.statementDay }), 400, 'INVALID_ARGUMENTS_ERROR');
      }
    }
  }
});

test('mutation validation rejects invalid weeks, days, PDF currencies and dates', async () => {
  for (const service of ['statement.week.decide', 'statement.week.change']) {
    for (const newStatementWeek of [0, 5, 1.5, true, [], {}, '02', '2.0', '__proto__']) await assertError(await post(service, { cardNumber: adaCard, statementDay: 5, newStatementWeek }), 400, 'INVALID_ARGUMENTS_ERROR');
    for (const statementDay of [0, 32, 2.5, true, '5', [], {}]) await assertError(await post(service, { cardNumber: adaCard, newStatementWeek: 2, statementDay }), 400, 'INVALID_ARGUMENTS_ERROR');
  }
  for (const currencyType of ['TRY', 'tl', 'JPY', 1, {}]) await assertError(await post('statement.pdf.send', { ...basePdf, currencyType }), 400, 'INVALID_ARGUMENTS_ERROR');
  for (const statementDate of ['2026-10-05', '31.02.2026', '29.02.2026', '00.10.2026', '05.13.2026', '01.01.0000']) await assertError(await post('statement.pdf.send', { ...basePdf, statementDate }), 400, 'INVALID_ARGUMENTS_ERROR');
});

test('PDF fixture lookup remains customer-only; all currencies and arbitrary addresses follow contract', async () => {
  for (const currencyType of ['TL', 'USD', 'EUR', 'GBP']) {
    const response = await post('statement.pdf.send', { ...basePdf, currencyType, cardNumber: 'not-a-fixture-card', statementDate: '29.02.2028', emailAddress: 'other@synthetic.example' });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), ada.services['statement.pdf.send'].response);
  }
});

test('no currency block, amount, product, card mask or error is synthesized', async () => {
  for (const { data, entry } of requests('cards.balance')) {
    const body = await (await post('cards.balance', data)).json();
    assert.deepEqual(body, entry.response);
    if (entry.http === 200 && !('debtGBP' in entry.response.data)) assert.equal('debtGBP' in body.data, false);
  }
  const cards = await (await post('cards.list', { customerNo: '92030487' })).json();
  const sameLastFour = cards.data.cards.filter(card => card.cardNumberLast4 === '4253');
  assert.equal(sameLastFour.length, 2);
  assert.notEqual(sameLastFour[0].cardNumber, sameLastFour[1].cardNumber);
  await assertError(await post('cards.balance', { cardNumber: '5400********1234' }), 404, 'FB_IVR_CHANNEL_120', 'WARNING');
  await assertError(await post('cards.balance', { cardNumber: '1234' }), 404, 'FB_IVR_CHANNEL_120', 'WARNING');
});

test('metadata, token/header absence, aiFlow and supplied now do not change exact fixtures', async () => {
  for (const now of ['2026-10-12T10:30:00+03:00', '2040-01-01T00:00:00+03:00']) {
    const response = await post('cards.list', { customerNo: ada.customerNo, aiFlow: 'ignored', now }, undefined, { now, call: { customerNumber: 'different', now, lang: 'en' } });
    assert.deepEqual(await response.json(), ada.services['cards.list'].response);
  }
  for (const intAddressInfoType of ['E', 'P', 'B', 'nonempty']) {
    assert.deepEqual(await (await post('contact.email.get', { customerNo: ada.customerNo, intAddressInfoType })).json(), ada.services['contact.email.get'].response);
  }
});

test('repeated mutation, preview, and linked-card reads remain immutable exact fixtures', async () => {
  const original = JSON.stringify(bundledFixtures);
  const selectedWorker = createWorker({ wait: async () => {} });
  const customer = source.customers.find(c => c.customerNo === '92220795');
  const [main, linked] = Object.keys(customer.services['statement.week.get']);
  const day = customer.services['statement.week.get'][main].response.data.statementDay;
  const newStatementWeek = Number(Object.keys(customer.services['statement.week.change'][main])[0]);
  for (const service of ['statement.week.decide', 'statement.week.change', 'statement.week.change']) {
    const response = await post(service, { cardNumber: main, statementDay: day, newStatementWeek }, selectedWorker);
    assert.deepEqual(await response.json(), customer.services[service][main][newStatementWeek].response);
  }
  for (const cardNumber of [main, linked]) {
    assert.deepEqual(await (await post('statement.week.get', { cardNumber }, selectedWorker)).json(), customer.services['statement.week.get'][cardNumber].response);
  }
  assert.equal(JSON.stringify(bundledFixtures), original);
});

test('malformed JSON/envelopes and unknown templates produce errors without invented data', async () => {
  for (const body of ['{', 'null', '[]', '{}', '{"data":[]}', '{"data":null}']) {
    const response = await worker.fetch(new Request('https://mock.example/voice/v1/cards.list', { method: 'POST', body }));
    await assertError(response, 400, 'INVALID_ARGUMENTS_ERROR');
  }
  await assertError(await post('cards.list', { customerNo: '{{customerNumber}}' }), 400, 'INVALID_ARGUMENTS_ERROR');
  await assertError(await post('cards.balance', { cardNumber: '__proto__' }), 404, 'FB_IVR_CHANNEL_120', 'WARNING');
});

test('health, method enforcement, path enforcement, CORS and optional mock token', async () => {
  assert.deepEqual(await (await worker.fetch(new Request('https://mock.example/health'))).json(), { ok: true, customers: 34, services: 7 });
  await assertError(await worker.fetch(new Request('https://mock.example/voice/v1/cards.list')), 405, 'METHOD_NOT_ALLOWED');
  await assertError(await worker.fetch(new Request('https://mock.example/cards.list', { method: 'POST', body: '{}' })), 404, 'NOT_FOUND');
  const options = await worker.fetch(new Request('https://mock.example/voice/v1/cards.list', { method: 'OPTIONS' }));
  assert.equal(options.status, 204);
  const token = await worker.fetch(new Request('https://mock.example/oauth2/token', { method: 'POST' }));
  assert.deepEqual(await token.json(), { access_token: 'freya-bank-test-token', token_type: 'Bearer', expires_in: 1800 });
});

test('OpenAPI exposes exactly seven POST paths, resolved schemas and placeholder origin', () => {
  assert.equal(spec.openapi, '3.0.3');
  assert.deepEqual(spec.servers.map(server => server.url), ['https://final-bank-mock.invalid']);
  assert.deepEqual(Object.keys(spec.paths).sort(), SERVICES.map(service => '/voice/v1/' + service).sort());
  function checkRefs(value) {
    if (!value || typeof value !== 'object') return;
    if (value.$ref) assert.ok(spec.components.schemas[value.$ref.split('/').at(-1)], value.$ref);
    for (const child of Object.values(value)) checkRefs(child);
  }
  checkRefs(spec);
  for (const [path, operations] of Object.entries(spec.paths)) {
    assert.deepEqual(Object.keys(operations), ['post']);
    const schema = spec.components.schemas[operations.post.requestBody.content['application/json'].schema.$ref.split('/').at(-1)];
    assert.deepEqual(schema.required, ['data']);
    assert.ok(operations.post.responses['200']);
    assert.ok(operations.post.responses['400']);
    assert.ok(operations.post.responses['500']);
    assert.equal(operations.post['x-bank-service'], path.split('/').at(-1));
  }
  assert.equal(spec.components.schemas.WeekChangeData.properties.statementWeek.type, 'string');
  assert.equal(spec.components.schemas.WeekChangeData.properties.statementDay.type, 'string');
  assert.equal(spec.components.schemas.BalanceData.required.includes('debtGBP'), false);
});

test('OpenAPI request examples and every fixture response conform to their published schemas', () => {
  function validate(value, schema, context) {
    if (schema.$ref) return validate(value, spec.components.schemas[schema.$ref.split('/').at(-1)], context);
    if (value === null && schema.nullable) return;
    if (schema.oneOf) {
      const passing = schema.oneOf.filter(option => { try { validate(value, option, context); return true; } catch { return false; } });
      assert.equal(passing.length, 1, context + ': oneOf');
      return;
    }
    if (schema.type === 'object') {
      assert.ok(value !== null && typeof value === 'object' && !Array.isArray(value), context);
      for (const field of schema.required || []) assert.ok(field in value, context + ': missing ' + field);
      for (const [field, child] of Object.entries(value)) {
        if (schema.properties[field]) validate(child, schema.properties[field], context + '.' + field);
        else if (schema.additionalProperties === false) assert.fail(context + ': unexpected ' + field);
      }
    } else if (schema.type === 'array') {
      assert.ok(Array.isArray(value), context);
      for (const child of value) validate(child, schema.items, context + '[]');
    } else if (schema.type === 'integer') assert.ok(Number.isInteger(value), context);
    else if (schema.type) assert.equal(typeof value, schema.type, context);
    if (schema.enum) assert.ok(schema.enum.includes(value), context + ': enum');
    if (schema.pattern) assert.match(value, new RegExp(schema.pattern), context);
    if (schema.minimum !== undefined) assert.ok(value >= schema.minimum, context);
    if (schema.maximum !== undefined) assert.ok(value <= schema.maximum, context);
    if (schema.minLength !== undefined) assert.ok(value.length >= schema.minLength, context);
  }
  for (const service of SERVICES) {
    const operation = spec.paths['/voice/v1/' + service].post;
    const request = operation.requestBody.content['application/json'];
    validate(request.example, request.schema, service + ' request example');
    for (const { entry } of requests(service)) validate(entry.response, operation.responses[entry.http].content['application/json'].schema, service + ' response');
  }
});

test('real production waiter delays the specified balance at least 12 seconds', { timeout: 20000 }, async () => {
  const customer = source.customers.find(c => c.customerNo === '94907600');
  const cardNumber = '540000******7211';
  const start = performance.now();
  const response = await post('cards.balance', { cardNumber }, worker);
  assert.ok(performance.now() - start >= 11900, 'response arrived before the fixture delay');
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), customer.services['cards.balance'][cardNumber].response);
});
