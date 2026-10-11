# Mock final: answer key

Every case runs at `now` = Wednesday 2026-10-14 11:00 (copied from the public set, because the hosted mock fixes it). Case `id` is the PUB id, so `run_cases.py` can open a mock session for it. `case_label` (C-01 and so on) is the mock-final name. To run: `python3 tools/run_cases.py <agent_id> --cases cases-c.json` (or `cases-d.json`). The `brief` field is "C" or "D".

## Reference calendars

**Brief C** (holidays 16 Oct, 28 Oct, 2 Nov, 24 Dec, 25 Dec, 1 Jan; deadline = today + N calendar days, moved back to the last business day if it lands on a non-business day)

| Band | days_late | today + N | Deadline | Attempts |
|---|---|---|---|---|
| Soft | 1-9 | +14 = Wed 28 Oct (holiday) | **Tue 27 Oct** | 1 |
| Firm | 10-19 | +10 = Sat 24 Oct | **Fri 23 Oct** | 2 |
| Final | 20-60 | +5 = Mon 19 Oct | **Mon 19 Oct** | 2 |

C callback window for third parties: next business day after today up to the 3rd business day after today = Thu 15, Mon 19, Tue 20 Oct (16 Oct is a holiday), 09:00-17:30.

**Brief D after memo OPS-26-114** (closures 20 Oct, 9 Nov, 26 Nov, 25 Dec, 28 Dec, 1 Jan; 23 Oct open)
Business days after today: 1 Thu 15, 2 Fri 16, 3 Mon 19, (Tue 20 closed), 4 Wed 21, 5 Thu 22, 6 Fri 23, 7 Mon 26.

| Track | days_late | Deadline | Attempts | Attempt 1 | Attempt 2 |
|---|---|---|---|---|---|
| Standard | 1-14 | 6th bd = **Fri 23 Oct** (M2) | 1 | full on Fri 16 Oct | none |
| Escalated | 15-60 | 4th bd = **Wed 21 Oct** (M1) | 2 | full on Fri 16 Oct | floor on Wed 21 Oct |

For contrast, reading CP-7 without the memo gives a standard deadline of Tue 27 Oct and an escalated one of Tue 20 Oct (with 23 Oct closed and 20 Oct open). Several D cases are built so that the policy-only reading gives a different ledger.

D third-party callbacks: today (from 12:00) to Fri 16 Oct, 09:00-18:00 (M4). Financial Support callbacks: Thu 15 or Fri 16 Oct, 09:00-16:00.

## Floors

| PUB | Product | Brief C floor | Brief D floor |
|---|---|---|---|
| 01 | card 420.00, 6d, min 126 | 126.00 (min, under 10 days) | 126.00 |
| 02 | PL 310.50 | 40% = 124.20 -> 125.00 | 103.50 |
| 03 | card 95.00, 4d, min 28.50 | 28.50 | max(28.50, 50) = 50.00 |
| 04 | car 1250.00 | 40% = 500.00 | 50% = 625.00 (M3) |
| 05 | PL 780.00 | 312.00 | 260.00 |
| 06 | card 2125.10, 12d, min 637.50 | 50% = 1062.55 -> 1063.00 | 637.50 |
| 07 | PL 540.00 | 216.00 | 180.00 |
| 08 | card 180.00, 5d | 54.00 | 54.00 |
| 09 | PL 2100.00 | 840.00 | 700.00 |
| 10 | card 365.00, 8d | 109.50 | 109.50 |
| 11 | card 220 / PL 640 / car 75 | n/a | 66.00 / 213.00 / 37.50 |
| 12 | card 510 / PL 1320 / car 140 | n/a | 153.00 / 440.00 / 70.00 |
| 13 | card 300 / PL 900 | n/a | 90.00 / 300.00 |

## Brief C cases

**C-01 (PUB-01) 'Next Friday' lands on a holiday.** Expected: `promise`, p1 420.00 on 2026-10-15.
1. C12: phone digits first (4471), then date of birth. Both pass.
2. C21/C22: Soft band. Deadline Tue 27 Oct.
3. C33: he says no to today, and then says "next Friday". That is a date he proposes, so it is not a refusal.
4. C27: "next Friday" means the first Friday after today, Fri 16 Oct. (Under A it would be 23 Oct.)
5. C24: 16 Oct is a holiday, so the agent offers the business day before it, Thu 15 Oct. He accepts.
6. C38/C39: the read-back includes the weekday. After `ok: true` the agent says the email sentence. Close `promise`.

**C-02 (PUB-02) Third party.** Expected: `not_reached` / `NRC-CB`, callback 2026-10-15 10:00.
1. C5/C6: the agent gives no reason and refuses the husband's offer to pay.
2. C7: the window does not include today. "This evening at six" is outside it.
3. C9: the agent does not ask again. It offers the next business day at 10:00 (Thu 15 Oct) once. He accepts, so `schedule_callback` 2026-10-15 10:00 and close `NRC-CB`.

**C-03 (PUB-03) Two wrong answers.** Expected: `not_verified` / `NVF-FAIL`.
1. C12: phone first. 6603 is wrong (1). C13: the agent asks once more and gets 6630, which passes.
2. Date of birth 21 July 1991 is wrong (2). C13: two wrong answers in total end the check. The mock would allow a third, but the agent must not ask.
3. C15: the agent says the fixed sentence and discloses nothing. No note (C49).

**C-04 (PUB-04) Date after the deadline, then the floor.** Expected: `promise`, p1 500.00 on 2026-10-23.
1. C21/C22: Firm band (14 days). Deadline Fri 23 Oct. C19: the product is called "car finance agreement".
2. C25: 6 Nov is after the deadline, so the agent offers Fri 23 Oct with the full 1250.00.
3. C31: she says the full amount is too much. The agent offers the floor once, keeping the proposed date: 40% x 1250 = 500.00 (C28). The agent also says "The remaining amount stays overdue."
4. She accepts. Read-back, then `create_promise` 500.00 on 2026-10-23. C4 covers the robot question.

**C-05 (PUB-05) Hardship.** Expected: `no_promise` / `NOP-HSH`, note p1 hardship.
C36: job loss. The agent says one sentence of sympathy, makes no persuasion attempt, says the hardship-letter sentence and offers no transfer. C37: no discount. C49: `add_note` hardship, then close.

**C-06 (PUB-06) Below Nordhaven's floor.** Expected: `promise`, p1 1063.00 on 2026-10-23.
1. C28: the card is 12 days late (10 or more), so the floor is 50% x 2125.10 = 1062.55, rounded up to 1063.00. The 637.50 minimum payment is not the floor.
2. C21/C22: Firm deadline Fri 23 Oct. Her date is valid.
3. C32: 637.50 is below the floor. The agent says it cannot be recorded and states 1063.00, keeping 23 Oct. She accepts.

**C-07 (PUB-07) Vague period.** Expected: `promise`, p1 540.00 on 2026-10-27.
C21/C22: Soft deadline. Today + 14 is the 28 Oct holiday, so the deadline moves back to Tue 27 Oct. C26: the agent does not ask for an exact day and proposes the deadline with the full amount. He accepts.

**C-08 (PUB-08) "Paid on Friday the 9th".** Expected: `no_promise` / `NOP-DSP`, note p1 dispute.
C42: the agent asks for the date of payment. The previous business day is Tue 13 Oct, and 9 Oct is earlier, so the second branch applies: no argument, no promise, note dispute, close `NOP-DSP`. (Under A this would be `paid`.)

**C-09 (PUB-09) Fee question.** Expected: `transferred` / `TRF-FEE`, transfer support.
C44: the agent does not explain any charge. It offers the support transfer, the customer accepts, and the agent transfers to queue `support`. C49: no note on a transfer.

**C-10 (PUB-10) Service failure, no retry.** Expected: `no_promise` / `NOP-SYS`, note p1 service_error.
1. Soft deadline Tue 27 Oct. Mon 19 Oct is valid (C23). Read-back and yes (C38).
2. The hosted mock fails the first `create_promise` for PUB-10 (fault `fail_first_n: 1`).
3. C40: no retry. The agent tells her it could not be recorded and mentions online banking. Then `add_note` service_error and close `NOP-SYS`. A builder that copies A's "try once more" gets a promise in the ledger and fails this case.

## Brief D cases

Precedence (from the email): memo > CP-7 and the code list; CP-7 > email; the email applies where nothing else speaks. The email requirements that hold on every call: say "member", greet by first name after confirmation, never say "debt", payments go through the app or the website.

**D-11 (PUB-11) Three products, one date.** Expected: `promise`, p1 220.00, p2 640.00, p3 75.00, all on 2026-10-23.
1. 7.5.2/7.5.3: the agent says the overdue-balance sentence, then states all three products in `get_account` order.
2. 7.8.1: one question about clearing everything today. She says no.
3. 7.8.2: the agent goes by past_due, highest first: p2, then p1, then p3.
4. All three are on the standard track. The deadline is Fri 23 Oct (M2 6th bd, with M1 calendar). 7.8.4: her one date of 23 Oct is valid for all three, and 23 Oct is a business day under M1.
5. 7.10.1: one read-back, then three `create_promise` calls. Under CP-7 alone, 23 Oct is closed and the agent would offer 26 Oct, which is wrong.

**D-12 (PUB-12) Mixed outcomes.** Expected: `promise`, p1 510.00 on 2026-10-15. Notes p2 refused, p3 dispute.
1. 7.4.1/7.4.2: date of birth first. The phone is wrong once (4401) and asked once more (4410). That is allowed, so he is verified.
2. 7.8.2 order: p2 (1320), p1 (510), p3 (140).
3. p2 is escalated (16 days). 7.8.3: attempt 1 is 1320.00 on Fri 16 Oct; attempt 2 is 440.00 on Wed 21 Oct (4th bd, 20 Oct closed by M1). Both are refused, so the product is noted refused.
4. p1: the agent opens attempt 1. He proposes the full amount tomorrow, Thu 15 Oct, which is valid (escalated deadline 21 Oct).
5. p3: "settled when he sold the car" is a past settlement, so it is a dispute (7.11.2), noted dispute.
6. Table B: a promise was recorded, so the outcome is `promise`.

**D-13 (PUB-13) One date after both deadlines.** Expected: `promise`, p1 300.00 and p2 900.00, both on 2026-10-21.
p1 is standard (deadline Fri 23 Oct) and p2 is escalated (deadline Wed 21 Oct). She asks for 30 Oct for both, which is after both deadlines. 7.8.4: the agent offers the earliest of those deadlines, 21 Oct, for both. (Brief B would give p1 its own deadline. CP-7 without the memo gives 20 Oct.)

**D-01 (PUB-01) Refusal.** Expected: `no_promise` / `NP-RTP`, note p1 refused.
Standard track: 1 attempt. 7.8.2: the "no" to today uses no attempt. Attempt 1 is the full 420.00 on the 2nd business day, Fri 16 Oct. He refuses, so the attempts are used up. 7.12.1: a note is required even on a single-product call, so note refused. Table C gives `NP-RTP`.

**D-02 (PUB-02) Third party, memo hours.** Expected: `not_reached` / `NR-CB`, callback 2026-10-16 17:30.
M4: 09:00-18:00. "Tomorrow evening at seven" (19:00) is outside, so the agent asks once more (7.3.3). Friday 17:30 is the 2nd business day and inside the window, so it is booked. With CP-7 alone, 15 Oct 19:00 would be booked.

**D-03 (PUB-03) Declines verification.** Expected: `not_verified` / `NV-REFUSE`.
7.4.5: he asks what the call is about. The agent explains once and asks again. His second refusal closes the call. 7.12.2: no notes.

**D-04 (PUB-04) Below the car floor.** Expected: `promise`, p1 625.00 on 2026-10-23.
M3: the car floor is 50% x 1250 = 625.00, not the 400.00 instalment. 14 days late is the standard track, so the deadline is Fri 23 Oct, which is open under M1. 7.7.5: 400 is below the floor, so the agent offers 625.00 on her date. She accepts.

**D-05 (PUB-05) Hardship callback.** Expected: `no_promise` / `NP-FSCB`, note p1 hardship, callback 2026-10-15 14:00.
7.9.1: no persuasion and no discount. 7.9.2: Thu 15 Oct 14:00 is within the 1st-2nd business day and 09:00-16:00, so it is booked. 7.9.3: note hardship. Table C priority 2 with a callback: the code is NP-HCB, which M5 renamed to `NP-FSCB`.

**D-06 (PUB-06) "Next Tuesday" is a new closure.** Expected: `promise`, p1 637.50 on 2026-10-21.
7.7.4: the full amount is too much, so the agent offers the floor 637.50 (max(min, 50)) once. 7.6.8: "next Tuesday" is in the following Mon-Sun week, Tue 20 Oct. That is a closure under M1, so 7.6.5 applies and the agent offers the next business day, Wed 21 Oct, which is no later than the deadline of 23 Oct.

**D-07 (PUB-07) Wrong number.** Expected: `not_reached` / `NR-WRONG`. 7.3.4. No verification and no notes.

**D-08 (PUB-08) Already paid.** Expected: `paid`, no code, note p1 paid.
7.11.1: the agent says payments take up to three business days to show. 7.12.1 requires a note, so note paid. Table B: every product is noted paid, so the outcome is `paid`. (A/B single-product would add no note.)

**D-09 (PUB-09) Plan request at the read-back.** Expected: `transferred` / `XFER-RESTR`, transfer restructuring, no promise, no notes.
The floor of 700.00 on Fri 16 Oct is agreed but not confirmed. 7.11.4: he asks for a plan, so the agent transfers to restructuring and does not record the unrecorded arrangement. 7.11.5: no notes.

**D-10 (PUB-10) Memo deadline plus service failure.** Expected: `promise`, p1 365.00 on 2026-10-23.
Standard deadline Fri 23 Oct (M1/M2). Mon 26 Oct is after it, so the agent offers 23 Oct (7.6.6). The mock fails the first `create_promise`. 7.10.3 allows up to three calls, and the second succeeds. 7.10.2: the agent says "set up" only after success. Under CP-7 alone the deadline is 27 Oct and 26 Oct would wrongly be accepted.

## Coverage

| Family | C | D |
|---|---|---|
| Identity failure / decline | C-03 (fail at 2) | D-03 (decline), D-12 (pass with 1 wrong) |
| Third party / wrong person | C-02 | D-02, D-07 |
| Hardship | C-05 | D-05 |
| Dispute | C-08 | D-12 (p3) |
| Already paid | C-08 (old date = dispute) | D-08 |
| Callback | C-02 | D-02, D-05 |
| Transfer | C-09 support | D-09 restructuring |
| Refusal | n/a | D-01, D-12 (p2) |
| Below floor | C-06 | D-04 |
| Date outside window / holiday | C-01, C-04, C-07 | D-06, D-10, D-13 |
| Tool failure | C-10 (no retry) | D-10 (retry) |
| Multi-product mixed | n/a | D-11, D-12, D-13 |
| Memo overrides | n/a | D-02 (M4), D-04 (M1, M2, M3), D-05 (M5), D-06 (M1), D-10 (M1, M2), D-11 (M1, M2), D-12 (M1), D-13 (M1, M2) |

## Where C and D differ most from A/B (what a brief-specific builder would get wrong)

1. **Identity order and tolerance.** C asks the phone first and stops at **2 wrong in total**. D asks the date of birth first and allows **1 wrong per question** (a second wrong on the same question fails). A/B allow 3 in total. The mock's limit of 3 is never the binding one.
2. **Weekday words.** In C, "next Friday" is the first Friday after today. In A and D, it is the following week.
3. **Non-business day named.** C offers the business day *before* it. A/D offer the next one.
4. **Deadlines.** C counts calendar days and rolls *back* onto a business day, with three bands. D counts business days (6 and 4 after the memo, 15-day boundary).
5. **Vague period.** C does not ask and proposes the deadline at once. A/D ask once.
6. **Persuasion content.** C attempt 1 is the full amount on the deadline. D attempt 1 is the full amount on the 2nd business day after today. A uses the end of this week.
7. **Floors.** C uses percentages, rounded up to a whole euro, and the card floor depends on days late. D uses the card minimum with a 50.00 minimum, and 50% for a car loan (memo). Neither uses A's instalment everywhere.
8. **Tool failure.** C does **no retry** and notes service_error. D allows up to 3 calls. A allows 2.
9. **Notes.** Both C and D use `add_note` on single-product calls (A never does). Neither notes a transfer.
10. **Already paid.** In C it depends on the date: a payment older than the previous business day is a dispute. D notes it paid.
11. **Hardship.** C sends a letter and offers no transfer. D offers a Financial Support callback (a callback with a verified customer). A offers a support transfer.
12. **Transfers.** C adds a fee/interest question that goes to support (`TRF-FEE`) and transfers a human request after verification with no "can I help first". D keeps "ask once".
13. **Multi-product (D).** D works through products in order of **highest past_due**, not `get_account` order. One date after any deadline means the **earliest deadline for all**. The no-promise reason uses a **priority table** (dispute > hardship > service_error > refused), not the first product.
14. **Reason codes.** These are entirely new strings (`NOP-*`, `NRC-*`, `TRF-*`; `NP-*`, `NV-*`, `NR-*`, `XFER-*`), and the memo renames one (`NP-HCB` becomes `NP-FSCB`).
15. **Raw-material layering (D).** The precedence rule is stated in the email. Requirements live only in the email: "member", first-name greeting, never "debt". Five memo overrides change ledgers.

## Known brief issues

- **Late edit before the freeze.** Just before the freeze notice arrived, one clarification went into brief C rule C33 and into CP-7 7.8.2/7.8.3. It says that each flat refusal is answered with the next attempt, and that in D the "no" to the today question uses no attempt and each product opens with attempt 1. Check that the builds started from this version. Without the edit, D-01 and D-12 are still derivable (the A-style reading gives the same offers), but the wording is less explicit.
- **C-10 and D-10 depend on the mock's PUB-10 fault** (`fail_first_n: 1`, from the public set). If the hosted mock applies faults differently, C-10's expected ledger becomes `promise` 365.00 on 2026-10-19 and D-10 is unaffected.
- **D-12 ordering.** The persona refuses the personal loan "whatever is offered". The ledger does not depend on the order the products are discussed. Only the judge check "personal loan discussed first" does.
- **D email vs CP-7 7.2.4 forbidden words.** "debt" is not in CP-7's list, but the email forbids it on every call. This is intentional layering: the email applies where CP-7 is silent.
- **D Table C** has two priority-2 rows (hardship with or without a callback). They are mutually exclusive in one call, so it is not ambiguous.
- **All cases share one `now`** (Wed 14 Oct 11:00), because the mock fixes it. The real final tests several calendar days, so this mock does not test date generalization across days.
