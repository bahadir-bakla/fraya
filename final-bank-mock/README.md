# Final bank mock

Cloudflare module Worker for the final case. It serves the seven contract services at `/voice/v1/<service>`, with exact per-customer fixture bodies, HTTP statuses, and the specified 12-second delayed balance. The bundled fixture map has 34 customers and 617 responses. No database or secrets are needed.

`openapi.json` describes all seven POST paths. Its server is deliberately `https://final-bank-mock.invalid`. The parent must replace `servers[0].url` with the actual deployed public origin in its HOSTCONFIG preparation before running the builder. This is a mock integration artifact, not a handmade phone workflow.

## Local validation

```powershell
Set-Location -LiteralPath 'C:\Users\9bakl\OneDrive\Belgeler\ChatGPT\BUILD THE BUILDER\fraya\final-bank-mock'
node --test test/*.test.js
npx wrangler deploy --dry-run --outdir .wrangler/dry-run
npx wrangler dev
```

`npm run prepare` regenerates the fixture snapshot and placeholder OpenAPI from the immutable source pack. Do not run it after HOSTCONFIG replacement unless you intend to restore the placeholder. Unit tests compare every fixture route to the original source. The delay is verified using an injected waiter and separately with the real timer.

## Public deployment (parent handles authentication)

From this directory, with the parent's authenticated Cloudflare environment:

```powershell
npx wrangler deploy
```

Use the actual origin printed by Wrangler, such as `https://final-bank-mock.<account-subdomain>.workers.dev`. That example is not a verified deployed address. Keep the Worker reachable through competition scoring. No login, deployment, Git operation, or platform operation is performed by this deliverable.

After deployment, verify the public Worker using the provided all-fixture HTTP verifier:

```powershell
node scripts/verify-http.mjs 'https://<actual-worker-origin>'
```

It checks `/health` and all 617 fixture status/body pairs against the immutable source, including the delayed answer. A failed request or mismatch exits nonzero. Set phone tools to `POST <actual-origin>/voice/v1/<service>`, with `{"data":{...},"call":{...}}` envelopes.

## Contract behavior

- Customer numbers accept strings or numbers; requested weeks accept `1`–`4` or their string forms. Card numbers are exact masked keys from `cards.list`; response masking is not converted back into a lookup key.
- Required fields are validated before lookup. Week mutations require `statementDay`, weeks 1–4, and a card number. PDF sends require all five fields, a supported currency and a valid `dd.MM.yyyy` date.
- Unknown customer/card/week returns the contract's service-specific 404, or 400 `INVALID_ARGUMENTS_ERROR` for services without a defined 404. Missing PDF fixtures return `FB_IVR_CHANNEL_107`.
- Token/headers, `call`, and `aiFlow` do not affect fixture lookup. A mock `POST /oauth2/token` exists for integrations that request a token. No auth is enforced in the synthetic test environment.
- `statement.pdf.send` lookup is by customer number, as specified in test-customers.md. The bank backend does not enforce a registered email match; this mock adds no business policy. The phone agent owns consent and allowed-address checks.
- Change/send routes return the exact fixture acknowledgement and do not persist state. Preview, repeat mutations, subsequent reads, and linked-card reads remain deterministic fixture responses.
- All dates are copied verbatim from fixtures. `now` belongs to phone-agent date decisions and is not a bank service request field. No mock route consults the system clock.
- Customer 97631186 has no issued statement: `statementDate` and `lastPayDate` are empty strings in balance/week responses. OpenAPI preserves this exception; PDF request dates must still be nonempty.
- Unknown template strings produce contract errors; no customer is guessed for a test-panel placeholder.

Sources: `final-case-20261011/Build the Builder - Final Case/BRIEF.md`, `sources/documents/2026-10-01-service-contract.md` (especially section 6), and `test-environment/test-customers.json` / `test-customers.md`.
