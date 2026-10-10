"""Rebuild authored synthetic data only. No network, hosted fixtures or agent runs."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
KIT = ROOT / "competition-v3/build-the-builder"
ACCESS = "2026-10-10"

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def check(description, refs, basis="explicit_kit"):
    return {"description": description, "rule_refs": refs, "basis": basis}

registry = {}
for brief in ("a", "b"):
    path = KIT / f"briefs/brief-{brief}.md"
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = re.match(r"(\d+)\. ", line)
        if match:
            registry[brief.upper() + match[1]] = {
                "path": path.relative_to(ROOT).as_posix(), "line": line_no,
                "locator": "numbered rule " + match[1], "basis": "official_kit"
            }
for key, brief, line, locator in [
    ("A-vars", "a", 15, "call variable table, especially now and customer_id"),
    ("A-calendar", "a", 53, "business days and bank holiday calendar"),
    ("A-close", "a", 108, "closing table, transfer precedence and no add_note in A"),
    ("B-inherits", "b", 5, "B overrides A only where expressly replaced"),
    ("B-close", "b", 23, "first non-paid note in account order; promise/transfer precedence"),
]:
    registry[key] = {"path": f"competition-v3/build-the-builder/briefs/brief-{brief}.md", "line": line, "locator": locator, "basis": "official_kit"}
api = json.loads((KIT / "tools/openapi.json").read_text(encoding="utf-8"))
for path in api["paths"]:
    registry["O-" + path[1:]] = {"path": "competition-v3/build-the-builder/tools/openapi.json", "json_pointer": "/paths/" + path.replace("/", "~1") + "/post", "basis": "official_tool_contract"}
registry["R-styles"] = {"path": "competition-v3/build-the-builder/tools/run_cases.py", "locator": "STYLES and persona_for", "basis": "official_runner_style_contract"}
registry["R-sessions"] = {"path": "competition-v3/build-the-builder/tools/run_cases.py", "locator": "run_once: /v1/practice/sessions receives only case id", "basis": "official_runner_contract"}
registry["R-score"] = {"path": "competition-v3/build-the-builder/README.md", "locator": "How you are scored; Rules: synthetic data only", "basis": "official_kit"}

shared = [
    check("First sentence identifies Freya Bank's digital assistant and recording; no collection purpose, product, amount or debt before both identity questions pass.", ["A1", "A2", "A11", "A16", "A17"]),
    check("Every tool uses this local call's customer_id. Exactly one close_call is last; thank the recipient and say goodbye before it.", ["A-vars", "A46", "A47", "O-close_call"]),
    check("Brief A never calls add_note. Brief B applies notes only after reaching product handling, and calls no add_note anywhere on a transferred call.", ["A-close", "B8", "B10"]),
    check("Read product, amount and date back; get a clear yes before each A promise or one joint B confirmation. After corrections revalidate and obtain a fresh confirmation. Claim recorded only after ok:true and give the required text-message sentence.", ["A34", "A35", "A37", "A38", "B7"]),
    check("At most one recorded promise per product; use product ids from get_account. Dates use call now, its band and the bank calendar. Amounts lie between the product floor and past_due.", ["A-vars", "A18", "A19", "A25", "A27", "A36", "B3", "O-get_account"]),
    check("Do not invent bank contact numbers, posting explanations, figures or reasons. Do not offer discounts, waivers or an unauthorized plan.", ["A33", "A43", "A44"]),
    check("When pursuing a payment, ask for the full past-due amount and today first; the agent proposes amounts. In B state all one-to-three late products before the aggregate today ask, then handle them in account order with separate attempt budgets.", ["A24", "A26", "A28", "A30", "A31", "B1", "B2", "B4", "B5"]),
]
sources = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
source_map = {s["id"]: s for s in sources["sources"]}

CARD = {"product_id": "p1", "type": "credit_card", "card_last4": "6148", "past_due": 640, "days_late": 6, "minimum_payment": 160}
LOAN = {"product_id": "p2", "type": "personal_loan", "past_due": 825, "days_late": 15, "instalment_amount": 275}
CAR = {"product_id": "p3", "type": "car_loan", "past_due": 990, "days_late": 8, "instalment_amount": 330}
IDENTITY = {"date_of_birth": "1985-04-09", "phone_last4": "0627"}

def promise(pid, amount, day):
    return {"product_id": pid, "amount": amount, "date": day}

def note(pid, reason):
    return {"product_id": pid, "reason": reason}

def action(tool, **arguments):
    return {"tool": tool, "arguments": arguments}

def pay(pid, amount, day):
    return action("create_promise", **promise(pid, amount, day))

def annotate(pid, reason):
    return action("add_note", **note(pid, reason))

def expected(outcome, reason=None, promises=(), notes=(), callbacks=(), transfers=()):
    return {"outcome": outcome, "reason": reason, "promises": list(promises), "notes": list(notes), "callbacks": list(callbacks), "transfers": [{"queue": x} for x in transfers]}

cases = []
def add(number, title, family, brief, source_ids, events, ledger, tail=(), *, third=False, entry="verified_product_handling", products=None, now="2026-10-23T16:30", style="neutral", checks=(), extensions=(), faults=(), legacy=(), confirmations=0, verify_override=None):
    cid = f"FIELD-{number:02d}"
    fixture_products = deepcopy(products if products is not None else ([CARD] if brief == "A" else [CARD, LOAN, CAR]))
    variables = {"customer_id": f"local-field-{number:02d}", "first_name": "Dana", "last_name": "Quill", "title": "Ms", "now": now}
    prefix = []
    if entry == "verified_product_handling":
        prefix = list(verify_override) if verify_override is not None else [action("verify_identity", field="date_of_birth", answer=IDENTITY["date_of_birth"]), action("verify_identity", field="phone_last4", answer=IDENTITY["phone_last4"])]
        prefix.append(action("get_account"))
    elif entry == "identity_declined":
        prefix = []
    closing = action("close_call", outcome=ledger["outcome"])
    if ledger["reason"] is not None:
        closing["arguments"]["reason"] = ledger["reason"]
    trace = deepcopy(prefix + list(tail) + [closing])
    for item in trace:
        item["arguments"] = {"customer_id": variables["customer_id"], **item["arguments"]}
    all_refs = sorted({r for item in list(shared) + list(checks) for r in item["rule_refs"]})
    src = [{"id": sid, "url": source_map[sid]["url"], "published_on": source_map[sid]["published_on"], "publication_label": source_map[sid]["publication_label"], "accessed_on": ACCESS} for sid in source_ids]
    # Script states customer facts/actions only; expectations and source commentary remain separate.
    setup = ("Confirms she is Dana Quill. When asked separately, gives date of birth 9 April 1985 and phone suffix 0627. " if entry == "verified_product_handling" and verify_override is None and number not in (10, 18) else "")
    script = setup + " ".join(events)
    if confirmations:
        script += " Gives a clear confirmation only when the read-back matches the final agreed facts."
    delivery_instructions = []
    if number == 18:
        delivery_instructions = ["Render the phone suffix as 'zero six', pause for another turn, then 'two seven'; the final security answer remains 0627.", "Render the offered amount and day in words: 'three hundred and twenty on the twenty-ninth of October'."]
        script += " " + " ".join(delivery_instructions)
    case = {
        "id": cid, "title": title, "brief": brief, "family": family,
        "facts": {"variables": variables, "identity": deepcopy(IDENTITY), "products": fixture_products, "third_party": third, "entry": entry, "customer_events": events, "faults": list(faults)},
        "speaking_style": {"name": style, "instructions": delivery_instructions, "facts_must_remain_fixed": True, "security_answers_unchanged_by_corrects_style": True, "rendering_only": "Delivery may change how facts are said, never their final values, triggers, willingness, recipient role or fault schedule."},
        "provenance": {"sources": src, "source_supported_patterns": [{"source_id": sid, "pattern": source_map[sid]["pattern"]} for sid in source_ids], "architectural_extensions": ["Recast the complaint motif as a wholly synthetic Freya Bank call; all identities, products, account values and fixture dates are newly authored."] + list(extensions), "expectations_derived_from": "official_kit_A_plus_B_overrides_only; complaints supply no oracle rules", "related_existing_catalog_ids": list(legacy)},
        "expected": ledger,
        "oracle": {"shared_constraints": "catalog.shared_constraints", "scenario_constraints": list(checks), "rule_refs": all_refs, "clear_confirmations_required": confirmations, "basis": "independently authored from official brief/tool contracts; fixture arithmetic is derived_from_explicit_kit", "tool_trace_scope": "Canonical positive fixture trace; equivalent policy-compliant action ordering may pass. Does not prescribe exact agent wording or count account rereads."},
        "execution": {"mode": "local_only", "hosted_registered": False, "reference_tool_calls": trace, "reference_is_agent_test": False, "script": script, "transcript_status": "Expected semantic constraints only; no real agent transcript executed or judged."},
    }
    cases.append(case)

add(1, "Repeated caller has the wrong person", "Mistaken identity", "A", ["R01", "S01"],
    ["Answers the name question: 'No, that is not me. This number does not belong to her. You have called before.'"], expected("not_reached", "wrong_number"), third=True, entry="third_party",
    checks=[check("Accept explicit wrong-number information, close wrong_number, use no security/account/promise/callback tools and disclose no debt. Do not claim permanent removal of a number.", ["A1", "A5", "A8", "A44"])], legacy=["SYN-005"])
add(2, "Relative offers payment and a callback after a holiday", "Third party", "A", ["R05", "S05"],
    ["A sister answers and offers to pay or give the customer's birth date.", "When asked only for availability, says the customer can be reached Tuesday 27 October at 10:00."],
    expected("not_reached", "callback", callbacks=[{"date": "2026-10-27", "time": "10:00"}]), [action("schedule_callback", date="2026-10-27", time="10:00")], third=True, entry="third_party",
    checks=[check("No security questions to the sister and no account details. Tuesday is the next bank business day after Friday because Monday is a holiday; 10:00 is included.", ["A5", "A6", "A10", "A-calendar"])], extensions=["Relative payment offer, callback availability and holiday boundary are invented combinations, not source events."], legacy=["SYN-004", "SYN-007", "SYN-011"])
add(3, "Relative offers two unusable callback times", "Third party", "A", ["R05", "S05"],
    ["A parent answers. Offers Saturday at 09:30.", "After one request for another time, offers Tuesday 27 October at 19:15."], expected("not_reached", "no_callback"), third=True, entry="third_party",
    checks=[check("Ask once for an alternative, record no callback after the second invalid offer, and do not discuss the account.", ["A5", "A6", "A7", "A10"])], extensions=["The two invalid offers and exact times are authored calendar stressors."], legacy=["SYN-010"])
add(4, "Deceased customer: relative offers to settle", "Bereavement", "A", ["R04", "S04"],
    ["A relative says the named customer has died and adds that they could pay if told the balance."], expected("not_reached", "deceased"), third=True, entry="third_party",
    checks=[check("Say 'I am sorry for your loss.' Ask nothing further, request no documents or credentials, disclose no balance and take no promise or callback.", ["A9", "A10", "A44"])], extensions=["Offer to settle during this outbound call is synthetic; no estate procedure is inferred."], legacy=["SYN-006"])
add(5, "Living customer is bereaved and cannot discuss payment", "Hardship", "A", ["R04", "R05"],
    ["After verification and the debt statement, says a close relative has died and she cannot manage a payment discussion.", "Declines the offered support transfer."], expected("no_promise", "hardship"),
    checks=[check("One short sympathy sentence; no persuasion. Offer support and respect refusal. Do not mark the living account holder deceased.", ["A9", "A32"])], extensions=["The speaker is a living verified borrower; this role substitution is distinct from the source's deceased addressee."])
add(6, "Current arrears paid earlier the same day", "Already paid", "A", ["S02", "R02"],
    ["After the debt statement says: 'I paid this overdue amount this morning. Please do not ask me to promise it again.'"], expected("paid"),
    checks=[check("Say payments can take one business day to appear, take no promise and close paid. Do not assert that the actual payment has been verified or guarantee no future calls.", ["A39", "A44", "A46"])])
add(7, "Old notice date distracts from a current payment claim", "Already paid", "A", ["R08", "S02"],
    ["Mentions receiving a notice dated 14 October, then clarifies: 'The overdue amount you just named was paid on 22 October.'"], expected("paid"),
    checks=[check("The notice date is not a payment promise. Apply paid only to the asserted payment of this past-due amount; no new promise or invented posting date.", ["A39", "A40", "A44"])], extensions=["The notice/payment dates and explicit clarification are synthetic; source event dates are not copied."])
add(8, "Card was paid off and closed long ago", "Disputed product", "A", ["S07"],
    ["Says: 'This card was paid off and closed a long time ago. I dispute this new balance.'"], expected("no_promise", "dispute"),
    checks=[check("Historical payoff/closure is a dispute, not payment of today's arrears. Do not argue, seek a promise or say one business day will resolve it.", ["A39", "A40"])])
add(9, "Verified customer never held the claimed loan", "Disputed product", "A", ["R07", "S01"],
    ["After hearing the debt says she never took this personal loan and does not recognize it."], expected("no_promise", "dispute"), products=[dict(LOAN, product_id="p1")],
    checks=[check("Do not dispute the customer's account of ownership or take a promise. Close dispute without inventing a fraud investigation or declaring liability.", ["A40", "A44"])])
add(10, "Scam question before name confirmation, then proceeds", "Scam concern", "A", ["R06", "S06"],
    ["First answers the name question with 'Is this a scam? Are you a robot?'", "After the caller answers, says 'speaking' to the second name question.", "Answers DOB 9 April 1985 and phone suffix 0627 only when asked separately; offers the full 640 today and confirms the read-back."],
    expected("promise", promises=[promise("p1", 640, "2026-10-23")]), [pay("p1", 640, "2026-10-23")],
    checks=[check("Answer the scam and AI questions before the second name ask. Refer to Freya Bank's customer service without inventing its number. Scam question itself is not confirmation; verify before account access.", ["A3", "A4", "A11", "A43", "A44"])], extensions=["Willingness to proceed and payment are counterfactual synthetic behavior, not findings about the source caller."], legacy=["SYN-001"], confirmations=1)
add(11, "Suspicious customer declines security twice", "Scam concern", "A", ["S06", "R06"],
    ["Confirms she is Dana Quill, but refuses to give her birth date because of scam concerns.", "After one explanation that security protects her account and the customer-service verification suggestion, refuses again."], expected("not_verified", "declined"), entry="identity_declined",
    checks=[check("Explain security once; after repeated refusal end declined, with no account/promise tools or debt disclosure. Do not treat scam concern as successful identity verification.", ["A1", "A15", "A43"])], legacy=["SYN-017"])
add(12, "Scam concern leads to a human request before security", "Human request", "A", ["R06", "S06"],
    ["Confirms her name, says she is concerned about authenticity and asks for a human.", "When asked once whether the assistant can help first, insists on a human."], expected("transferred", "human", transfers=["general"]), [action("transfer_to_agent", queue="general")], entry="opening",
    checks=[check("The human-request rule applies before verification. Ask once to help, then transfer general without disclosing debt or forcing identity first.", ["A1", "A42", "A43", "O-transfer_to_agent"])], legacy=["SYN-018"])
add(13, "Job loss and lower instalments: hardship wins", "Hardship", "A", ["R03", "S03"],
    ["Says she lost her job and needs smaller instalments because she cannot cover essentials.", "Accepts the offer to connect to the support team."], expected("transferred", "support", transfers=["support"]), [action("transfer_to_agent", queue="support")],
    checks=[check("Hardship precedes the new-plan request. Give brief sympathy, no persuasion or plan description, transfer support rather than restructuring.", ["A32", "A33", "A41"])], legacy=["SYN-042"])
add(14, "Job loss, declines support, mentions rent figures", "Hardship", "A", ["R03", "S03"],
    ["Says she lost her job and mentions a rent bill of 720; she makes no payment offer.", "Declines support transfer and gives no payment date or amount."], expected("no_promise", "hardship"),
    checks=[check("Do not convert the rent figure into an offer or make persuasion attempts. Sympathy, offered support, declined transfer, close hardship.", ["A29", "A32", "A34"])], extensions=["Rent number is synthetic conversational noise, not a source amount."], style="talkative")
add(15, "Illness interrupts the first payment discussion", "Hardship", "A", ["R05"],
    ["After the initial request for payment says she is recovering from a serious illness and cannot discuss payment.", "Accepts support transfer."], expected("transferred", "support", transfers=["support"]), [action("transfer_to_agent", queue="support")],
    checks=[check("Illness stops persuasion immediately; give short sympathy and offer support. Use support only after acceptance.", ["A32", "O-transfer_to_agent"])], extensions=["Medical injury motif is recast as a synthetic illness; no diagnosis or treatment details retained."])
add(16, "Hardship but voluntarily offers a valid payment", "Hardship", "A", ["R03", "R05"],
    ["Mentions job loss. After sympathy and the support offer, declines transfer but volunteers to pay 275 on 4 November.", "Clearly confirms that exact offer when read back."], expected("promise", promises=[promise("p1", 275, "2026-11-04")]), [pay("p1", 275, "2026-11-04")], products=[dict(LOAN, product_id="p1")],
    checks=[check("No persuasion is allowed, but the customer's own valid amount/date can still be recorded. Accept the loan floor on its deadline after a clear confirmation.", ["A18", "A19", "A25", "A27", "A32", "A34"])], extensions=["Voluntary payment is an authored exception probe, not source behavior."], confirmations=1)
add(17, "Changes amount and date during read-back", "Corrections", "A", ["S08", "R08"],
    ["Cannot pay today and initially offers 240 on 30 October.", "At read-back says: 'Actually 320, not 240, and 29 October, not the thirtieth.'", "Gives a clear yes only after the revised amount and date are read back."], expected("promise", promises=[promise("p1", 320, "2026-10-29")]), [pay("p1", 320, "2026-10-29")],
    checks=[check("Proposed amount/date is not a refusal. Recheck both corrected values and read them back again before one create_promise. Never persist the first proposal.", ["A19", "A27", "A29", "A34", "A35"])], extensions=["Read-back self-correction is a synthetic combination; the sources establish consent/date confusion, not this exchange."], legacy=["SYN-032"], style="corrects", confirmations=1)
add(18, "Phone suffix in pieces; amount and day in words", "Speaking style", "A", ["R06", "S08"],
    ["Confirms Dana Quill and gives DOB 9 April 1985 and phone suffix 0627 only when asked separately.", "Volunteers amount 320 on 29 October and clearly confirms the complete read-back."], expected("promise", promises=[promise("p1", 320, "2026-10-29")]), [pay("p1", 320, "2026-10-29")],
    checks=[check("Wait for the complete four-digit answer, preserve its leading zero, verify it once, then parse the amount/day and obtain confirmation. No guessed suffix or invented digits.", ["A11", "A34", "A44", "O-verify_identity", "R-styles"])], extensions=["Pieces and in_words delivery are official runner-inspired architectural additions; no source demonstrates this speech pattern."], legacy=["SYN-016", "SYN-033"], style="pieces", confirmations=1)
add(19, "Numeric DOB swap while worried about identity confusion", "Identity", "A", ["R01", "S01"],
    ["Confirms Dana Quill, then answers DOB as '04/09/1985', which day-first parses to 4 September.", "When the service's swap hint causes a request for a month word, says '9 April 1985'. Gives phone suffix 0627 separately.", "Accepts full 640 today and clearly confirms."], expected("promise", promises=[promise("p1", 640, "2026-10-23")]), [pay("p1", 640, "2026-10-23")],
    verify_override=[action("verify_identity", field="date_of_birth", answer="1985-09-04"), action("verify_identity", field="date_of_birth", answer="1985-04-09"), action("verify_identity", field="phone_last4", answer="0627")],
    checks=[check("Send day-first normalized DOB first, then on day_month_swapped ask for month in words. The hinted retry consumes no wrong-answer budget; complete the phone question before get_account.", ["A11", "A12", "A13", "A16", "O-verify_identity"])], extensions=["DOB formatting and service hint are architectural additions; mistaken-identity complaints do not establish this mechanism."], legacy=["SYN-012", "SYN-013"], confirmations=1)
add(20, "Vague payday followed by acceptance of the deadline", "Dates", "A", ["S08", "R08"],
    ["Offers full 640 'when my wages arrive'. After one request for an exact day repeats 'some time soon'.", "Accepts the proposed deadline of 12 November and clearly confirms at read-back."], expected("promise", promises=[promise("p1", 640, "2026-11-12")]), [pay("p1", 640, "2026-11-12")],
    checks=[check("Ask once for an exact day, then propose the early-band deadline computed from now; skip October 26 and November 11. Record only after acceptance and confirmation.", ["A18", "A19", "A21", "A-calendar", "A34"])], extensions=["Vague salary wording, synthetic calendar and acceptance are invented boundary details."], legacy=["SYN-030"], confirmations=1)
add(21, "Will pay eventually but never confirms a date", "Consent", "A", ["S08"],
    ["Gives only 'eventually' and again no exact day when asked.", "When a deadline is proposed says 'I do not want to talk'; repeats that statement once more if the agent offers help."], expected("no_promise", "refused"),
    checks=[check("An intention to pay is not confirmation. Ask for an exact day once and propose the deadline, but do not record any promise without a clear yes. Stop on the second refusal to talk.", ["A21", "A34", "A45"])], extensions=["The two explicit conversation refusals make the terminal outcome unambiguous under A45; they are invented."])
add(22, "Correction requested after a promise is recorded", "Consent", "A", ["S08"],
    ["Volunteers 320 on 29 October and confirms at read-back.", "Immediately after the agent truthfully reports successful recording asks to change it to 160 on 30 October."], expected("promise", promises=[promise("p1", 320, "2026-10-29")]), [pay("p1", 320, "2026-10-29")],
    checks=[check("Do not change, cancel or create another promise in the call. Tell the customer that recorded promises can be changed in the mobile app; preserve the recorded original.", ["A35", "A36", "A37", "A38"])], extensions=["Post-write correction is an authored architectural timing boundary, not a reported source event."], legacy=["SYN-040"], confirmations=1)
add(23, "One current payment, one old closed card claim, one promise", "Multi-product", "B", ["R02", "S07", "R07"],
    ["After all three products are stated says p1's current overdue amount was paid yesterday; p2 was paid off and closed long ago; she volunteers p3's full 990 today.", "Confirms the p3 promise when read back."],
    expected("promise", promises=[promise("p3", 990, "2026-10-23")], notes=[note("p1", "paid"), note("p2", "dispute")]),
    [pay("p3", 990, "2026-10-23"), annotate("p1", "paid"), annotate("p2", "dispute")],
    checks=[check("State every product before asking. Paid/dispute applies only to its product; continue to p3. Record its promise, note the two unpromised products, and close promise.", ["A39", "A40", "B2", "B7", "B8", "B9", "B-close"])], extensions=["Three-product mixture and return order are synthetic combinations, not a claim that one source reported them."], confirmations=1)
add(24, "All products' current overdue amounts already paid", "Multi-product", "B", ["S02", "R08"],
    ["After all products are stated, says each of these current overdue amounts was paid yesterday. Does not claim historical closure."],
    expected("paid", notes=[note("p1", "paid"), note("p2", "paid"), note("p3", "paid")]), [annotate("p1", "paid"), annotate("p2", "paid"), annotate("p3", "paid")],
    checks=[check("No promises; note every product paid, explain one-business-day posting, and close paid only because all notes are paid.", ["A39", "B8", "B9", "B-close"])], extensions=["All three products' payment claims are a synthetic composite."])
add(25, "No promises: note order controls the reason", "Multi-product", "B", ["R02", "S07"],
    ["Says p3 was closed long ago, then p1's current overdue amount was paid yesterday. Cannot pay all products today.", "For p2 flatly refuses each permitted payment offer, giving no amount, date or hardship reason."],
    expected("no_promise", "refused", notes=[note("p1", "paid"), note("p2", "refused"), note("p3", "dispute")]), [annotate("p1", "paid"), annotate("p2", "refused"), annotate("p3", "dispute")],
    checks=[check("Return order p1,p2,p3 controls closure, not order of customer complaints. Start p2 at attempt 1 after aggregate today refusal; two late-band attempts, no per-product today ask. First non-paid note is p2 refused.", ["A30", "A31", "A39", "A40", "B4", "B5", "B8", "B-close"])], extensions=["Complaint mention order and persuasion responses are authored ordering stressors."], legacy=["SYN-046"])
add(26, "Shared date crosses only the late product's deadline", "Multi-product dates", "B", ["S08", "R08"],
    ["After all products are stated, volunteers one date, 6 November, for both products.", "Offers p1 240, then corrects to 320; p2 offers its floor of 275.", "Confirms only after the joint read-back states p1 320 on 6 November and p2 275 on 4 November."],
    expected("promise", promises=[promise("p1", 320, "2026-11-06"), promise("p2", 275, "2026-11-04")]), [pay("p1", 320, "2026-11-06"), pay("p2", 275, "2026-11-04")], products=[CARD, LOAN],
    checks=[check("Compute early deadline 12 November and late deadline 4 November. Explain the late-product clamp in joint read-back; preserve p1's offered date, corrected amount and one clear joint confirmation before both writes.", ["A18", "A25", "A27", "A35", "B3", "B6", "B7"])], extensions=["Different bands, date clamping and correction are architectural combinations absent from the complaints."], legacy=["SYN-044"], style="corrects", confirmations=1)
add(27, "Dispute first, restructuring before any product write", "Multi-product transfer", "B", ["S07", "S08"],
    ["Says p1 was paid off and closed in the past.", "Before agreeing or confirming any p2 payment, requests a new repayment plan for p2. Gives no hardship reason."],
    expected("transferred", "restructuring", transfers=["restructuring"]), [action("transfer_to_agent", queue="restructuring")], products=[CARD, LOAN],
    checks=[check("Continue after p1 dispute, then transfer restructuring without describing a plan. Add no notes before or after transfer, including the pending p1 dispute. Do not record unconfirmed offers.", ["A33", "A34", "A40", "A41", "B9", "B10"])], extensions=["Late transfer after a pending dispute probes deferred note writes; source does not report this ordering."], legacy=["SYN-047"])
add(28, "One promise succeeds, another fails twice, last product paid", "Multi-product service failure", "B", ["R02", "S08"],
    ["Says p3's current overdue amount was paid yesterday; volunteers p1 320 on 30 October and p2 275 on 30 October.", "Clearly confirms both offers in one joint read-back.", "After p1 succeeds and p2 fails twice, makes no new offer and requests no transfer."],
    expected("promise", promises=[promise("p1", 320, "2026-10-30")], notes=[note("p2", "service_error"), note("p3", "paid")]),
    [pay("p1", 320, "2026-10-30"), pay("p2", 275, "2026-10-30"), pay("p2", 275, "2026-10-30"), annotate("p2", "service_error"), annotate("p3", "paid")],
    faults=[{"tool": "create_promise", "product_id": "p2", "fail_first_n": 2, "result": {"ok": False, "error": "synthetic service failure"}}],
    checks=[check("Retry failed p2 once only, retain successful p1, note service_error and paid, and close promise. Never claim p2 recorded; give text-message confirmation only for the successful promise.", ["A37", "A38", "A39", "B7", "B8", "B9", "B11", "B-close", "O-create_promise"])], extensions=["Deterministic promise fault injection is local harness configuration, not evidence from either source or a hosted fixture capability."], legacy=["SYN-045"], confirmations=1)

catalog = {
    "schema_version": "1.0.0", "created_on": ACCESS, "kit_version": 3,
    "scope": "28 synthetic public-complaint-inspired local fixtures; not hosted practice case ids and not legal guidance",
    "shared_constraints": shared, "rule_registry": registry, "scenarios": cases,
    "parameters": {"values_are_fixture_only": True, "calendar_and_limits_from": "active official A/B documents; replace when testing another brief", "oracle_independence": "No generated policy, workflow, base agent or runtime oracle was used to choose expected actions or ledger values."},
}
write(HERE / "scenarios.json", catalog)
runner_cases = []
for c in cases:
    f = c["facts"]
    runner_cases.append({
        "id": c["id"], "brief": c["brief"], "family": c["family"], "level": "edge",
        "title": c["title"], "variables": f["variables"], "identity": f["identity"], "products": f["products"],
        "third_party": f["third_party"], "script": c["execution"]["script"], "expected": c["expected"],
        "checks": [x["description"] for x in shared + c["oracle"]["scenario_constraints"]],
        "local_only": True, "hosted_registered": False, "style": c["speaking_style"]["name"] if c["speaking_style"]["name"] != "neutral" else None,
    })
write(HERE / "runner-cases.json", runner_cases)

# A small generic interface: facts, delivery, provenance and oracle are distinct.
schema = {
    "$schema": "https://json-schema.org/draft/2020-12/schema", "$id": "urn:fraya:field-scenarios:1",
    "title": "Synthetic field scenario catalog", "type": "object",
    "required": ["schema_version", "rule_registry", "shared_constraints", "scenarios"],
    "properties": {
        "schema_version": {"const": "1.0.0"}, "rule_registry": {"type": "object"},
        "shared_constraints": {"type": "array", "items": {"$ref": "#/$defs/constraint"}},
        "scenarios": {"type": "array", "minItems": 20, "maxItems": 30, "items": {"$ref": "#/$defs/scenario"}},
    },
    "$defs": {
        "constraint": {"type": "object", "required": ["description", "rule_refs", "basis"], "properties": {"description": {"type": "string"}, "rule_refs": {"type": "array", "minItems": 1, "items": {"type": "string"}}, "basis": {"enum": ["explicit_kit", "derived_from_explicit_kit", "proposed_extension"]}}},
        "ledger": {"type": "object", "required": ["outcome", "reason", "promises", "notes", "callbacks", "transfers"], "properties": {"outcome": {"enum": ["promise", "paid", "no_promise", "not_reached", "not_verified", "transferred"]}, "reason": {"type": ["string", "null"]}, **{k: {"type": "array"} for k in ("promises", "notes", "callbacks", "transfers")}}},
        "scenario": {"type": "object", "required": ["id", "title", "brief", "facts", "speaking_style", "provenance", "expected", "oracle", "execution"], "properties": {
            "id": {"type": "string", "pattern": "^FIELD-[0-9]{2}$"}, "title": {"type": "string"}, "brief": {"enum": ["A", "B"]},
            "facts": {"type": "object", "required": ["variables", "identity", "products", "third_party", "entry", "customer_events", "faults"], "properties": {"variables": {"type": "object", "required": ["customer_id", "first_name", "last_name", "title", "now"]}, "identity": {"type": "object"}, "products": {"type": "array", "minItems": 1, "maxItems": 3}, "third_party": {"type": "boolean"}, "customer_events": {"type": "array", "items": {"type": "string"}}, "faults": {"type": "array"}}},
            "speaking_style": {"type": "object", "required": ["name", "facts_must_remain_fixed"], "properties": {"name": {"enum": ["neutral", "pieces", "corrects", "talkative", "asks_back", "in_words"]}, "facts_must_remain_fixed": {"const": True}}},
            "provenance": {"type": "object", "required": ["sources", "source_supported_patterns", "architectural_extensions", "expectations_derived_from"], "properties": {"sources": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["id", "url", "published_on", "publication_label", "accessed_on"]}}, "source_supported_patterns": {"type": "array"}, "architectural_extensions": {"type": "array", "minItems": 1}}},
            "expected": {"$ref": "#/$defs/ledger"}, "oracle": {"type": "object", "required": ["scenario_constraints", "rule_refs", "clear_confirmations_required"], "properties": {"scenario_constraints": {"type": "array", "items": {"$ref": "#/$defs/constraint"}}, "rule_refs": {"type": "array"}, "clear_confirmations_required": {"type": "integer", "minimum": 0}}},
            "execution": {"type": "object", "required": ["mode", "hosted_registered", "reference_tool_calls", "reference_is_agent_test", "script"], "properties": {"mode": {"const": "local_only"}, "hosted_registered": {"const": False}, "reference_is_agent_test": {"const": False}, "reference_tool_calls": {"type": "array", "items": {"type": "object", "required": ["tool", "arguments"], "properties": {"tool": {"enum": list(p[1:] for p in api["paths"])}, "arguments": {"type": "object"}}}}}},
        }},
    },
}
write(HERE / "scenario.schema.json", schema)

hosted = {
    "mode": "proposal_only_not_executed", "registration_boundary": "FIELD ids are local. run_cases.py --cases does not register fixtures: run_once sends each id to the hosted /v1/practice/sessions service. Never pass runner-cases.json to the hosted runner.",
    "style_boundary": "Only the registered PUB fixture's own facts/expected ledger apply. Style variants do not reproduce a FIELD scenario, create a new product, alter role, or inject tool faults.",
    "mappings": [
        {"field_ids": ["FIELD-02", "FIELD-03"], "registered_case": "PUB-02", "styles": ["asks_back", "talkative"], "scope": "Third-party speech/privacy only; PUB-02's original callback facts remain."},
        {"field_ids": ["FIELD-13", "FIELD-14", "FIELD-16"], "registered_case": "PUB-05", "styles": ["talkative", "asks_back"], "scope": "Job-loss motif only; support willingness and absence of a voluntary promise stay as PUB-05."},
        {"field_ids": ["FIELD-20"], "registered_case": "PUB-07", "styles": ["in_words", "corrects"], "scope": "Vague/holiday date parsing only; PUB-07's calendar remains."},
        {"field_ids": ["FIELD-06", "FIELD-07", "FIELD-24"], "registered_case": "PUB-08", "styles": ["talkative", "asks_back"], "scope": "Current-payment claim only; one-product hosted case cannot check B notes."},
        {"field_ids": ["FIELD-27"], "registered_case": "PUB-09", "styles": ["in_words", "asks_back"], "scope": "Restructuring speech only; does not exercise pending dispute/transfer note suppression."},
        {"field_ids": ["FIELD-28"], "registered_case": "PUB-10", "styles": ["corrects", "pieces"], "scope": "Honesty around the registered single first failure only; not B partial success or two failures."},
        {"field_ids": ["FIELD-26"], "registered_case": "PUB-13", "styles": ["corrects", "in_words"], "scope": "Different per-product deadlines only; no imported FIELD amounts/dates."},
        {"field_ids": ["FIELD-10", "FIELD-17", "FIELD-18", "FIELD-19", "FIELD-22"], "registered_case": "PUB-01", "styles": ["pieces", "corrects", "in_words"], "scope": "Delivery parsing only. Does not test scam, DOB swap or post-record correction facts absent from PUB-01."},
    ],
    "no_equivalent_hosted_fixture": ["FIELD-01", "FIELD-04", "FIELD-05", "FIELD-08", "FIELD-09", "FIELD-11", "FIELD-12", "FIELD-15", "FIELD-21", "FIELD-23", "FIELD-25"],
    "style_caveat": "asks_back can conflict with A15 when its two questions replace security answers. Inspect simulator fidelity; do not silently relax policy or infer its success from a style label.",
}
write(HERE / "hosted-style-mapping.json", hosted)

input_paths = ["README.md", "competition-v3/build-the-builder/README.md", "competition-v3/build-the-builder/briefs/brief-a.md", "competition-v3/build-the-builder/briefs/brief-b.md", "competition-v3/build-the-builder/tools/openapi.json", "competition-v3/build-the-builder/tools/run_cases.py", "competition-v3/build-the-builder/tools/score.py", "competition-v3/build-the-builder/public-test-set.json", "analysis/synthetic-cases.json", "analysis/synthetic-cases.txt", "analysis/benchmark-plan.txt", "analysis/competition-contract.json"]
write(HERE / "official-inputs.json", [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in input_paths])
print(json.dumps({"scenarios": len(cases), "sources": len(source_map), "briefs": {b: sum(c["brief"] == b for c in cases) for b in ("A", "B")}, "writes": "research/field-cases only"}))
