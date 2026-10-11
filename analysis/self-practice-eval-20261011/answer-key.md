# Mock final 2: answer key

`now` = Wednesday 2026-10-14 11:00 for every case. Rule references: Brief E uses `E1`..`E50`. Brief F uses `2:x.y` for a section of 02-policy-extract (ACS-7), `Mn` for item n of 03-memo-amendment (CM-2026-19), and "code list" for 04-code-list.

The hosted mock checks `close_call.reason` against the Brief A/B table, so it will reject every E/F reason code below. Score those cases by hand on reason (the ledger fields are unaffected).

## Calendars

| Date | Day | Brief E | Brief F |
|---|---|---|---|
| 10-15 | Thu | bd 1 | bd 1 |
| 10-16 | Fri | **holiday** | bd 2 |
| 10-19 | Mon | bd 2 | bd 3 |
| 10-20 | Tue | bd 3 | **holiday** (Founders' Day) |
| 10-21 | Wed | bd 4 = **stage-2 deadline** | bd 4 |
| 10-22 | Thu | bd 5 | bd 5 = **10-30 days deadline** |
| 10-23 | Fri | bd 6 | **holiday** (memo item 2) |
| 10-26 | Mon | bd 7 | bd 6 |
| 10-27 | Tue | bd 8 | bd 7 |
| 10-28 | Wed | **holiday** | bd 8 |
| 10-29 | Thu | bd 9 = **stage-1 deadline** | bd 9 |
| 10-30 | Fri | bd 10 | bd 10 = **1-9 days deadline** |

- E: stage 1 (1-10 days) is the 9th business day = **29 Oct**. Stage 2 (11-24) is the 4th = **21 Oct**. Stage 3 (25+) has no promise. Callback days: 15 or 19 Oct.
- F: 1-9 days is the 10th business day = **30 Oct** (29 Oct without memo item 2). 10-30 days is the 5th = **22 Oct**. 31-60 days is the 2nd = 16 Oct (unused). Memo item 7 (new deadlines) only starts 2 Nov, so it does not apply. Callback days after the memo: 15 or 16 Oct, 09:00-18:00.

## Floors

- E (E27): ceil(past_due / 2) for every type. PUB-01 210, PUB-02 156, PUB-03 48, PUB-04 625, PUB-05 390, PUB-06 1063, PUB-07 270, PUB-08 90, PUB-10 183.
- F (2:8.2 + M3): card = minimum_payment, personal loan = instalment, car finance = full past_due.

---

## Brief E

**E-01 PUB-01 Daniel Reyes, card 420, 6 days late.** Confirms name (E2-E3). Phone digits first, then DOB (E12), both pass, then get_account (E17) and the disclosure (E18). 6 days is stage 1: deadline 29 Oct, 2 attempts (E19, E21). First ask about today (E31) gets a flat no, which uses an attempt (E33). Attempt 1: full 420 on 29 Oct, refused. Attempt 2: floor 210 on 29 Oct, accepted (E27, E33). Read-back and yes (E37), create_promise ok, reference and email sentence (E40). Close `promise`.
Ledger: promise p1 210.00 on 2026-10-29. No notes, callbacks or transfers.

**E-02 PUB-02 husband (third party).** E6: no reason given, no verification. "Tomorrow" is Thu 15 Oct, the next business day, so the day is allowed (E7). 12:30 falls in the lunch gap, so the agent offers 14:00 (E8). He accepts and the agent books it. Close `not_reached` / `CB`.
Ledger: callback 2026-10-15 14:00.

**E-03 PUB-03 Owen Park.** Phone 6603 is wrong (1). Re-asked: 6630 is right (E13). DOB 21 July 1991 is wrong (2). Two wrong answers in total end the check (E13). No disclosure; he is told to call the number on his card or statement (E15). Close `not_verified` / `IDF`. (An agent that allows three strikes re-asks the DOB, gets the right answer and fails the case.)
Ledger: no promises, notes, callbacks or transfers.

**E-04 PUB-04 Lena Hoffmann, car 1250, 14 days.** Stage 2: deadline 21 Oct. Not today. 6 Nov is after the deadline (E24; E25 gives the same result), so the agent offers 21 Oct and she accepts, at the full amount. Robot question: E4. Close `promise`.
Ledger: p1 1250.00 on 2026-10-21.

**E-05 PUB-05 Tomas Novak, personal loan 780, 21 days.** Stage 2, so E20 does not apply. Job loss triggers E35: one sentence of sympathy, no attempt, no transfer offer, add_note hardship (E48). Close `no_promise` / `HARD`.
Ledger: note p1 hardship.

**E-06 PUB-06 Priya Nair, card 2125.10, 12 days.** Stage 2: deadline 21 Oct. Floor = ceil(1062.55) = 1063 (E27; minimum 637.50 is ignored). She says "too much" and offers 800 on Mon 19 Oct. 800 is below the floor (E30), so the agent offers 1063 on the named date, which is valid (E29, E22), and says the rest remains overdue. She accepts. Close `promise`.
Ledger: p1 1063.00 on 2026-10-19.

**E-07 PUB-07 Samuel Ortiz, personal loan 540, 5 days.** Stage 1: deadline 29 Oct. "Next Friday" is the first Friday after today (E26), 16 Oct, which is a holiday and not after the deadline. So the agent offers the business day before it, Thu 15 Oct (E23). He accepts. Close `promise`.
Ledger: p1 540.00 on 2026-10-15.

**E-08 PUB-08 Hannah Schmidt, card 180.** Already paid (E42): the agent asks the date, and she says Fri 9 Oct. The two business days before today are 13 and 12 Oct, so 9 Oct is older. The agent transfers to support and adds no note (E48). Close `transferred` / `SUPP`.
Ledger: transfer support.

**E-09 PUB-09 Victor Ionescu, personal loan 2100, 28 days.** Stage 3 (E19). E20 comes first: the agent states the balance (E18), takes no promise although he offers Friday, and transfers to restructuring. Close `transferred` / `RSTR`.
Ledger: transfer restructuring.

**E-10 PUB-10 Grace Lin, card 365, 8 days.** Stage 1: deadline 29 Oct. 22 Oct at the full amount is valid. Read-back and yes. The first create_promise fails (mock fault). E41: no retry, tell her it could not be recorded, add_note service_error. Close `no_promise` / `SVC`.
Ledger: no promise; note p1 service_error.

---

## Brief F

**F-01 PUB-11 Sofia Almeida: card 220/9d, personal loan 640/9d, car 75/3d.** Order by days late (M5): card 9, then loan 9 (a tie, so get_account order), then car 3. ACS-7 6.3 would order loan, card, car; the memo replaces it. All deadlines are 30 Oct. Not all today (2:9.1).
- Card: she names 23 Oct, a memo holiday not after the deadline, so the agent offers the next business day, Mon 26 Oct (M2, 2:7.4). She accepts. Read-back, yes, create_promise p1 220 (2:10.1).
- Loan: "too much", so the agent offers the floor 213 once and says the remainder stays in arrears (2:8.3). She takes it for 30 Oct. Read-back, yes, create_promise p2 213.
- Car: she offers 25. The floor is 75 (M3). Below the floor, so the agent offers 75 once, she refuses, and the account ends with note p3 refused and no more attempts (2:8.4, 2:10.6).
- Close `promise` (2:12.2). App sentence (M6).

Ledger: p1 220.00 on 2026-10-26, p2 213.00 on 2026-10-30, note p3 refused.

**F-02 PUB-12 Marcus Bell: card 510/16d, personal loan 1320/16d, car 140/7d.** DOB right. Phone 4401 is wrong, re-asked, and 4410 is right (2:5.2). Order: card, loan (tie, get_account order), car (M5). Not all today.
- Card: dispute (2:11.2). No argument, the agent says a disputes specialist will write, note p1 dispute at once.
- Loan: deadline 22 Oct. Flat refusal, one loan attempt: floor 440 on 22 Oct (2:9.3). Refused, so note p2 refused (2:9.4).
- Car: he asks for lower monthly payments, so the agent transfers to restructuring (2:11.3). Notes already written stay and no note is written for p3 (2:10.6).
- Close `transferred` / `XRS`.

Ledger: notes p1 dispute and p2 refused, transfer restructuring. (Under Brief B, which forbids notes on a transfer, this would differ.)

**F-03 PUB-13 Elena Rossi: card 300/4d, personal loan 900/20d.** Order by days late: loan 20 first, then card 4 (M5). Not both today.
- Loan: deadline 22 Oct. She takes 22 Oct at the full amount. Read-back, yes, and create_promise p2 straight away, before the card (2:10.1).
- Card: she mentions her own illness. M4 replaces 2:9.5: one sentence of sympathy, no persuasion, transfer to support without asking, no further notes.
- The recorded promise stays. Transferred overrides promise (2:12.2). Close `transferred` / `XSP`.

Ledger: p2 900.00 on 2026-10-22, transfer support, no notes.

**F-04 PUB-01 Daniel Reyes, card 420/6d.** Deadline 30 Oct (M2 moves it from 29 Oct). Not today. The day question (2:9.2) gets "can't pay at all", a flat refusal. Card has two attempts (2:9.3). Attempt 1: full 420 on 30 Oct, refused. Attempt 2: floor 126 on 30 Oct, accepted. Read-back, yes, record, app sentence (M6). Close `promise`.
Ledger: p1 126.00 on 2026-10-30.

**F-05 PUB-02 husband (third party).** No disclosure (2:4.1). 19:00 today is not allowed after M1 (no same-day callbacks, latest 18:00), so the agent asks once more (2:4.3). Thu 15 Oct 17:30 is allowed, so it is booked. Close `not_reached` / `RCB`.
Ledger: callback 2026-10-15 17:30.

**F-06 PUB-03 Owen Park.** DOB 1990-07-21 is wrong and is asked again. 1991-07-21 is the second wrong answer on the same question, so verification fails (2:5.2). The phone question is never asked. No disclosure, plus the statement/branch advice (2:5.4). Close `not_verified` / `VFL`.
Ledger: none.

**F-07 PUB-04 Lena Hoffmann, car 1250/14d.** Deadline 22 Oct. Not today. She offers 400 on 22 Oct. The car floor is 1250 (M3), so the agent says 400 cannot be recorded and offers 1250 once (2:8.4). She accepts for 22 Oct. Close `promise`.
Ledger: p1 1250.00 on 2026-10-22.

**F-08 PUB-05 Tomas Novak.** He confirms his name, then refuses the DOB and asks what the call is about. The agent explains once (2:5.5). He refuses again. Close `not_verified` / `VDC`. verify_identity is never called and nothing is disclosed (2:3.1).
Ledger: none.

**F-09 PUB-06 Priya Nair, card 2125.10/12d.** Deadline 22 Oct. Not today. Day question: "too much", so the agent offers the floor 637.50 once and says the remainder stays in arrears (2:8.3). She accepts and says "next Friday". 2:7.7 makes that the following calendar week, so 23 Oct, which is after the deadline (and a holiday). 2:7.5 applies: offer 22 Oct, which she accepts. Close `promise`.
Ledger: p1 637.50 on 2026-10-22.

**F-10 PUB-07 wrong number.** 2:4.4. Close `not_reached` / `RWN`. No other tools.
Ledger: none.

**F-11 PUB-08 Hannah Schmidt.** Already paid (2:11.1): the three-business-days sentence and note p1 paid (2:10.6). Every account is noted paid, so close `paid` with no reason code (2:12.3).
Ledger: note p1 paid.

**F-12 PUB-09 Victor Ionescu.** After disclosure he asks for a person. The agent asks once whether it can help (2:11.4). He insists, so the agent transfers to general. No account was finished, so there are no notes. Close `transferred` / `XHU`.
Ledger: transfer general.

**F-13 PUB-10 Grace Lin, card 365/8d.** Deadline 30 Oct. Not today. 20 Oct is Founders' Day and not after the deadline, so the agent offers the next business day, 21 Oct (2:7.4). She accepts. Read-back, yes. The first create_promise fails, the agent retries once and it returns ok (2:10.4). Only then does it say "recorded". App sentence. Close `promise`.
Ledger: p1 365.00 on 2026-10-21.

---

## Second-pass record

The second pass re-derived every case without using the rationale fields. A Python validator (`_tools/mf2_validate.py`) recomputed the deadlines, floors, callback windows and enums from the calendars above, and byte-compared the facts with public-test-set.json. It found no errors.

One fix came out of this pass. F-03 originally said "her husband has been in hospital". Whether a relative's illness counts under M4 was ambiguous, so the script now says she was ill herself.
