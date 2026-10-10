# MiroFish local readiness and scenario adapter

The official upstream checkout is pinned to `7657031ac01184afe2cb220f5ee3545573b5e843`. The normal backend now starts with authenticated CLIProxy and Zep configuration. A synthetic graph named `fraya-rd_20261010T132208Z` completed with four nodes and four edges. Two fictional participant agents completed one active Twitter round: Maya liked the seeded post and Noah published a reply. No agent errors were recorded. The test environment was closed; the loopback proxy and backend remain running in hidden processes.

The authoritative recorded results are `../../analysis/mirofish-readiness.json` and its text companion. Authenticated stage evidence is in ignored `runtime/authenticated-simulation.json` and `runtime/proxy-evidence.json`. The earlier `runtime/probe.json` remains an installation-only baseline whose app-factory health probe bypassed credential validation. The authenticated test instead used unmodified `backend/run.py` with normal validation and the pinned official graph/preparation/start/close APIs.

## Authenticated local use

The explicitly designated Desktop CLIProxy supplies the client key in memory. Its existing config remains unchanged. A tiny real completion verified `gpt-6-luna` through `http://127.0.0.1:8317/v1`; the selected model is not substituted. Zep's explicit `.local-secrets/zep-key.dpapi` is decrypted in memory by `scripts/freya_dpapi_server.py.unprotect`. The child process receives scoped MiroFish settings, dotenv is disabled, and provider logs are redacted. No plaintext credential file is needed.

From the `fraya` root in PowerShell:

```powershell
.\integrations\mirofish\run_authenticated.ps1 -ProxyConfig 'C:\Users\9bakl\OneDrive\Masaüstü\clıproxy\bin\config.yaml'
# Resume the existing bounded test; a completed test is observed without a new inference round.
.\integrations\mirofish\run_authenticated.ps1 -ProxyConfig 'C:\Users\9bakl\OneDrive\Masaüstü\clıproxy\bin\config.yaml' -Action smoke
```

The wrapper prefers existing services, proves a tiny completion before backend launch, and starts any missing service with `Start-Process -WindowStyle Hidden`. The smoke uses the same fresh, labelled test graph, at most three agents (the wrapper requests two), and exactly one Twitter round. Its phase timeout is 240 seconds when invoked by the wrapper, with an absolute permitted maximum of 600 seconds. It never deletes a Zep graph or enables graph-memory updates. Reports and interview calls are outside this smoke. The engine may download its public pretrained recommendation model on first use; future launcher model caches are scoped to ignored `runtime/`.

Two pinned-upstream limitations matter for evidence. Generated profiles originally activated only in the evening, so the first midnight round did no model-driven work; that attempt is retained as incomplete. The corrected test changes only its generated `simulation_config.json` to activate its two agents at hour zero and assigns the seeded post to Maya. The single-platform Twitter script does not write the runner's expected `actions.jsonl`, so the official API reports zero round/action counters even after successful work. Completion therefore requires official terminal process status, the engine's `Round 1/1` output, and actual social actions after the seeded post in a read-only OASIS database trace. Seed posts and refresh-only traces cannot satisfy the check. The restart validator also requires a Reddit profile for Twitter-only runs; the correction used a fresh simulation on the same owned graph.

Nonsecret connection metadata is published at `.local-secrets/cli-proxy-connection.json` (schema 1), with `base_url`, `model_ids`, `selected_model`, `verified_completion_model`, provenance, and `credential_file`. That credential file is `.local-secrets/llm-proxy-key.dpapi`, encrypted for the current Windows user and compatible with the same in-memory `unprotect`. The shared `provider_inventory` records two enabled Codex auth records, zero Claude records, and zero Claude API-key entries. No exact `claude-opus-5-5` route or alias is verified; no provider was activated or substituted. These ignored local artifacts contain no plaintext key.

## Installation and local use

Run from the `fraya` project root in PowerShell:

```powershell
.\integrations\mirofish\install.ps1
python integrations/mirofish/probe_runtime.py --engine-timeout 180
```

The installer fetches the exact commit, refuses to reset a different or modified existing checkout, runs `uv sync --locked --no-dev` in the backend, and runs `npm ci` and `npm run build` in the frontend. The project uses the existing Python 3.11.9, Node 24.13.1, npm 11.8.0, and uv 0.11.28. Upstream's backend requires Python 3.11 or 3.12. Its pinned Vite 7 frontend needs a recent Node release despite the README's broader Node 18+ prerequisite. The installed Node 24 meets it. Docker is installed but its Linux daemon is unavailable; the source path is used. Root `concurrently` dependencies and optional development groups are unnecessary for individual launch. Transitive dependencies, including OASIS/CAMEL and torch, remain installed as required by the upstream lock.

The verified probe uses a 180-second engine import allowance: the first 60-second attempt timed out, and the longer attempt successfully imported the same OASIS/CAMEL symbols used by upstream's simulation script. No model was instantiated. The frontend probe starts upstream Vite's preview server and fetches the built HTML, JavaScript, and CSS over loopback HTTP. It does not exercise browser interactions, backend API calls, graph construction, or an authenticated experiment. All probe servers are stopped after the checks.

For a separately configured backend, upstream also supports its own ignored environment file:

```powershell
Copy-Item integrations/mirofish/mirofish.env.example integrations/mirofish/vendor/MiroFish/.env
# Fill LLM_API_KEY and ZEP_API_KEY in that file using your own MiroFish configuration.
.\integrations\mirofish\run.ps1 -Service backend
```

Set `LLM_BASE_URL` to an OpenAI-compatible endpoint and `LLM_MODEL_NAME` to an available model. The template shows upstream's Qwen example; the authenticated test uses the designated local CLIProxy instead. The required Zep key must belong to Zep Cloud. The pinned configuration explicitly rejects `ZEP_API_URL`, so a local Zep server is not a supported replacement. Leave optional `LLM_BOOST_*` settings absent unless all three are intentionally configured. No unrelated application credentials are read, requested, or copied. The wrapper disables dotenv's parent-directory search when MiroFish's own `.env` does not exist.

In a second terminal, start the frontend:

```powershell
.\integrations\mirofish\run.ps1 -Service frontend
```

The frontend binds to `127.0.0.1:3000`, with the upstream proxy targeting `localhost:5001`. Keep backend port 5001 for the proxy. The wrapper suppresses automatic browser opening and uses the upstream Vite configuration in memory. Stop either service with Ctrl+C. The readiness probe uses temporary local servers and shuts them down itself.

## What this integration produces

The credential-free adapter reads the 50-case analysis catalog and the 13 official public cases. It emits scenario contracts and explicit expected output without calling an LLM or either hosted service. Generated records carry source hashes and remain labelled `scenario_only_not_executed`. Fixture facts, the customer's decision/script intent, expected tool/ledger results, and speech delivery belong to separate fields. Changing a delivery style must leave the protected facts/intent/oracle digest unchanged; this is a local integrity contract, not a claim that an LLM will always obey it.

Official `expected` objects are retained exactly. Synthetic cases keep their expectation basis, source rules, and oracle scope. Proposed extensions stay proposals; partial oracles do not acquire an invented final outcome. Synthetic fixtures and fault injections remain local specifications. They are not registered hosted bank fixtures.

Generate or verify the complete catalog, or export one speaking-style variant:

```powershell
python -B integrations/mirofish/scenario_adapter.py build
python -B integrations/mirofish/scenario_adapter.py verify
python -B integrations/mirofish/scenario_adapter.py seed --case PUB-01 --style in_words --output pub01-in-words.txt
python -B -m unittest discover -s integrations/mirofish/tests -p test_scenario_adapter.py -v
```

The JSON catalog always includes all 63 cases. `seed` accepts repeated `--case` options and the `plain`, `pieces`, `corrects`, `talkative`, `asks_back`, and `in_words` styles. Output paths are restricted to this integration's `scenarios/` directory; unknown IDs, malformed fixtures, arbitrary style text, and unsupported overrides are rejected. The checked-in `scenarios/example-seed.txt` demonstrates an official case, a partial synthetic oracle, and a proposed raw-memo extension. Seed text uses `.txt` or `.md`, supported upstream upload types. These seeds are planning inputs for a future MiroFish experiment and cannot establish simulation success or Freya performance.

## MiroFish and hosted Freya have different roles

MiroFish's upstream workflow builds a graph from seed documents, generates agent personas/configuration, runs OASIS social simulations for Twitter/Reddit-like environments, and produces reports and agent interactions. Here its useful role is future scenario exploration and speaking-style variation. It does not run Freya workflows, implement the bank API contract, or provide the competition's ledger/transcript oracle. Its graph/persona pipeline can reinterpret text, so generated ideas must be checked against the protected local case contract before adoption.

In the supplied official runner, `run_once` creates a practice session by sending only `{"case": case_id}` to `/v1/practice/sessions`. The returned session variables determine the hosted fixture. Editing persona text or adding a local case with different identity, dates, products, amounts, or faults does not provision that backend state. The 13 public cases can be represented locally; the 50 synthetic cases require a separate local mock/harness or an explicitly supported fixture-registration API. No such API has been assumed or contacted.

The supplied scorer checks actual ledger outcome/reason, promises, notes, callbacks, transfers, closing, and identity-related tool usage. The runner also requires the hosted transcript judge to pass. A MiroFish report, scenario file, or an installation smoke substitutes for none of these. No hidden-score estimate or actual bank behavior is inferred from this work.

## Packaging and sources

`vendor/`, `runtime/`, Python bytecode, caches, dependencies, builds, and `.env` files are ignored by this integration's `.gitignore`. The nested upstream `.git` exists only in the local ignored checkout. Commit the small integration files and scenario contracts only. Do not include ignored vendor/runtime directories in a zip or other file-based export; Git ignores do not govern arbitrary archive tools. Upstream source remains unmodified and retains its AGPL-3.0 license in the local checkout.

Primary upstream sources: [pinned README](https://github.com/666ghj/MiroFish/blob/7657031ac01184afe2cb220f5ee3545573b5e843/README.md), [dependency specification](https://github.com/666ghj/MiroFish/blob/7657031ac01184afe2cb220f5ee3545573b5e843/backend/pyproject.toml), [configuration](https://github.com/666ghj/MiroFish/blob/7657031ac01184afe2cb220f5ee3545573b5e843/backend/app/config.py), [launcher](https://github.com/666ghj/MiroFish/blob/7657031ac01184afe2cb220f5ee3545573b5e843/backend/run.py), and [environment example](https://github.com/666ghj/MiroFish/blob/7657031ac01184afe2cb220f5ee3545573b5e843/.env.example). Local fixture evidence: `competition-v3/build-the-builder/tools/run_cases.py`, `tools/score.py`, `public-test-set.json`, and `analysis/synthetic-cases.json`.
