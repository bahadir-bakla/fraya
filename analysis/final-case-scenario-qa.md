# Final-case scenario source and parser QA

Offline status: **PASS**. 12 scenarios, 68 condition checks, 14 parser/handoff probes. No live simulation run.

First batch: FC-01 through FC-05. Personas are in exact platform envelope format. Variables remain an unbound template until the parent binds returned persona IDs.

| Scenario | Fixture customer | now | Primary branch | QA |
|---|---|---|---|---|
| FC-01 | 95004361 | 2026-10-12T10:30:00+03:00 | normal | PASS |
| FC-02 | 96158684 | 2026-10-12T10:30:00+03:00 | normal | PASS |
| FC-03 | 97526380 | 2026-10-12T10:30:00+03:00 | normal | PASS |
| FC-04 | 92460108 | 2026-10-12T10:30:00+03:00 | normal | PASS |
| FC-05 | 96158684 | 2026-10-12T10:30:00+03:00 | normal | PASS |
| FC-06 | 96125950 | 2026-10-12T10:30:00+03:00 | normal | PASS |
| FC-07 | 97631186 | 2026-10-12T10:30:00+03:00 | no-issued-statement | PASS |
| FC-08 | 95004361 | 2026-10-05T10:30:00+03:00 | same-cut-day | PASS |
| FC-09 | 95004361 | 2026-10-16T10:30:00+03:00 | past-due | PASS |
| FC-10 | 92311921 | 2026-10-12T10:30:00+03:00 | credit-negative | PASS |
| FC-11 | 92030487 | 2026-10-12T10:30:00+03:00 | card-collision | PASS |
| FC-12 | 92335586 | 2026-10-12T10:30:00+03:00 | email-service-error | PASS |

The catalog embeds actual expected POST data, exact original fixture HTTP statuses and bodies, fixture pointers, every Turkish conditional turn, and immutable business checks. It uses no practice PUB fixtures or ledger scoring.

Source limitations:

- No phone agent, mock endpoint, or Freya simulation was called. PASS means offline source/fixture/schema/script consistency only.
- Annual-right eligibility flag is absent from the service contract and fixtures; no used-right fixture or precheck has been invented.
- All final fixtures have automaticPaymentFlag N; positive delayed automatic-payment branch is not fixture-testable.
- FC-05 retains the documented example-vs-policy routing conflict; it is not weakened to make a workflow pass.
- Masked card middle digits do not exist. FC-11 does not claim full-number/last-six matching success coverage.

Parent handoff: create personas from `analysis/final-case-personas.json`, save the response locally, then run `python -X utf8 analysis/final-case-scenario-qa.py --bind SAVED_RESPONSE_PATH`. Use returned IDs and matching `customerNumber`/`now`; never use names as IDs.

Each condition and its source/fixture/script validation reason is in `final-case-scenario-qa.json`; the full source hashes are in `final-case-scenario-catalog.json`.
