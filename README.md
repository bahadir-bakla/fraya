# fraya — Build the Builder

Build a Freya phone workflow from brief files and their supplied OpenAPI. Source
inventory and policy/gap review feed compact workflow IR; deterministic expansion
fills tool schemas, URLs, methods, required fields and enums from that API. Lint
and coverage checks precede an independent source critic, remote dry-run,
save/publish, fixed-model and authored-field readback, optional registered practice,
and platform export. Practice combines ledger and conversation verdicts. Bounded
JSON patches repair candidates; artifacts and traces persist throughout.
The compiler binds known private tool-macro response aliases only in routing
variables; literal API payloads remain opaque. Advisory progress checks inspect
reachable native termination and close-result routes. Repairs receive bounded
execution counts from real calls without customer speech, arguments or results.
Invalid source references in policy-gap review receive at most two model repairs;
original rejected reviews and genuine blocking ambiguities remain recorded.

[Builder architecture](docs/builder-architecture.mmd) shows this implemented path.
The legacy `forge.ps1 build` command still emits the older offline graph format.

## Recorded status — 2026-10-10

See [builder R&D status](analysis/builder-rd-status.txt) for evidence and remaining gates.

- The new [V10 automatic build](local-runs/builder-progress-a-v10/trace.json)
  emits native termination but was rejected by the source critic after 189s
  for callback/transfer receipts, stop/retry state and speech/closure ordering.
  The [V11 automatic Sol repair](local-runs/builder-progress-a-v11/trace.json)
  hit its 240s model timeout within the same original budget. Neither published
  nor started hosted practice. Latest actually executed voice score remains
  **0/3**; source validation and review gates were retained. Builder code was
  unchanged from commit `d30204e` throughout V10/V11.
- Latest full core UTF-8 run: **742 passed, 2 optional integrations skipped in
  65.45s**. Separately verified: **19 Bridge tests** and **36 MiroFish integration
  tests** passed. The latest **86 focused compiler/build/platform checks** and
  earlier 120 focused checks are included in the core total, not added to it.
  The latest share audit checked **773 files** cleanly after dataset integration.
- [V8 development checkpoint run](local-runs/builder-rd-a-v8/trace.json) completed
  in **1153s** from its original **13:37 UTC** start, including manual builder-code
  fixes between processes. Candidate 5 has seven nodes; its independent critic
  passed with no issues. Remote dry-run, save/publish in `codex-builder-rd-a`,
  `experimental-5` and authored-field readback, three public simulations and
  [platform export](local-runs/builder-rd-a-v8/platform-export.workflow.json)
  completed. The actual result is **`practice_failed`, 0/3**, with `final_ready=false`.
  All three calls stopped after the greeting and first user reply, used no tools,
  and ended after about 62s with `customer-ended-call`. This does not establish a
  clean 30-minute run on unseen inputs; contest artifacts remain **not ready**.
- The [baseline control](local-runs/platform-baseline-control/trace.json) ran PUB-01
  on the prior working reference agent after V8, without overlapping simulations.
  It also stalled after the opening exchange and ended at 62s. Its later lifecycle
  `close_call` used invalid `no_promise`, so no ledger closure, verification, account
  lookup or promise occurred. The complex-workflow stall remains unresolved.
- Both minimal `experimental-5` controls responded across many turns:
  [LLM entry](local-runs/model-availability-control/evidence/trace.json) produced
  **81 assistant / 80 user messages in 152s**;
  [TTS entry](local-runs/model-availability-tts-control/evidence/trace.json) produced
  **17 assistant / 16 user messages in 45s**. Both used one conversation node
  without extraction, routing, tools or hooks. This demonstrates model availability,
  with **no evidence that TTS caused the complex-workflow stall**. Their failing
  practice scores are expected without bank policy; invented monetary details are
  diagnostic failures, not ledger facts. These are protocol controls, not ready agents.
- The explicit [entry-adapter probe](local-runs/builder-chat-entry-probe-a/trace.json)
  of V8 candidate 5 in `codex-builder-probe-a` version 2 completed **0/3**, now with
  spoken replies and tool calls. Identity attempts recorded empty bank arguments:
  only `customer_id` reached the HTTP body; the security field and answer were
  omitted because model-supplied fields lacked body-binding defaults. Post-hooks
  also logged snekbox DNS failures at `snekbox-svc.staging.local:8060` and connection
  resets. These were observed transient sandbox errors, not an ongoing-outage claim;
  the adapter remains an explicit comparison experiment with no TTS causal proof.
- The [body-binding probe](local-runs/builder-body-binding-probe-a/trace.json)
  completed **0/3**, with `final_ready=false`. Operation/field-specific
  `{{forge_arg_<hash>}}` defaults preserve API shape, types, descriptions and enums;
  both date-of-birth and phone checks now verified in PUB-01/PUB-06 ledgers, and
  PUB-01 actually called `get_account`. Policy failures remain: PUB-01 recorded no
  promise and closed as transferred to a human without a transfer; PUB-02 passed
  conversation review but recorded no callback; PUB-06 made an unnecessary support
  transfer, then repeated farewells without closing. No `function_call_error` events
  were recorded in this latest probe. Binding progress is not a benchmark pass.
- The separate [development probe](local-runs/builder-development-probe-a/trace.json)
  of v8 candidate 1 published in `codex-builder-probe-a`, verified `experimental-5`
  and authored-field readback, then scored **0/3** public practice cases. It retains
  the rejecting `revise` review and `final_ready=false`; it does not pass the
  builder review gate.
- [Freya baseline evidence](local-runs/mcp-smoke/summary.json) verifies connection,
  dry-run, save/publish, simulation and export. PUB-01 passed its ledger but failed
  conversation requirements. It was the official reference agent.
- `guarded_actions` has **75 passing offline checks**. It is not automatically
  enabled in current phone workflows. The compiler expands explicit
  `@builtin:guarded_dispatch` references into baked code; `build-live` and the probe
  call `validate_guard_wiring` for opted-in gates. This checks local gate structure.
  Next gates are trusted source-policy/state/action adapters, backend-success
  evidence before terminal dispositions, and confirmed promise/callback/transfer
  actions. Successful bank closure must route to silent native `end_call` to prevent
  repeated farewells. These structural policy guards are still missing in the candidate.
- [MiroFish](analysis/mirofish-readiness.txt) completed an actual **two-agent,
  one-round** smoke. UI/API round/action counters remained zero because the
  monitor's expected action log was absent; engine output and persisted social
  actions establish completion. This exercised no bank or Freya scenario.
- [Exact Opus](analysis/opus-redteam.txt): the authenticated `claude-opus-5-5`
  proxy request returned **HTTP 502 / unknown_provider_for_requested_model**;
  native Claude CLI was unauthenticated. No Opus inference or attacks were obtained.
- [28 complaint-inspired field cases](research/field-cases/README.txt) and
  [50 planning cases](analysis/synthetic-cases.txt) are synthetic local material,
  not registered hosted bank fixtures or evidence of a generated-agent pass.

## Windows setup

Use Python 3.11+, Git, and a signed-in Codex CLI on PATH for model generation.
`setup.ps1` creates the child core venv and a separate MCP integration venv;
the core venv intentionally does not install the MCP server package.

```powershell
git clone https://github.com/bahadir-bakla/fraya.git
cd fraya
.\setup.ps1
$env:FREYA_API_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Your permitted Freya API key' -AsSecureString)).Password
$env:FREYA_BANK_TEAM_KEY = [System.Net.NetworkCredential]::new('', (Read-Host 'Stable bank team key, at least 16 characters' -AsSecureString)).Password
```

Each collaborator supplies permitted credentials in the process that launches
the builder/MCP. Set `FREYA_WORKSPACE_ID` when a key sees multiple workspaces.
Start Codex/MCP from that environment; optional `.\register-mcp.ps1` registers the
server without storing keys. Credentials, DPAPI stores and venvs are excluded
from the shareable snapshot; another machine cannot reuse local DPAPI files.

## Build and resume

From the root, replace the input paths with your files. Include inherited briefs
when an amendment depends on them. `build.ps1` wraps the `build-live` CLI.

```powershell
$PracticeCases = Read-Host 'Compatible registered practice IDs, comma-separated; blank to publish untested'
.\build.ps1 -Briefs @('.\inputs\brief.txt') -ToolApi '.\inputs\openapi.json' `
  -Out '.\local-runs\my-build' -Slot 'my-builder' -Cases $PracticeCases `
  -BudgetSeconds 1800 -Repairs 2
```

Strict mode is the default: binding source gaps, missing coverage and concrete
critic errors block deployment. `-AllowSourceGaps` (`--allow-source-gaps`) is an
explicit **practice-development** mode requiring `-Cases`; it preserves gap and
limitation evidence and may accept a blocked critic, but never suppresses concrete
critic errors. Live results always retain `final_ready=false`.

`-CompileOnly` emits an unpublished, untested artifact. `-Model` selects the builder
model; the phone model remains `experimental-5`. `-Style` changes speaking style,
and `-Reps` repeats registered practice cases. FIELD/SYN IDs cannot be used as
hosted `-Cases`; style changes do not install new bank facts.

Resume only a stopped run with matching source/API hashes and its sidecar files.
Keep its original `-BudgetSeconds`: time since the original start still counts.
`-WorkflowCheckpoint` takes a candidate envelope from that same run, not an
expanded `workflow-*.json` file.

```powershell
.\build.ps1 -Briefs @('.\inputs\brief.txt') -ToolApi '.\inputs\openapi.json' `
  -Out '.\local-runs\my-resume' -Slot 'my-builder' -Cases $PracticeCases `
  -BudgetSeconds 1800 -PolicyCheckpoint '.\local-runs\my-build\policy.json' `
  -WorkflowCheckpoint '.\local-runs\my-build\candidate-1.json'
```

Use a distinct stable slot per collaborator. The builder waits for remote running
simulations; the Bridge checks starts again and retains uncertain-write recovery state.
Inspect `trace.json`, policy/gap review, compact candidates, expanded workflows,
lint/critic/readback records, practice ledgers/transcripts and platform export in
the output directory. A practice pass alone does not establish final readiness.

## Development probe

For an explicit **development-only** empirical trial, `scripts/probe_candidate.py`
accepts a structurally valid candidate envelope and its existing critic review.
It expands and lints the draft, validates explicit guard wiring, publishes in your
own distinct slot, verifies model and authored-field readback, runs the selected
registered cases and exports evidence.
From the root, replace the paths and slot; select compatible cases without spaces:

```powershell
$ProbeCases = Read-Host 'Nonempty registered practice IDs, comma-separated'
& ./skill-creator-skill-lift/.venv/Scripts/python.exe -X utf8 -B scripts/probe_candidate.py `
  .\local-runs\my-build\candidate-1.json --review .\local-runs\my-build\critic-1.json `
  --tool-api .\inputs\openapi.json --slot my-builder-probe --cases $ProbeCases `
  --out .\local-runs\my-probe --budget-seconds 600
```

Optional `--chat-entry-adapter` uses compiler `chat_mode=True` to replace conversation
TTS entries with LLM prompts that request the exact authored line. This is an explicit
comparison experiment. The compiler defaults to `chat_mode=False`, and normal
`build-live` preserves TTS entries.

The probe preserves the supplied review in `independent-review.json` and candidate
limitations in `limitations.json`. Even `probe_passed` retains `final_ready=false`
and does **not** satisfy `build-live`'s independent review gate. It is a separate
development command, not `-AllowSourceGaps` or a reviewed-builder success.

## Offline verification

Run from the root. Restore the root after core tests so Bridge discovery uses
the separate integration interpreter and the correct test directory.

```powershell
Push-Location .\skill-creator-skill-lift
try {
  & .\.venv\Scripts\python.exe -X utf8 -m pytest -c agent_forge/pytest.ini agent_forge/tests voice_contract/tests -q
} finally { Pop-Location }
& ./skill-creator-skill-lift/integrations/freya-mcp/.venv/Scripts/python.exe -X utf8 -m unittest discover -s skill-creator-skill-lift/integrations/freya-mcp/tests -p "test_*.py" -q
```

The authoritative kit is [competition-v3/build-the-builder](competition-v3/build-the-builder/).
[Benchmark plan](analysis/benchmark-plan.txt), [research transfer](analysis/benchflow-transfer.txt)
and [field review](analysis/field-scenario-review.txt) describe evaluation scope.
Final deliverables require platform-exported workflows, reproducible builder code
and commands, and traces from fresh automatic runs on unseen briefs and API schemas
from one immutable commit within the official time limit. The development checkpoint
chain above does not establish that competition result.

## Public dataset planning adapters

[Customer dataset adapter](integrations/customer-datasets/README.txt) downloads
the pinned Banking77 test split and one Taskmaster-3 shard, verifies source and
license-notice SHA-256, and produces 50 local conversation plans. The separate
12-test stdlib suite and an offline rebuild pass on the actual downloaded files.
Raw files and generated plans stay in ignored cache. The records preserve
taxonomy, turn structure and hashed lexical cues; they contain no raw speech,
bank policy mapping or bank expected output. Scope is `conversation_only` /
`not_executed`, not an additional Freya benchmark. See the
[six-candidate primary-source research](research/customer-datasets.txt).
