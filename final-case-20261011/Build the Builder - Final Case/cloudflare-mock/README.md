# Mock service with Cloudflare Workers

Your flow's tools call a mock service that you write, instead of the real bank service. You publish this service as a free Cloudflare Worker. The `example/` folder here only shows the pattern: a Worker with a single endpoint (`POST /ping`). You will write the statement-debt services yourself.

## Requirements

- Node.js 18 or later
- A free Cloudflare account (dash.cloudflare.com)
- Wrangler (Cloudflare's command-line tool): runs without installing, via `npx wrangler ...`

## 1. Run the example locally

```bash
cd example
npx wrangler dev
```

The Worker opens at `http://localhost:8787`. Try it from another terminal:

```bash
curl -s -X POST http://localhost:8787/ping \
  -H 'content-type: application/json' \
  -d '{"kod": "A1"}'
```

The response is the same as `example/example-response.json`. For a code that does not exist it returns `404` and `{"hata": "kayıt bulunamadı"}`.

## 2. Publish it

```bash
npx wrangler login      # grant access to your Cloudflare account in the browser
npx wrangler deploy
```

The output shows the Worker address: `https://example-mock.<your-subdomain>.workers.dev`. To change the name, change the `name` field in `wrangler.toml`. Run `npx wrangler deploy` again whenever the code changes; the address stays the same.

Check after publishing:

```bash
curl -s https://example-mock.<your-subdomain>.workers.dev/health
```

## 3. Connect the tool in the Freya flow to the Worker

1. Add an API tool to the flow.
2. Enter the method and address: `POST https://<your-worker-name>.<your-subdomain>.workers.dev/<path>`. For the statement services, use the same path as under the bank's base address in `../sources/documents/2026-10-01-service-contract.md` (for example `/voice/v1/cards.list`).
3. In the request body, write variables in the form `{{variable_name}}`. Example: `{"data": {"customerNo": "{{customerNumber}}", "aiFlow": "..."}, "call": {...}}`. During the call, the variable's value is substituted in.
4. Take the fields you will use in the flow from the response into variables.

The "Test API Request" button in the panel may send the text `{{customerNumber}}` as is, without filling in the variables. In this case the example Worker returns a valid record instead of an error (`isTemplateVariable`). Doing the same in your own services makes testing easier.

## When writing your own services

- Endpoints, request and response fields must match `../sources/documents/2026-10-01-service-contract.md` exactly: the same path, the same field names (`data`/`call` request body, `data`/`result` response), the same date and amount format. The test customers' responses are in `../test-environment/test-customers.json`, explained in `../test-environment/test-customers.md`.
- Keep customer and card data in a table inside the Worker file (like `RECORDS` in the example). No database is needed.
- For a customer or card that is not found, return the error response from the contract; do not return made-up data.
- Responses should return data only (amount, date, status). The flow builds the sentence to be said to the customer.
- Do not put secret keys or real personal data in it; the Worker address is public.
