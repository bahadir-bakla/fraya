import fixtures from './fixtures.js';

export const SERVICES = Object.freeze([
  'cards.list', 'cards.balance', 'statement.week.get', 'statement.week.decide',
  'statement.week.change', 'contact.email.get', 'statement.pdf.send'
]);
const customerServices = new Set(['cards.list', 'contact.email.get', 'statement.pdf.send']);
const weekServices = new Set(['statement.week.decide', 'statement.week.change']);
const requiredFields = {
  'cards.list': ['customerNo'],
  'cards.balance': ['cardNumber'],
  'statement.week.get': ['cardNumber'],
  'statement.week.decide': ['cardNumber', 'newStatementWeek', 'statementDay'],
  'statement.week.change': ['cardNumber', 'newStatementWeek', 'statementDay'],
  'contact.email.get': ['customerNo', 'intAddressInfoType'],
  'statement.pdf.send': ['customerNo', 'cardNumber', 'currencyType', 'statementDate', 'emailAddress']
};
const customers = new Map(fixtures.customers.map(customer => [String(customer.customerNo), customer]));
const cardServices = new Map(SERVICES.filter(service => !customerServices.has(service)).map(service => [service, new Map()]));
for (const customer of fixtures.customers) {
  for (const [service, index] of cardServices) {
    for (const [card, answer] of Object.entries(customer.services[service] || {})) {
      if (index.has(card)) throw new Error('Duplicate fixture card for ' + service + ': ' + card);
      index.set(card, answer);
    }
  }
}

const headers = {
  'content-type': 'application/json; charset=utf-8',
  'cache-control': 'no-store',
  'access-control-allow-origin': '*'
};
const json = (body, status = 200, extraHeaders = {}) => new Response(JSON.stringify(body), { status, headers: { ...headers, ...extraHeaders } });
const sleep = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds));
const empty = value => value === undefined || value === null || (typeof value === 'string' && value.trim() === '');
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);

function error(status, code, message, type = 'ERROR') {
  // Generated errors are deterministic; all fixture trace ids remain untouched.
  const guid = 'f0e1d2c3b4a5968778695a4b3c2dffff';
  return json({ result: {
    guid, returnCode: code, messageText: message, code, message, type,
    details: {
      guid,
      rootCause: type === 'WARNING' ? 'com.freyabank.ivrgateway.ivrchannel.rest.exception.NotFoundException' : 'IllegalArgumentException',
      errorOrigin: 'ivr-gateway-test:ivr-channel-v0'
    }
  } }, status);
}
const invalid = message => error(400, 'INVALID_ARGUMENTS_ERROR', message);
function notFound(service) {
  const definitions = {
    'cards.list': ['FB_IVR_CHANNEL_102', 'Müşteriye ait geçerli kart bilgisi bulunamadı.'],
    'cards.balance': ['FB_IVR_CHANNEL_120', 'Kart bakiye servisi hatası: kart bulunamadı'],
    'statement.week.get': ['FB_IVR_CHANNEL_121', 'Kart ekstre haftası servisi hatası: kart bulunamadı'],
    'statement.pdf.send': ['FB_IVR_CHANNEL_107', 'Pdf dokümanı bulunamadı']
  };
  const definition = definitions[service];
  return definition ? error(404, definition[0], definition[1], 'WARNING') : invalid('No test fixture for the requested customer, card or statement week');
}

function validDate(value) {
  if (typeof value !== 'string' || !/^\d{2}\.\d{2}\.\d{4}$/.test(value)) return false;
  const [day, month, year] = value.split('.').map(Number);
  if (year < 1 || month < 1 || month > 12 || day < 1) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  return day <= [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
}

function validate(service, data) {
  for (const field of requiredFields[service]) {
    if (empty(data[field])) return invalid(field === 'cardNumber' ? 'card number cannot be empty' : field + ' cannot be empty');
  }
  if ('customerNo' in data && customerServices.has(service)) {
    if (!['string', 'number'].includes(typeof data.customerNo) || !/^\d{8}$/.test(String(data.customerNo))) return invalid('customerNo must be an 8-digit string or number');
  }
  if ('cardNumber' in data && requiredFields[service].includes('cardNumber') && typeof data.cardNumber !== 'string') return invalid('cardNumber must be a string');
  if (weekServices.has(service)) {
    if (!['string', 'number'].includes(typeof data.newStatementWeek) || !/^[1-4]$/.test(String(data.newStatementWeek))) return invalid('newStatementWeek must be 1, 2, 3 or 4');
    if (!Number.isInteger(data.statementDay) || data.statementDay < 1 || data.statementDay > 31) return invalid('statementDay must be an integer from 1 to 31');
  }
  if (service === 'contact.email.get' && typeof data.intAddressInfoType !== 'string') return invalid('intAddressInfoType must be a string');
  if (service === 'statement.pdf.send') {
    if (!['TL', 'USD', 'EUR', 'GBP'].includes(data.currencyType)) return invalid('currencyType must be TL, USD, EUR or GBP');
    if (!validDate(data.statementDate)) return invalid('statementDate must be a valid dd.MM.yyyy date');
    if (typeof data.emailAddress !== 'string') return invalid('emailAddress must be a string');
    // Test lookup is only by customerNo. Do not add registered-address, card
    // ownership, or date-equality rules that the integration contract lacks.
  }
  return null;
}

export function createWorker({ wait = sleep } = {}) {
  return {
    async fetch(request) {
      const path = new URL(request.url).pathname;
      if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: { 'access-control-allow-origin': '*', 'access-control-allow-methods': 'GET, POST, OPTIONS', 'access-control-allow-headers': '*' } });
      if (path === '/health' && request.method === 'GET') return json({ ok: true, customers: customers.size, services: SERVICES.length });
      if (path === '/oauth2/token' && request.method === 'POST') return json({ access_token: 'freya-bank-test-token', token_type: 'Bearer', expires_in: 1800 });
      const service = path.startsWith('/voice/v1/') ? path.slice('/voice/v1/'.length) : '';
      if (!SERVICES.includes(service)) return error(404, 'NOT_FOUND', 'Unknown endpoint');
      if (request.method !== 'POST') return error(405, 'METHOD_NOT_ALLOWED', 'This service requires POST');
      let body;
      try { body = await request.json(); }
      catch { return invalid('Request body must be valid JSON'); }
      if (!isObject(body) || !isObject(body.data)) return invalid('data must be a JSON object');
      const validationError = validate(service, body.data);
      if (validationError) return validationError;
      const data = body.data;
      let answer;
      if (customerServices.has(service)) answer = customers.get(String(data.customerNo))?.services[service];
      else {
        answer = cardServices.get(service).get(data.cardNumber);
        if (weekServices.has(service)) answer = answer?.[String(data.newStatementWeek)];
      }
      if (!answer) return notFound(service);
      if (answer.delaySeconds) await wait(answer.delaySeconds * 1000);
      // Stateless acknowledgement of mutation fixtures: neither this response
      // nor any later response is changed, and delaySeconds is not in the body.
      // Dates are fixture constants. No code reads Date.now or the system date.
      return json(answer.response, answer.http);
    }
  };
}

export default createWorker();
