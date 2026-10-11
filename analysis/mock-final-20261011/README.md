# Mock final — 11 October 2026

A rehearsal of the final: two briefs the builder had never seen, one automatic build each, then simulated
customers with human speaking styles, scored like the final (a case counts only if every run passes).

## Setup

- **Briefs.** Written blind by a separate agent that could read only the public kit (README, briefs A/B, OpenAPI,
  public test set, runner, scorer), never the builder's code. `briefs/brief-c.md` is a clean specification;
  `briefs/brief-d/` is raw bank material (email, policy extract, amending memo, code list) with up to three
  products. Rules differ from A/B: identity order and limits, calendar and holidays, floors, deadlines, retry on a
  failed promise (C: never, D: up to three calls), notes on single-product calls, hardship handling, transfer
  queues, and all reason codes.
- **Cases.** `cases-c.json` (10) and `cases-d.json` (13) reuse the 13 registered customers' facts exactly
  (names, identity, products, `now`), with new scripts, expected ledgers and judge checks. `answer-key.md` derives
  every expected ledger; `audit.md` is an independent re-derivation (19 OK, 2 ambiguous, 2 script risks, 0 wrong;
  the four flagged scripts/checks were fixed before running, ledgers unchanged).
- **Builder.** `origin/codex/builder-rd` at `31b86c0`, `--skip-tests`, 30-minute limit, model `gpt-6-astra`.
  C built in 577 s (round 1), D in 889 s (round 2; round 1 rejected by the builder's own coverage gate).
- **Runs.** Kit `tools/run_cases.py`, unchanged, with `--style talkative`, `corrects`, `pieces`.

## Results (v1 builder)

| | C (clean spec) | D (raw material) |
|---|---:|---:|
| Calls passing, raw score | 5 / 30 | 0 / 26 |
| Calls passing, adjusted | 8 / 30 | 0 / 26 |
| Cases passing every run | **0 / 10** | **0 / 13** |

*Adjusted*: the hosted mock only accepts Brief A/B close reasons, so a `close_call` rejected solely for an unknown
reason code is counted with the agent's own outcome and reason (`rescore.py`; the final's mock knows its own
table). D's `pieces` run and both plain control runs were lost to Freya 5xx outages and are not reported.

Per-case rows: `results-v1/*.log` (failure reasons as printed by the kit runner), `results-v1/*.json`,
`results-v1/rescored.json`.

## Failures and causes

1. **Recipient confirmation rejected natural replies (both agents, most calls).** C's guard accepted only a bare
   "yes" or the exact full name, so "Yes, this is Daniel" failed; D's treated single words such as "said" or "son"
   as exclusions ("I just said, that's me" failed) and could not proceed when the extractor omitted its typed
   event. After two attempts the call closed as unclear. The build guide had five accreted paragraphs demanding
   strict raw-text validation of this step.
2. **D's multipurpose event grammar was not produced by the hosted extractor**, so even full-name confirmations
   stalled; in the `corrects` run no call reached `verify_identity`.
3. **Security answers in pieces** ("44… 71") were not assembled; the agent re-asked from scratch and several calls
   hit the 420 s cap.
4. **Practice-brief habits leaked.** C-05 offered a transfer on hardship although Brief C forbids it; C-09
   transferred to `general` instead of the `support` queue Brief C names for charge questions. The guide contained
   A/B-specific wording (hardship transfer, no persuasion on hardship, text-message sentence).
5. One promise was recorded on the wrong date (C-06, `pieces`).
6. **Platform outages hurt the builder.** A Freya 504 on the dry-run sent a valid candidate back to model repair.

What worked once past the opening: new dates, floors, holidays, the no-retry rule and the new reason codes were
read from the brief; most promise cases passed.

## Fixes (branch `tau-hardening`)

- `ee23096` one permissive recipient rule with a natural-utterance self-test, simple phase-specific extraction for
  opening/security, accumulation of split security answers, no practice-brief defaults.
- `0f93051` transient Freya errors retried within the budget where a resend cannot duplicate a side effect.
- `7e2c329` difficult-caller rules mined from tau-bench (`research/tau-difficult-callers/`).
- `67c583f` unique temp names for state files (parallel builds crashed).
- `fdcec5b` a workflow create that timed out is adopted by its unique name or safely resent (a validated Brief A
  candidate was lost to a 504 in its last round).
- `5378491` six rounds by default with `--skip-tests` (a Brief A+B build stopped after 17 of 30 minutes).

C and D were used to find these failures, so they are no longer blind. A new blind brief is needed to measure
generalization of the fixes.
