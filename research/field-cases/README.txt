FRAYA FIELD CASES — SYNTHETIC LOCAL FIXTURES, VERSION 1.0.0
Reviewed/accessed: 2026-10-10, Europe/Istanbul. Official kit: version 3.

28 independently authored scenarios: 22 Brief A, 6 Brief B. Inspiration:
16 directly readable public original complaint/post pages, 8 Reddit and 8
Sikayetvar, across five subreddits and five financial-service names. Patterns
are unverified allegations, not facts about a bank or legal guidance.
All fixture identities, identifiers, balances and dates are synthetic.
Source publication metadata stays in provenance, never in bank fixtures.
Nine publication dates are explicit or indexed absolute dates; seven exact
dates are unknown. Unknown dates are null with the observed publication label.
Event dates, crawl ages and nearby posts never substitute for publication dates.

FILES
- sources.json: URLs, publication/access metadata, short paraphrased original
  patterns, evidence locators, limitations and excluded inaccessible candidates.
- scenarios.json: canonical catalog; facts, speaking_style, provenance,
  expected ledger, rule-linked oracle and local execution data are separate.
- scenario.schema.json: small generic scenario envelope profiled for this kit.
- runner-cases.json: flat array with the official runner/scorer field names.
  This can be ingested by an offline adapter; FIELD ids are not registered.
- hosted-style-mapping.json: proposed PUB/style mappings and their exact limits.
- official-inputs.json: hashes of the kit and existing analysis actually reviewed.
- local_runner.py: seven-tool in-memory bank fixture and independent bounded
  ledger/tool chronology checks. It has no network path or hosted mutations.
- build_catalog.py: reproducibly writes the authored JSON pack in this directory.
- validation.json: observed schema/contract/hash/reference replay and negative
  control results, explicitly excluding an agent or transcript-policy pass.
- write_review.py: creates only analysis/field-scenario-review.json and .txt.

SMALL SCENARIO CONTRACT
id, title, brief: selection and effective source policy.
facts: variables, hidden mock identity/products, recipient role, customer event
  plan and local faults. These are input facts, not agent instructions.
speaking_style: rendering instructions that cannot change facts, role, willingness
  or fault schedule. Deliberate factual revisions are events; generic corrects
  delivery changes only an initial rendition and ends with the canonical value.
provenance: complaint pattern vs invented architectural combination, dates/URLs.
expected: outcome, reason, promises, notes, callbacks and transfers.
oracle: independently authored constraints, official rule references, and clear
  confirmation requirements; never derived from the agent under test.
execution: local-only reference calls and a customer-only script.

All numbered A1-A47 and B1-B11 anchors are inventoried with source lines.
Special section/table anchors identify the calendar, call variables, closing
precedence and B inheritance. O-* references point into the delivered OpenAPI.
This is not a claim that every official rule is covered by these 28 cases.
Shared constraints apply with their stated branch/A/B conditions. B overrides A:
per-product paid/dispute continues; B closing uses account return order; any
transfer suppresses all notes, including ones whose reasons were learned earlier.

LOCAL EXECUTION (from the fraya repository root; Python 3.11 and jsonschema)
python -X utf8 -B research/field-cases/build_catalog.py
python -X utf8 -B research/field-cases/local_runner.py validate --out research/field-cases/validation.json
python -X utf8 -B research/field-cases/write_review.py

One executable fixture, with a fresh empty ledger and reset identity/fault state:
python -X utf8 -B research/field-cases/local_runner.py replay --id FIELD-28

For a locally connected agent, instantiate local_runner.Bank(case) and dispatch
only tool names/arguments to Bank.call. Feed the agent only call variables and
its own successful tool results. Feed a customer simulator only its authorized
role/identity, customer event plan and speaking_style; a third party knows no
security answers. Do not feed either actor source commentary or expected output.
Account product ids must come from get_account, not from the customer's script.
The local fixture's human-readable p1/p2/p3 labels identify products for adapters;
translate them to the spoken product labels in customer simulation.

ACTUAL TRACE INPUT
check-traces accepts a JSON array of {"id":"FIELD-xx","ledger":{...}}.
ledger has outcome, reason (null when absent), promises, notes, callbacks,
transfers and calls. Each call has tool, arguments and actual result.
The shapes match the ledger consumed by the official score_ledger function.
python -X utf8 -B research/field-cases/local_runner.py check-traces --traces <local-traces.json>
The checker reconstructs ledger mutations from successful calls and checks
verification/order, ids, dates/floors, retries, transfer notes and closing.
It does not infer a spoken confirmation or judge empathy/read-back/honesty.
The scenario's shared and scenario-specific transcript constraints need an
independent transcript judge plus simulator-fact fidelity checks. No complete
agent pass may be inferred from a passing ledger/tool check.

Reference replay is a positive-data consistency check, not an agent run.
The in-memory mock deliberately accepts invalid calendar/floor values when its
tool contract would: the independent oracle rejects them. Error strings and
promise ids in this local mock are synthetic; they are not hosted API claims.
Fault injection is declared only in local facts. All other tool actions succeed.
No unspecified callback/transfer failure recovery oracle is invented.
Fresh Bank instances reset all state; never reuse one across scenarios.

HOSTED BOUNDARY
Do not pass runner-cases.json to the official hosted run_cases.py.
The --cases option reads a list but run_once obtains registered fixtures by
posting only their case ids to /v1/practice/sessions. No arbitrary fixture
registration is documented in the inspected kit. Flat shape is not registration.
hosted-style-mapping.json proposes styles only for existing PUB ids; the original
PUB facts, products, dates, amounts, willingness, faults and oracle stay fixed.
It cannot execute a FIELD case or prove these scenarios pass on Freya.
No hosted simulation, persona creation, workflow publish, or MCP mutation ran.

GENERIC USE AND COVERAGE LIMITS
Use the existing 50-case analysis catalog as related coverage, not executable
bank data. This pack adds complaint contexts, consent boundaries and composites;
it does not replace the original catalog or treat public13 as a final oracle.
Future fixtures must recompute bands, floors, dates, outcome/queue enums and
identity order from that future brief and its own API. Current examples belong
to fixture data, never permanent builder logic. local_runner is a kit-v3 local
prototype, not a general policy compiler or production bank service.
OpenAPI success is not evidence of policy compliance. Compare ledger and actual
conversation independently; retain repeated-run requirements from the kit.

Only research/field-cases/** and analysis/field-scenario-review.{json,txt} were
written for this research task. Concurrent unrelated workspace files are owned
by their collaborators and were neither edited nor assessed here.
