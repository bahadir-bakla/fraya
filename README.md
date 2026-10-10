# fraya — Build the Builder

Brief files + their OpenAPI → policy compiler → Freya workflow → independent
tests → bounded repairs → platform export and trace. The target is a builder
that generalizes to unseen briefs, rather than a manually tuned phone agent.

The private working repository is `https://github.com/bahadir-bakla/fraya`.
It contains a source snapshot of the `agent-forge` code with the first builder
fixes, the official kit v3, research, benchmark inventory and a live MCP bridge.
No nested Git checkout, virtual environment or credentials are shipped.

## Current status

- Source inventory preserves all 47 Brief A rules and 11 Brief B amendments,
  physical source lines, tables and distinct IDs across files.
- OpenAPI supplies the actual tools, changed fields, enums and JSON body schemas.
  Source amendments are inventoried; semantic precedence is not compiled yet.
- Main tests: 230 passed, 2 optional integrations skipped. MCP bridge: 18 passed;
  real initialization and discovery expose 22 tools.
- Authenticated Freya MCP health, workflow listing and remote dry-run passed.
  An isolated baseline workflow was saved, published, simulated and exported;
  transcript and ledger were retrieved. PUB-01 ledger passed; conversation
  failed because the reference agent omitted the text-message confirmation.
  This was one baseline run, not a test of our future general compiler.
- The legacy `build` command still emits the old offline graph format. A general
  compiler to the official Freya graph and independent runtime oracle remain.

## Run on Windows

Python 3.11+, Git, and Codex CLI for MCP registration are required.

```powershell
git clone https://github.com/bahadir-bakla/fraya.git
cd fraya
.\setup.ps1
.\forge.ps1 inspect ../competition-v3/build-the-builder/briefs/brief-a.md ../competition-v3/build-the-builder/briefs/brief-b.md --tool-api ../competition-v3/build-the-builder/tools/openapi.json --out ../local-runs/input-contract.json
.\register-mcp.ps1
```

Supply `FREYA_API_KEY` and a stable `FREYA_BANK_TEAM_KEY` (any secret of at least
16 characters) in the process environment that launches MCP. Each collaborator
can use their own permitted workspace key. The original developer's DPAPI files
are excluded and cannot be used on another machine. Do not put keys in Git.
An explicit `--env-file` is also supported by the integration launcher.

Existing Codex sessions may need a reload to discover new tools. Direct MCP calls
also work immediately using `freya-call.ps1` with a JSON request list; examples
are under `local-runs/mcp-connect` and `local-runs/mcp-smoke`.

```powershell
.\freya-call.ps1 -Request local-runs/mcp-connect/request.json -OutFile local-runs/connect-result.json
cd skill-creator-skill-lift
.\.venv\Scripts\python.exe -X utf8 -m pytest -c agent_forge/pytest.ini agent_forge/tests voice_contract/tests -q
.\integrations\freya-mcp\.venv\Scripts\python.exe -X utf8 -m unittest discover -s integrations/freya-mcp/tests -p "test_*.py" -q
```

## Shared workspace coordination

Only one simulation can run at once per Freya workspace. Coordinate test starts
with collaborators, use separate stable workflow slots, publish before testing,
and record the published version. Never overwrite someone else's slot. The MCP
bridge checks remote running simulations and keeps local create/start recovery
state, avoiding automatic retries after an uncertain write.

## Evidence and next work

- `analysis/guide-merge.txt`: friend guide reconciled with kit and official site.
- `analysis/literature-review.txt`: τ-bench and ten primary references.
- `analysis/benchflow-transfer.txt`: reusable methods and evidence limitations.
- `analysis/benchmark-plan.txt`: final benchmark, public suite and build plan.
- `analysis/synthetic-cases.json`: 50 planning cases; not hosted bank fixtures.
- `analysis/mcp-live-connect.json`: live MCP connection and platform dry-run.
- `competition-v3/build-the-builder/`: authoritative versioned kit, unchanged.

Do not treat the reference base agent or one green smoke run as competition
readiness. Final deliverables require exported workflows, reproducible builder
code/commit/run command, and traces from automatic runs on unseen inputs.
