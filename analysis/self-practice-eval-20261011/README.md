# Self-practice evaluation — 11 October 2026

## Why

Every Freya run scoring 80–100% came from a build that repaired against the same public cases; blind builds scored
30–60% and the first blind mock final 0/23 (`analysis/mock-final-20261011`). Final briefs have no test customers, so
`--self-practice` (commit `b1dde39`, branch `blend-13`) makes the builder write, audit and run its own practice
customers from the evidence, with loop detection feeding repairs.

## Public cases with the blend builder (tests on)

`blend-13` (`26eadb0`): build A and A+B with official test feedback, then an independent plain verification run.

| Agent | Builder's own rounds | Independent verification |
|---|---|---|
| blend-a (Brief A) | 7/10 → 10/10 | **9/10** (PUB-01: an extra callback was booked) |
| blend-b (A+B) | rejected by coverage gate → 1/3 → 2/3 | **3/3** |

Median slowest agent turn 7 s (valid run). `results-blend-13/`.

## Blind comparison on unseen briefs E and F

A separate agent that never saw builder code wrote `briefs/brief-e.md` (clean spec) and `briefs/brief-f/` (raw
material: email, policy, amending memo with decoys, code list; up to three products), plus hidden cases
`cases-e.json` (10) and `cases-f.json` (13) with `answer-key.md`, re-derived in a second pass. Each method built once,
one build at a time; each agent then ran the hidden cases three times (plain, talkative, pieces).

| Brief | Method | Calls passing (reason-adjusted) | Calls passing (official) | **Cases passing all 3 runs** |
|---|---|---:|---:|---:|
| E | `--skip-tests` | 22/30 | 7/30 | **6/10** |
| E | `--self-practice` | 16/30 | 7/30 | **3/10** |
| F | `--skip-tests` | 13/39 | 4/39 | **1/13** |
| F | `--self-practice` | 27/39 | 13/39 | **4/13** |

*Reason-adjusted*: the hosted mock only accepts Brief A/B close reasons, so a `close_call` rejected solely for an
unknown reason code counts with the agent's own outcome and reason (`simulate.py --adjust-reasons`). No platform
stalls were detected in these runs (`classify_stalls.py`: no engine event after the caller's first reply).

Reading:
- On F, the raw-material type that was hardest all day, self-practice more than doubled passing calls and pass^3.
- On E it lost. Its own practice test found a date-of-birth loop (38 repeats) but the repair started with two minutes
  left and timed out, so the looping version stayed live. The late-repair guard (`a8ede8c`) came after this build;
  the F self-practice build ran with it.
- One build per method per brief: a direction, not a verdict. Builds of the same builder vary a lot.
- 30 minutes is tight for self-practice (build ~10 min, each practice round 5–8 min in a shared Freya queue), so most
  runs got one or two repairs.

## Builder findings from these runs

- Self-practice found real defects no plain persona triggers: a "can we skip the security questions?" request
  closed the call as declined (repaired: 0/8 → 5/8 on the same cases); spoken date-of-birth and birth-year loops.
- Fixed during the evaluation: keep the published candidate when a practice test times out (`49c1f0d`); no repair
  in the last five minutes when a tested candidate is live (`a8ede8c`).
- An orphaned simulation from a timed-out build blocked the shared workspace; `POST /api/v2/simulations/{id}/cancel`
  (undocumented) cancels it.

## Next

Smaller train sets (5–6) so more repair rounds fit; repeat the E/F comparison to separate method from build variance.
