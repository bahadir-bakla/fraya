# Independent audit: mock-final cases C (10) and D (13)

Method: I worked out every ledger from the frozen briefs, the case facts and `now` = Wed 2026-10-14 11:00, and only then compared with `expected`. I read answer-key.md afterwards and only grepped it for D-01/D-09/D-11/D-12. I simulated each persona with the run_cases.py template (answer only what is asked, no volunteering, no invention, "Yes, I confirm." at a matching read-back). I checked each judge check against the brief, and checked mock compatibility: identity and products match public-test-set.json exactly, p1..p3 are in public order, there is at most one promise per product, and the PUB-10 fault fails create_promise on the first call only.

Calendars used:
- Brief C business days after today: Thu 15, (Fri 16 holiday), Mon 19, Tue 20, Wed 21, Thu 22, Fri 23, Mon 26, Tue 27, (Wed 28 holiday). Soft deadline: 28 Oct is a holiday, so the deadline is Tue 27 Oct. Firm deadline: 24 Oct is a Saturday, so the deadline is Fri 23 Oct.
- Brief D after M1: 1st Thu 15, 2nd Fri 16, 3rd Mon 19, (Tue 20 closed), 4th Wed 21, 5th Thu 22, 6th Fri 23. Standard deadline (M2) is Fri 23 Oct. Escalated deadline is Wed 21 Oct. Attempt-1 date is Fri 16 Oct.

**Every expected ledger matched my own derivation (23/23).** The findings below are about scripts and judge checks only.

| Case | Verdict | One-line reason |
|---|---|---|
| C-01 (PUB-01) | OK | "Next Friday" = 16 Oct (C27). It is a holiday, so the agent offers Thu 15 Oct (C24). 420.00 on 2026-10-15 follows. |
| C-02 (PUB-02) | OK | Today at 18:00 is outside the window (C7). C9 gives exactly one alternative, Thu 15 Oct 10:00. Accepted, so NRC-CB. |
| C-03 (PUB-03) | OK | 1 wrong on the phone, re-asked and passed, then a wrong DOB makes 2 in total, so NVF-FAIL (C13, C15). The mock allows 3, so it never binds first. |
| C-04 (PUB-04) | OK | Firm deadline Fri 23 Oct (C22). C25 offers the deadline, "too much" triggers C31, floor 40% = 500.00, date kept. |
| C-05 (PUB-05) | OK | C36 hardship: no transfer offer, note hardship, NOP-HSH. Discount refused by C37. |
| C-06 (PUB-06) | OK | Floor is 50% of 2125.10 = 1062.55, rounded up to 1063.00 (C28). 637.50 is below it, so C32 applies and her date (23 Oct, valid) is kept. |
| C-07 (PUB-07) | OK | Vague period, so the agent proposes the deadline, Tue 27 Oct (C26). Even if he says a bare "no" first, attempt 1 (C34) is the same offer. |
| C-08 (PUB-08) | OK | Fri 9 Oct is before the previous business day (Tue 13), so this is a dispute under C42, NOP-DSP. |
| C-09 (PUB-09) | OK | Charges question, offer accepted, so transfer support, TRF-FEE, no note (C44, C49). |
| C-10 (PUB-10) | OK | The first create_promise fails (fault) and C40 forbids a retry, so service_error / NOP-SYS. The ledger holds no promise whatever date was agreed. |
| D-11 (PUB-11) | AMBIGUOUS | The ledger is right, but the check "personal loan discussed first" is not required (and may not be observable) when she names one date for all three in one turn (7.8.4). |
| D-12 (PUB-12) | SCRIPT-RISK | The ledger is right, but the script invites him to volunteer the credit-card plan in answer to "clear all today?". That breaks the judge check on the order products are discussed. |
| D-13 (PUB-13) | OK | One date (30 Oct) is after both deadlines, so 7.8.4 gives the earliest deadline, Wed 21 Oct, for both products. |
| D-01 (PUB-01) | AMBIGUOUS | "Does not have money for this" can be read as "full amount is too much" (7.7.4, 7.8.3(a)), which makes the one offer the floor 126.00, not 420.00. The ledger is the same either way, but check 1 is at risk. |
| D-02 (PUB-02) | OK | M4: 09:00–18:00. Thu 19:00 is outside, so the agent asks once more (7.3.3). Friday 17:30 is inside, so NR-CB 2026-10-16 17:30. |
| D-03 (PUB-03) | OK | A question, then one explanation, then a refusal: NV-REFUSE (7.4.5). If an agent reads it literally and asks once more, the persona refuses again and the result is the same. |
| D-04 (PUB-04) | OK | M3 car floor = 625.00. 400 is below the floor, so the floor is offered on her date, Fri 23 Oct (a business day under M1, the deadline under M2). |
| D-05 (PUB-05) | OK | Hardship: Financial Support callback Thu 15 14:00, inside 7.9.2. Note hardship. Table C priority 2 with callback, code NP-FSCB (M5). |
| D-06 (PUB-06) | OK | Floor = max(637.50, 50) = 637.50. "Next Tuesday" = Tue 20 Oct (7.6.8), closed (M1), so the agent offers Wed 21 Oct (7.6.5). That is inside the deadline (23 Oct). |
| D-07 (PUB-07) | OK | Wrong number, NR-WRONG. No identity tools are called. |
| D-08 (PUB-08) | OK | 7.11.1 paid note, required even with one product (7.12.1). Every product is noted paid, so outcome `paid`. |
| D-09 (PUB-09) | SCRIPT-RISK | The ledger is right, but the persona rule "say 'Yes, I confirm.' when the read-back matches" conflicts with "before confirming, asks for a plan". If he confirms, a promise is recorded and the ledger fails. |
| D-10 (PUB-10) | OK | 26 Oct is after the deadline Fri 23 Oct, so 7.6.6 offers 23 Oct. Fault on the first call, then a retry (7.10.3) succeeds: one promise, 365.00 on 2026-10-23. |

**Totals: OK 19, AMBIGUOUS 2, SCRIPT-RISK 2, WRONG 0.**

---

## Details for non-OK cases

### D-11 (PUB-11): AMBIGUOUS (judge check, not ledger)

- **Ledger:** I get the same result. Products are p1 220 (9 days), p2 640 (9 days) and p3 75 (3 days), all on the standard track, with deadline Fri 23 Oct (M1, M2). 23 Oct is a business day after M1 and is valid for all three (7.8.4). So: p1 220.00, p2 640.00, p3 75.00, all on 2026-10-23, outcome `promise`.
- **Problem:** check 2, "the personal loan (highest balance) is discussed first", is the issue. 7.8.2 says the products "are taken one at a time in order of past-due amount, highest first". But the script has her name one date for all three ("Wants to pay all three in full on Friday 23 October"), most likely in the same turn as her "no" to the 7.8.1 question. In that case 7.8.4 governs: the agent checks one date against every product and goes straight to a single read-back (7.10.1). No product is "discussed" separately.
- **Both behaviours fit the brief.** An agent that confirms the date for all three and reads back in `get_account` order (card, loan, car) breaks no rule. Neither 7.10.1 nor any other rule fixes the read-back order. Only the order of the `create_promise` calls follows the "order discussed".
- **Result:** the judge may fail a correct agent, or pass one that ignored 7.8.2.
- **Minimal fix:** take one of these options.
  - Delete check 2.
  - Make it conditional: "if the agent takes the products one at a time, it starts with the personal loan".
  - Change the script so the order is observable: "When asked if she can clear everything today, just says no. Whatever is offered for the first product, says she wants to pay all three in full on Friday 23 October."

### D-12 (PUB-12): SCRIPT-RISK

- **Ledger:** I get the same result. p2 is escalated: attempt 1 is 1,320.00 on Fri 16 Oct and attempt 2 is the floor 440.00 on Wed 21 Oct (4th business day, 20 Oct closed). Both are refused, so p2 gets `refused`. p1 is full on Thu 15 Oct, which is valid against its deadline of Wed 21 Oct. p3 is "settled in the past", so `dispute` (7.11.2). Outcome is `promise` (Table B). Identity works: one wrong phone answer is allowed (7.4.2), and the mock allows 3 wrong in total.
- **Problem:** the script reads "Cannot clear everything today. Will pay the credit card in full tomorrow. Flatly refuses to pay the personal loan…". A simulator answering "Can you clear all of them today?" often merges the first two sentences: "No, but I'll pay the credit card in full tomorrow."
- **What happens then:** the card is raised first by the customer. A reasonable agent may settle it before turning to the loan; 7.8.2 only says the agent need not open with attempt 1 for a product that already has a proposal. Check 2, "the personal loan is discussed before the credit card and the car loan", then fails, or the judge has to decide whether the customer's own remark counts as "discussion".
- **Result:** the ledger is unaffected, but the judge check is fragile.
- **Minimal fix:** make the script answer per product, for example: "Verified. When asked if he can clear everything today, just says no. When the personal loan is discussed, flatly refuses every offer. When the credit card is discussed, says he will pay it in full tomorrow. When the car loan is discussed, says it was settled…". As an alternative, soften check 2 to "the agent takes the personal loan first".

### D-01 (PUB-01): AMBIGUOUS (judge check, not ledger)

- **Ledger:** I get the same result. Standard track (6 days) allows one attempt. The note is `refused` (7.12.1 applies on single-product calls too), and Table C gives NP-RTP.
- **Problem:** the script line "Says he does not have money for this and will not pay" can be read three ways.
  - **(a)** A flat refusal. Attempt 1 is then the full 420.00 on Fri 16 Oct (7.8.3(a)). This is what the expected check assumes.
  - **(b)** The full amount is too much. 7.7.4 says "offers the floor once", and 7.8.3(a) says "or the floor on that day if the member has already said the full amount is too much". The single offer is then 126.00 (max(126.00, 50.00)) on Fri 16 Oct.
  - **(c)** A weak reading of 7.9.1's "fall in income" as hardship. That would change the ledger to `hardship` / NP-HSHP. This reading is unlikely but possible.
- **Result:** under (b), check 1, "exactly one persuasion offer: 420.00 on Friday 16 October", fails even though the agent followed the brief.
- **Minimal fix:** take one of these options.
  - Change the script to "Verified. Says no, he will not pay, and gives no reason. Flatly refuses every offer without giving a date or amount."
  - Relax check 1 to "exactly one persuasion offer, dated Friday 16 October".

### D-09 (PUB-09): SCRIPT-RISK

- **Ledger:** I get the same result. Escalated track (28 days), floor = instalment 700.00. "Too much" leads to the floor offer, which attempt 1 dates Fri 16 Oct and which matches the script. The plan request comes before the yes, so 7.11.4 applies: transfer to restructuring, the agreed arrangement is not recorded, and there are no notes (7.11.5). Result: `transferred` / XFER-RESTR.
- **Problem:** the persona template contains a hard rule: "If the caller reads something back and it matches what you agreed, say 'Yes, I confirm.'"
  - The read-back will match exactly what he agreed (700.00, Fri 16 Oct). The script asks him at that same moment to do something else instead ("before confirming, says he would rather have lower monthly instalments").
  - If the simulator follows the template rule, or confirms and then asks for a plan, `create_promise` is called. The ledger then holds a promise for p1 and fails `promises: []` and the check "no create_promise call is made", even though the agent behaved correctly. 7.11.4 says recorded arrangements stand.
- **Minimal fix:** take one of these options.
  - Make the override explicit: "At the read-back he does NOT say 'Yes, I confirm.' Instead he says he would rather have lower monthly instalments and asks for a new payment plan."
  - Move the plan request earlier: "after agreeing to the lower amount for Friday 16 October, and before anything is read back, asks for a new payment plan". This tests the same 7.11.4 clause, "agreed but not yet recorded".

---

## Minor notes (no change needed)

- **C-01, C-10, D-13 ("Cannot pay today. Says …"):** if the persona answers only "no" to the today question, the agent's attempt-1 offer comes before the customer's own date. Every script then states the customer's date or acceptance explicitly, so each case still ends at the expected ledger. C-07 and C-10 do not depend on this at all.
- **C-04:** the robot question has no fixed timing. C3/C4 cover it before confirmation, and C4 covers it at any later point, so the ledger and checks are unaffected.
- **D-03:** 7.4.5 is less tight than C16 ("a second refusal or a second such question" when the first event was a question and the second a refusal). An agent may ask once more, but the persona keeps refusing, so the ledger and checks are unaffected.
- **D-02:** brief D has no rule saying "half past five" means 17:30. The persona says "half past five in the afternoon", so 17:30 is unambiguous.
- **Mock:** every case's identity and products are identical to public-test-set.json, so the hosted mock's facts line up. PUB-10's fault correctly gives NOP-SYS under C (no retry) and a promise under D (retry, second call succeeds). No case needs two promises on one product.
