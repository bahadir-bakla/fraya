# voice_contract

skill-creator's contract-first idea, applied to voice agents in regulated call centers.

A policy (SOP clauses: required disclosures, identity-before-account-data, forbidden threats, no PII read-back, handoff triggers) is compiled **once** into a Voice Acceptance Contract of `VC-*` rows. Each row names the policy clause it enforces, and the same contract drives three things:

| | What | Module |
|---|---|---|
| Live | Streaming guard between LLM and TTS. Holds back a short window, checks the whole turn so far, releases only safe text. A blocked turn is replaced by the rule's fallback line before any of it is spoken. | `guard.py`, `pipecat_guard.py` |
| After the call | Independent transcript audit (does not replay the guard, so guard bugs surface as disagreements) and pass@1 / pass^k over repeated runs. | `audit.py` |
| Before release | Generated tests: Freya unit tests (`POST /api/v2/unit-tests`) and personas (`POST /api/v2/personas`), plus Pipecat Evals scenarios. | `emit.py` |

A rule that lives only in a system prompt is a suggestion. This is the voice version of skill-creator's lesson that a rule stated in prose gets skipped and needs a mechanical check.

## Quick start

```bash
pip install pyyaml               # core needs only this (for .yaml policies)
python -m voice_contract table  voice_contract/policies/tr_bank_collections.yaml
python -m voice_contract emit   voice_contract/policies/tr_bank_collections.yaml out/
python -m voice_contract audit  voice_contract/policies/tr_bank_collections.yaml call.jsonl
python -m voice_contract bench  voice_contract/policies/tr_bank_collections.yaml
```

In a Pipecat bot (`pip install pipecat-ai`, tested with 1.12):

```python
from voice_contract import load_contract
from voice_contract.pipecat_guard import ContractGuardProcessor

guard = ContractGuardProcessor(load_contract("policy.yaml"),
                               event_tools={"verify_identity": "identity_verified"},
                               on_handoff=transfer_to_human)
pipeline = Pipeline([transport.input(), stt, user_agg, llm, guard, tts, transport.output(), assistant_agg])
```

## Rule kinds

| kind | side | enforced how |
|---|---|---|
| `required_disclosure` | agent | `prepend` speaks the canonical line on turn 1; otherwise flagged if missing by `within_agent_turns` |
| `gated_topic` | agent | blocked until a backend event (e.g. `identity_verified` from a successful `verify_identity` tool call) |
| `pii_leak` | agent | checksum-validated card (Luhn), Turkish ID (TCKN), TR IBAN (mod-97); `block` or `redact` |
| `forbidden` | agent | blocked (threats, guarantees) |
| `max_words` | agent | flagged (spoken replies must be short) |
| `escalation` | user | `handoff` to a target; the bot stops talking |
| `injection` | user | flagged |

Patterns are regexes matched on Turkish-aware lowercased text (İ→i, I→ı). Every rule must carry `source`; compile errors are all reported at once.

## Measured

- Guard cost: p50 0.62 ms, p95 1.13 ms per chunk on 200 four-word chunks (`bench`, this container's CPU).
- Added first-audio delay is the hold window (`hold_chars: 40`): the time the LLM takes to stream ~40 more characters, not speaking time.
- Tests: 27 pass, including card / TCKN / IBAN split at random chunk boundaries (150 cases) never reaching TTS, a real Pipecat pipeline run via `pipecat.tests.utils.run_test`, and the generated eval file loading through Pipecat's own `EvalScenarioFile.load`.

```bash
pip install pytest pytest-asyncio pyyaml pipecat-ai
python -m pytest -c voice_contract/pytest.ini voice_contract/tests
```

## Not done yet

- Freya unit-test and persona JSON follow the public API reference; nothing has been posted to a live Freya workspace.
- Pattern rules are lexical. A semantic layer (e.g. Qwen3Guard-Stream-0.6B, Apache-2.0, 119 languages) would sit behind them for harm and jailbreak.
- Guidance, not only blocking (PolicyGuide, arXiv 2608.19861): compile the policy into a workflow graph and feed step-specific corrections back to the LLM. The fallback lines here are the first step of that.
- Generating the policy YAML itself from an SOP document.
