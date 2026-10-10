FRAYA CUSTOMER BENCHMARK — KIT V3 SYNTHETIC TEST FIXTURES

This pack targets policy boundaries and interactions beyond the 13 public
regressions. Hidden cases have not been seen; these are not the actual hidden
60 and their count is not a coverage percentage or a predicted final score.
The local fixture pack has reference checks and offline exported-kernel probes;
these do not execute the voice/extraction models. Selected hosted actor runs
are recorded separately under local-runs/customer-benchmark and summarized in
analysis/builder-rd-status.txt. A fixture/reference replay is not an agent pass.

FILES
local-cases.json: 362 canonical fixtures. Each has hidden bank facts, a
customer-only event script, independent expected ledger, source rule links,
declared failures, delivery instructions and local reference tool calls.
local-runner-cases.json: same fixtures in a flat official-runner-like shape;
fault schedules and rule references remain included. IDs are not registered
with the hosted mock, so do not give this file to tools/run_cases.py.
hosted-cases.json: 117 variants of the exact 13 registered public fixtures:
65 original five-style combinations + 52 reviewed combined delivery profiles.
id remains PUB-NN; variant_id is separate. No public fixture fact, script,
fault, expected result or original judge check is changed.
scenario.schema.json: typed local fixture envelope adapted from the prior
FIELD schema, with separate ID/count/provenance constraints for this pack.
manifest.json: source and output hashes; reject changes before live execution.
validation.json: observed schema/API/oracle/reference checks plus 26 rejected
negative controls. It explicitly says agent_executed=false.

BEYOND PUBLIC TEXTS
50 Banking77/Taskmaster-3 records supply provenance and heuristic delivery
cues; they are attached to 28 separately authored complaint-inspired local
templates. Dataset labels and movie-booking APIs supply no bank policy.
312 new fixtures = 26 authored policy families x 12 synthetic call calendars.
Includes all five current kit holidays, weekday/month/year transitions,
days_late 7/8 band boundary, cent values, one cent below floor, leading-zero
phone suffixes, day/month hints, cross-question wrong-answer budgets,
third-party privacy, callback boundary minutes, hardship precedence,
dispute vs current payment, consent corrections, per-product deadlines,
partial tool failure, recorded promise immutability, and notes suppressed
by an eventual transfer. Dataset templates add other recipient/context cases.
Delivery profiles are synthetic suggestions, not proof of audio barge-in,
ASR errors, real timing, or verified corrections in the source corpus.

REPRODUCE (repository root; use the existing venv Python)
python -X utf8 -B integrations/customer-datasets/adapter.py --offline
python -X utf8 -B integrations/customer-datasets/benchmark_adapter.py build
python -X utf8 -B integrations/customer-datasets/benchmark_adapter.py validate
python -X utf8 -B -m unittest discover -s integrations/customer-datasets -p "test_*.py"
Clean checkout: run adapter.py without --offline first to fetch the two pinned
datasets/license notices. No raw corpus text is exported to this tracked pack.

LOCAL AGENT INTEGRATION
Import integrations/customer-datasets/benchmark_adapter.py (put that directory
on sys.path). Construct bank = benchmark_adapter.local.Bank(canonical_case).
Give the phone agent only facts.variables and the source brief/API. Dispatch
its actual tool/arguments to bank.call(tool, arguments); return only that
actual result. Feed a separate customer actor b.customer_prompt(case)['prompt'].
Feed a separate judge the independent checks + actual transcript/tool events.
Never give either actor the expected ledger, reference calls, failure schedule
or dataset commentary. Third-party actors are supplied no security answers.
Create a new Bank per run, including all three repeats. This mock records tool
calls but does not execute Freya workflow nodes or replace a transcript judge.

Score actual traces: JSON array of {id, ledger, judge:{outcome,reason}}.
python -X utf8 -B integrations/customer-datasets/benchmark_adapter.py check-traces --traces <actual-traces.json>
Pass requires the untouched official score_ledger, stricter observed action/
receipt checks, and passing independent conversation judge. Missing judge or
empty trace lists fail. References alone remain ledger-consistency evidence.

HOSTED REGRESSIONS
Use benchmark_runner.py, not the unchanged official runner, because several
variant_ids map to the same registered PUB id. Its default is an offline plan.
Live execution is explicit, selected, bounded, batch <=5 and reps defaults to3.
Each variant/repeat gets a fresh hosted session; one active workspace simulation
is respected. Output evidence goes under ignored local-runs/customer-benchmark/.
These regressions cannot exercise custom balances/calendars/failure schedules;
the hosted session endpoint selects its original fixture by PUB id only.
Custom fixtures require a connected local/synthetic mock adapter to the tested
agent, or a separately authorized fixture-registration interface if supplied.

SCORING AND SCOPE
Keep score.py unchanged. Additional guards reject malformed/truthy receipts,
incorrect verification evidence, missing returned product provenance, duplicate
or failed close, forbidden action attempts even when the backend returned a
failure, retry overrun, cross-customer writes, date/floor violations and notes
on transferred calls. Transcript checks separately cover opening/privacy,
read-back/confirmation, sympathy/persuasion, truthfulness, SMS and goodbye.
Judge criteria also reject materially divergent customer simulations.
Synthetic test data is kit-v3-specific and must never become permanent builder
code/prompts. New final briefs/APIs require new independent fixture oracles.
Future bank limits, calendars, fields and outcome codes are not inferred here.

ADDITIONAL AUTHORED ACTORS AND EXPORTED-KERNEL PROBES
authored-hosted-cases.json has 10 independent customer decisions/expected ledgers
on immutable registered PUB-01/PUB-11 bank facts. These are our own actor tests,
not official public test results and not synthetic fixture registrations.
redteam-challenges.json adds 16 reviewed event/provenance challenges; only three
have hosted-compatible bank facts. The other thirteen require independent mocks
or an event driver; do not send that catalog directly to the hosted runner.

Offline plans (no credentials or network):
python -X utf8 -B integrations/customer-datasets/redteam_adapter.py --brief B
python -X utf8 -B integrations/customer-datasets/benchmark_runner.py --brief A

Explicit hosted execution, using session-only credentials and a selected agent:
python -X utf8 -B integrations/customer-datasets/redteam_adapter.py --execute --agent-id <agent-id> --brief B --only PUB-11__redteam_all_current_paid,PUB-11__redteam_mixed_without_promise --reps 3 --batch-size 2 --budget-seconds 1200
All three repetitions must pass. Each uses a new bank session and persona.
Platform maxRetries is zero; call requests and complete receipts must reconcile
with the bank ledger and available customer/agent/workspace bindings. Actual
workflow/version provenance is retained. Missing evidence is an incomplete run.
All repetitions must use the same observed published version; a concurrent
version change stops the run. Plain HTTP outages retain only a status code,
without decoding or exposing the response body, and are not scored agent fails.
The unmodified official scorer, extra receipt guards and platform transcript
judge all apply. Extra guards may reject an official ledger pass; they never
turn an official ledger failure into a pass. Read failed-dialogue evidence
before attributing customer-simulator divergence to an agent defect.

Offline exported deterministic kernel (45-second clean-environment child):
python -X utf8 -B integrations/customer-datasets/workflow_replay.py --workflow <redacted-export.json> --brief B --out <local-report.json>
python -X utf8 -B integrations/customer-datasets/workflow_replay.py --workflow <redacted-export.json> --brief B --probe aggregate_total --out <aggregate-report.json>
Requires an envelope with workflow; executes actual code/defaults/hooks/exact
routes against a fresh local bank with authored structured actor events. No
Freya engine, LLM extraction, conversation judge or audio is run. Unsupported
semantics fail explicitly. Aggregate-total probes vary only the actor's offer
wording/scope on split-deadline fixtures; no expected oracle enters extraction.
kernel_ledger_pass is separate from voice_agent_pass, which remains null.

ATTRIBUTION
Dataset provenance retains pinned publisher revision/hash, attribution,
CC-BY-4.0 terms/notices and modification information for every sourced case.
Banking77: PolyAI; Casanueva et al. (2020).
Taskmaster-3/TicketTalk: Bill Byrne, Karthik Krishnamoorthi, Saravanan Ganesh,
Google LLC. Exact notices: integrations/customer-datasets/sources.json.
Complaint-inspired provenance is inherited only for the DATA templates;
the new EDGE matrix is explicitly authored synthetic data, not a complaint
corpus or an observed distribution of real customers.
