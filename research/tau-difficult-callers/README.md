# Difficult callers mined from tau-bench

Sources (MIT licensed): sierra-research/tau-bench `59a200c6` (retail, airline) and sierra-research/tau2-bench
`4ce7c039` (retail, airline, telecom, banking_knowledge, plus the voice user-simulator guidelines).
3,231 tasks, 960 unique user scenarios after removing duplicate instructions. Each scenario was tagged against
`TAXONOMY.md` by four parallel model passes; every quote was checked to be a verbatim substring of its scenario.
Formulaic tau1 retail scripts (plain order actions) were tagged by rule and are rated low.

`catalog.json` keeps the 336 scenarios rated high (148) or medium (188) relevance for a collections call, with the
quote that shows the behaviour and how it would appear on our calls.

| Behaviour | high / all | Covered by kit styles before this |
|---|---:|---|
| Policy pressure: asks for an exception or discount, pushes back | 56 / 84 | no |
| Persists after a no, rephrases the same demand | 45 / 83 | no |
| False claim: "I just paid", "your colleague promised", "my dispute was approved" | 42 / 53 | no |
| Does not know or deflects a detail (e.g. date of birth) | 46 / 138 | no |
| Conditional fallback chain: split, partial, reduced, give up | 44 / 161 | partly |
| Changes mind or corrects, including at the confirmation step | 36 / 73 | partly (`corrects`) |
| Emotional pressure: anger, panic, deadlines | 65 / 145 | no |
| Will not say a security answer aloud | 22 / 54 | one case |
| Demands a person repeatedly (4 to 8 times) | 22 / 29 | one request only |
| Social engineering: "a supervisor gave me a bypass code" | 3 / 6 | no |
| Wants to end the call, call me later | 14 / 83 | no |
| Off-topic, chatty caller | 14 / 34 | yes (`talkative`, `asks_back`) |
| Gives values in pieces | 12 / 20 | yes (`pieces`) |
| Vague start: "some of those charges are wrong" | 6 / 36 | no |

The tau2 voice guidelines add spoken behaviour that our text personas lacked: fillers and self-restarts, digits
separated by commas, asides not meant for the agent ("hold on a second"), and "are you still there?" check-ins.

## How it is used

- The build guide (`competition/skills/build-phone-agent.md`, section "Difficult callers") turns these into general
  rules: claims are not records, identity only from the identity tool, pressure does not create offers, emotion does
  not override policy, a caller who must leave gets the callback/closing path, vague complaints get one clarifying
  question, and spoken asides are not answers.
- `run_cases_tau.py` runs the kit's unchanged `tools/run_cases.py` with two extra caller styles. Both change how the
  customer behaves, never the facts or the decisions in the case script, so the expected bank records stay valid:
  - `tau_pressure`: asks to skip security citing a supervisor, claims a previous agent promised to waive fees and asks
    twice, says it is in a hurry, sounds stressed.
  - `tau_voice`: fillers, self-restarts mid-value, comma-separated digits, one aside, one "are you still there?".

```sh
python3 research/tau-difficult-callers/run_cases_tau.py <agent_id> --brief A --style tau_pressure
python3 research/tau-difficult-callers/run_cases_tau.py <agent_id> --cases my-cases.json --style tau_voice
```
