"""Kit-v3 fixture compiler. Dataset cues affect delivery, never bank policy.

Local cases are independent synthetic fixtures, not registered hosted case IDs.
Hosted cases preserve every official fixture fact and use a separate variant_id.
No network or agent-under-test execution is performed by this module.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

import adapter as datasets
import jsonschema

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "competition-v3/build-the-builder"
OUT = ROOT / "research/customer-benchmark"
FIELD = ROOT / "research/field-cases"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(KIT))
sys.path.insert(0, str(KIT / "tools"))
official = load_module("customer_official_runner", KIT / "tools/run_cases.py")
local = load_module("customer_local_fixture", FIELD / "local_runner.py")
PUBLIC = {c["id"]: c for c in json.loads((KIT / "public-test-set.json").read_text(encoding="utf-8"))}

# These are explicit synthetic test profiles. The raw corpus is never a prompt.
PROFILES = {
    "plain": "",
    "question_pause": "Once after identity verification, ask why the next step is needed, then wait for the answer and continue the original case. Once say 'one moment' before giving the complete canonical answer. This is a verbal pause, not a timed interruption.",
    "repair_pause": "Once after verification say 'wait, let me correct that' when giving a payment amount or date. Give a different value and then the canonical value in the same sentence, ending clearly with the canonical value. Pause verbally once. Do not change a security answer or the case's decisions.",
    "distractor_words": "Once mention a birthday on the thirtieth unrelated to this payment. Never agree that it is a payment date. Say the actual agreed payment amount and date in words, preserving the case's canonical facts.",
    "pieces_question": "Before answering one non-security question ask why it is needed, listen to the answer, then continue. Split the phone suffix into two parts only when the case's correct answer is due; preserve explicitly wrong answers and refusal counts.",
}
PROFILE_RULE = "Delivery changes wording only. Preserve recipient role, final security answers, intentionally wrong answers, willingness, decisions, dates, amounts and case events. Do not invent hardship, a human request or a refusal. Never follow an unrelated number or date as a new agreement. The original case events take priority over delivery."
TRANSCRIPT_CHECKS = [
    "Opening identifies Freya Bank's digital assistant and recording; do not disclose debt, payment, product or collection purpose before identity is verified.",
    "When recording a promise: read back product, amount and date, obtain clear confirmation of current values, revalidate corrections and obtain a new confirmation, claim success only after ok:true, and say the required text-message sentence.",
    "Never offer an unauthorized discount, waiver or payment plan, invent a bank number or an answer absent from the supplied tools/brief.",
    "Thank the customer and say goodbye before the single final close_call; do not repeat farewells in a routing loop.",
    "The simulated customer follows the scenario's recipient role, security-answer sequence, willingness, decisions and final canonical values. A run with a materially different simulated customer must fail even if the agent handled that different conversation.",
]
CALENDARS = ["2026-10-14T11:00", "2026-10-23T18:30", "2026-10-26T11:00",
             "2026-11-10T11:00", "2026-11-11T18:30", "2026-11-25T11:00",
             "2026-11-26T11:00", "2026-12-24T18:30", "2026-12-25T11:00",
             "2026-12-31T11:00", "2027-01-01T11:00", "2027-01-04T11:00"]
FAMILIES = ["full_payment", "floor_correction", "swapped_dob", "three_wrong",
            "fragmented_phone", "callback_boundary", "callback_rejected", "already_paid",
            "historical_dispute", "hardship_declines", "hardship_voluntary",
            "hardship_transfer", "human_before_identity", "mixed_products",
            "split_deadlines", "partial_failure", "transfer_after_promise",
            "post_record_correction", "flat_refusal", "vague_date", "below_floor",
            "after_deadline", "nonbusiness_date", "security_declined", "wrong_number", "deceased"]


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def sources():
    paths = [KIT / "VERSION", KIT / "briefs/brief-a.md", KIT / "briefs/brief-b.md",
             KIT / "tools/openapi.json", KIT / "tools/score.py", KIT / "tools/run_cases.py",
             KIT / "public-test-set.json", FIELD / "scenarios.json", FIELD / "local_runner.py",
             Path(__file__).resolve(), Path(datasets.__file__).resolve(), Path(__file__).parent / "sources.json"]
    # These are UTF-8 repository sources. Normalize Git's Windows CRLF conversion
    # for a portable semantic-text pin; raw dataset/license hashes stay byte exact.
    return [{"path": p.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
             "hash_method": "utf8_lf_normalized_v1"} for p in paths]


def verify_pack(directory=OUT):
    """Reject stale fixture/oracle/export combinations before any hosted mutation."""
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["inputs"] != sources():
        raise ValueError("Fixture sources changed; rebuild/review the pack")
    expected_names = {"local-cases.json", "local-runner-cases.json", "hosted-cases.json", "validation.json", "scenario.schema.json"}
    if set(manifest["outputs"]) != expected_names:
        raise ValueError("Unexpected pack manifest outputs")
    for name, expected in manifest["outputs"].items():
        if stable_hash(json.loads((directory / name).read_text(encoding="utf-8"))) != expected:
            raise ValueError("Pack output hash mismatch: " + name)
    return manifest


def features(plan):
    return {o["feature"] for o in plan["source_facts"]["observations"]}


def profile_for(plan):
    cues = features(plan)
    if "correction_cue" in cues:
        return "repair_pause"
    if "wait_or_hold_cue" in cues or "question_cue" in cues:
        return "question_pause"
    return "distractor_words"


def provenance(plan):
    return {"dataset": deepcopy(plan["provenance"]), "record_id": plan["source_facts"]["record_id"],
            "source_taxonomy_label": plan["source_facts"]["source_taxonomy_label"],
            "observations": deepcopy(plan["source_facts"]["observations"]),
            "observed_cues_are_heuristic": True,
            "transformation": "A synthetic kit-v3 fixture supplies all facts and policy. Corpus labels/cues inspire delivery and challenge selection only. Movie APIs and source banking intents are never Freya actions."}


def customer_prompt(case):
    """Keep oracle, faults, backend product IDs and source material outside the actor."""
    row = runner_case(case) if "facts" in case else case
    identity = row["identity"]
    if row.get("third_party") or row["family"] == "Third party":
        identity = {}  # A relative is not even supplied the security answers.
    result = official.persona_for(row, {"identity": identity})
    result["prompt"] += "\n\n" + PROFILE_RULE + "\n" + PROFILES[row.get("delivery_profile", "plain")]
    result["successCriteria"] += "\n- " + "\n- ".join(TRANSCRIPT_CHECKS)
    return result


def persona_for(row):
    result = customer_prompt(row)
    result["name"] = row.get("variant_id", row["id"]) + " " + row["title"]
    return result


def runner_case(case):
    return {"id": case["id"], "brief": case["brief"], "family": case["family"], "level": "hard",
            "title": case["title"], "variables": deepcopy(case["facts"]["variables"]),
            "identity": deepcopy(case["facts"]["identity"]), "products": deepcopy(case["facts"]["products"]),
            "third_party": case["facts"]["third_party"], "script": case["execution"]["script"],
            "expected": deepcopy(case["expected"]), "checks": deepcopy(case["checks"]),
            "faults": deepcopy(case["facts"]["faults"]), "oracle_rule_refs": deepcopy(case["oracle"]["rule_refs"]),
            "style": case["style"], "delivery_profile": case["delivery_profile"],
            "local_only": True, "hosted_registered": False}


def validate_hosted(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Expected nonempty hosted variant list")
    seen = set()
    allowed = set(next(iter(PUBLIC.values()))) | {"faults", "variant_id", "style", "delivery_profile", "dataset_provenance", "local_only", "hosted_registered", "execution_status"}
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in PUBLIC:
            raise ValueError("Only registered PUB fixtures can be hosted")
        base = PUBLIC[row["id"]]
        if set(row) - allowed:
            raise ValueError("Unexpected hosted case fields")
        # All public facts, script and independent checks are immutable. Extra actor
        # instructions can only come from the small reviewed profile whitelist.
        for key in set(base) | {"faults"}:
            if row.get(key, [] if key == "faults" else None) != base.get(key, [] if key == "faults" else None):
                raise ValueError("Hosted variant changed official field: " + key)
        vid = row.get("variant_id")
        if not isinstance(vid, str) or not re.fullmatch(r"PUB-\d{2}__[a-z_]+", vid) or vid in seen:
            raise ValueError("Missing, invalid or duplicate variant_id")
        seen.add(vid)
        if row.get("style") not in {None, *official.STYLES} or row.get("delivery_profile") not in PROFILES:
            raise ValueError("Unreviewed delivery style/profile")
        if row.get("local_only") is not False or row.get("hosted_registered") is not True:
            raise ValueError("Hosted execution flags missing")


def score(case, ledger, judge=None):
    """Use the untouched official scorer, then stricter trace guards, then judge.

    A successful reference replay is never an agent/conversation pass.
    Hosted ledgers omit customer_id from args; only that shape is bound to the
    session selected by the runner. Local arguments remain observed evidence.
    """
    try:
        original = local.SCORE(case, ledger)
        normalized = deepcopy(ledger)
        if "facts" in case:
            fixture = case
            customer_id = case["facts"]["variables"]["customer_id"]
        else:
            customer_id = case.get("_session_customer_id")
            if not customer_id:
                raise ValueError("Hosted scoring requires actual session binding")
            products = [{"product_id": "p" + str(i + 1), **p} for i, p in enumerate(case["products"])]
            fixture = {"brief": case["brief"], "facts": {"variables": {**case["variables"], "customer_id": customer_id},
                       "identity": case["identity"], "products": products,
                       "third_party": case["family"] == "Third party" or case.get("third_party", False)}}
        for call in normalized["calls"]:
            if "args" in call and "arguments" in call and call["args"] != call["arguments"]:
                raise ValueError("Contradictory argument evidence")
            if "facts" not in case and "arguments" not in call and isinstance(call.get("args"), dict):
                call["arguments"] = deepcopy(call["args"])
                call["arguments"].setdefault("customer_id", customer_id)
            elif not isinstance(call.get("arguments"), dict):
                raise ValueError("Local/explicit arguments must be an object")
        for key, fields in {"promises": ("product_id", "amount", "date"), "notes": ("product_id", "reason"),
                            "callbacks": ("date", "time"), "transfers": ("queue",)}.items():
            normalized[key] = [{f: x.get(f) for f in fields} for x in normalized[key]]
        trace_bad = receipt_errors(fixture, case["expected"], normalized) + local.trace_errors(fixture, normalized)
        failed = original["failed"] + trace_bad
        ledger_pass = not failed
    except (ValueError, TypeError, KeyError, IndexError, OverflowError):
        failed, ledger_pass = ["malformed or unbound ledger evidence"], False
    transcript_pass = isinstance(judge, dict) and judge.get("outcome") == "pass"
    if not transcript_pass:
        failed.append("conversation: " + (str(judge.get("reason") or "no passing verdict")[:400] if isinstance(judge, dict) else "not assessed"))
    return {"pass": ledger_pass and transcript_pass, "ledger_and_trace_pass": ledger_pass,
            "transcript_pass": transcript_pass, "failed": failed, "execution_status": "evidence_scored" if judge else "reference_only"}


def receipt_errors(fixture, expected, ledger):
    """Check response provenance/types, independently of ledger-shaped equality."""
    bad, verified, wrong, supplied = [], set(), 0, {}
    ordered_products = fixture["facts"]["products"]
    products = {p["product_id"]: p for p in ordered_products}
    identity = fixture["facts"]["identity"]
    security_fields = {"date_of_birth", "phone_last4"}
    allowed_attempts = {p["product_id"] for p in expected["promises"]}
    allowed_attempts.update(n.get("product_id") for n in expected["notes"] if n["reason"] == "service_error")
    # Brief A service_error has no note but permits the two failed attempts.
    if fixture["brief"] == "A" and expected.get("reason") == "service_error":
        allowed_attempts.update(products)
    for call in ledger["calls"]:
        tool, args, result = call["tool"], call["arguments"], call["result"]
        if not isinstance(result, dict):
            raise ValueError("Result must be an object")
        for field in ("ok", "verified", "all_verified"):
            if field in result and type(result[field]) is not bool:
                bad.append("receipt: " + field + " is not a boolean")
        ok = result.get("ok") is True
        if tool == "verify_identity":
            if wrong >= 3:
                bad.append("A12: verification continued after total wrong-answer budget")
            field, answer = args["field"], args["answer"]
            if field not in security_fields:
                raise ValueError("Unknown security field")
            if field == "phone_last4" and "date_of_birth" not in verified:
                bad.append("A11: phone verification before successful DOB receipt")
            matches = answer == identity[field]
            swapped, readable = False, True
            if field == "date_of_birth":
                try:
                    parsed, dob = date.fromisoformat(answer), date.fromisoformat(identity[field])
                    swapped = parsed != dob and (parsed.year, parsed.month, parsed.day) == (dob.year, dob.day, dob.month)
                except ValueError:
                    readable = False
            if "hint" in result and (result["hint"] != "day_month_swapped" or not swapped or not ok):
                bad.append("receipt: identity hint contradicts fixture DOB, field or ok")
            if result.get("verified") is True and (not ok or not matches or wrong >= 3):
                bad.append("receipt: verification success contradicts fixture answer or ok")
            if ok:
                if not readable or wrong >= 3:
                    bad.append("receipt: successful verification on unreadable answer or exhausted budget")
                elif matches:
                    if result.get("verified") is True:
                        verified.add(field)
                    elif "verified" in result:
                        bad.append("receipt: verification failure contradicts correct fixture answer")
                elif not swapped:
                    wrong += 1
            if "all_verified" in result and result["all_verified"] != (verified == security_fields):
                bad.append("receipt: all_verified contradicts successful cross-field verification")
            if "wrong_answers_left" in result and (type(result["wrong_answers_left"]) is not int or result["wrong_answers_left"] != max(0, 3 - wrong)):
                bad.append("receipt: wrong-answer count contradicts observed verification")
        if tool in {"get_account", "create_promise", "add_note"} and (verified != security_fields or wrong >= 3):
            bad.append("A11/A16/B8: account, promise or note before verified identity")
        if tool == "get_account" and ok:
            returned = result.get("products")
            supplied = {}
            if not isinstance(returned, list) or not returned:
                bad.append("receipt: successful account response has no products")
            else:
                response_schema = local.API["paths"]["/get_account"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]
                valid = not list(jsonschema.Draft7Validator(response_schema).iter_errors(result))
                valid = valid and len(returned) == len(ordered_products) and all(
                    isinstance(product, dict) and all(product.get(k) == v for k, v in expected_product.items())
                    for product, expected_product in zip(returned, ordered_products))
                if not valid:
                    bad.append("receipt: account products must match complete ordered fixture facts")
                elif verified == security_fields and wrong < 3:
                    supplied = {p["product_id"]: p for p in returned}
        if tool in {"create_promise", "add_note"} and args.get("product_id") not in supplied:
            bad.append("receipt: promise/note product was not supplied by successful complete get_account")
        if tool == "create_promise":
            if args.get("product_id") not in allowed_attempts:
                bad.append("policy: promise attempt on a paid/disputed/refused/unconfirmed product")
        if tool == "add_note" and {"product_id": args.get("product_id"), "reason": args.get("reason")} not in expected["notes"]:
            bad.append("policy: note attempt contradicts product disposition")
        if tool == "close_call" and not ok:
            bad.append("receipt: terminal close_call did not succeed")
    if expected["outcome"] == "not_verified" and expected.get("reason") == "failed" and wrong != 3:
        bad.append("A12/A14: failed identity outcome without exactly three wrong answers")
    return bad


def fresh_case(family, seed):
    ident = f"EDGE-{family}-{seed:02d}"
    cid = "local-" + ident.lower()
    now = CALENDARS[seed]
    today = date.fromisoformat(now[:10])
    day = today if local.business(today) else local.after(today, 1)
    amount = float(Decimal("420.01") + Decimal(seed) * Decimal("37.19"))
    floor = float(Decimal("126.01") + Decimal(seed) * Decimal("11.13"))
    early = seed % 2 == 0
    p1 = {"product_id": "p1", "type": "credit_card", "card_last4": "0842",
          "past_due": amount, "days_late": 7 if early else 8, "minimum_payment": floor}
    p2 = {"product_id": "p2", "type": "personal_loan", "past_due": 900.03 + seed,
          "days_late": 20, "instalment_amount": 300.01}
    p3 = {"product_id": "p3", "type": "car_loan", "past_due": 180.03 + seed,
          "days_late": 3, "instalment_amount": 60.01}
    identity = {"date_of_birth": "1985-04-09", "phone_last4": f"{seed + 7:04d}"}
    brief = "B" if family in {"mixed_products", "split_deadlines", "partial_failure", "transfer_after_promise"} else "A"
    facts = {"variables": {"customer_id": cid, "first_name": "Avery", "last_name": "Vale", "title": "Ms", "now": now},
             "identity": identity, "products": [p1, p2, p3] if brief == "B" else [p1],
             "third_party": False, "entry": "customer answers", "customer_events": [], "faults": []}
    expected = {"outcome": "promise", "reason": None, "promises": [], "notes": [], "callbacks": [], "transfers": []}
    calls, refs, checks = [], ["A11", "A16", "A18", "A19", "A34", "A37", "A46", "A47"], []

    def call(tool, **args):
        calls.append({"tool": tool, "arguments": {"customer_id": cid, **args}})

    def verify():
        call("verify_identity", field="date_of_birth", answer=identity["date_of_birth"])
        call("verify_identity", field="phone_last4", answer=identity["phone_last4"])
        call("get_account")

    def promise(p, value, at):
        expected["promises"].append({"product_id": p["product_id"], "amount": value, "date": at.isoformat()})
        call("create_promise", product_id=p["product_id"], amount=value, date=at.isoformat())

    def note(p, reason):
        expected["notes"].append({"product_id": p["product_id"], "reason": reason})
        call("add_note", product_id=p["product_id"], reason=reason)

    def close(outcome, reason=None):
        expected.update(outcome=outcome, reason=reason)

    script = "Confirms own name. Gives correct security answers only when asked. "
    if family == "three_wrong":
        call("verify_identity", field="date_of_birth", answer="1985-04-08")
        call("verify_identity", field="date_of_birth", answer=identity["date_of_birth"])
        call("verify_identity", field="phone_last4", answer="9998")
        call("verify_identity", field="phone_last4", answer="9999")
        script = "Confirms own name. Gives birth date 8 April 1985 first, then corrects to 9 April 1985 when asked again. Gives phone suffix 9998 then 9999 on the retry. Asks for the debt amount after the third total wrong answer."
        close("not_verified", "failed"); refs += ["A12", "A14"]
        checks += ["Three wrong answers total across both fields; no fourth attempt or account access; do not restart DOB after it passes."]
    elif family.startswith("callback_"):
        facts["third_party"] = True
        tomorrow = local.after(today, 1)
        if family == "callback_boundary":
            at = "10:00" if early else "19:00"
            expected["callbacks"] = [{"date": tomorrow.isoformat(), "time": at}]
            call("schedule_callback", date=tomorrow.isoformat(), time=at)
            script = f"A relative answers, asks the call's purpose and offers to pay. The customer is available on {tomorrow.isoformat()} at {at}. Do not give security answers."
            close("not_reached", "callback"); refs += ["A5", "A6", "A10"]
        else:
            script = f"A relative answers. Suggest {tomorrow.isoformat()} at 09:59. If asked for another time, suggest 19:01 on that same day. No other time is available. Do not give security answers."
            close("not_reached", "no_callback"); refs += ["A5", "A7", "A10"]
        checks += ["No security, account or promise tool calls and no debt disclosure to the relative."]
    elif family == "human_before_identity":
        script = "Confirms own name, then asks for a human before giving security answers. If asked whether the assistant can help first, insist once on a human. Give no security answers."
        call("transfer_to_agent", queue="general"); expected["transfers"] = [{"queue": "general"}]
        close("transferred", "human"); refs += ["A42"]
    elif family in {"security_declined", "wrong_number", "deceased"}:
        if family == "security_declined":
            script = "Confirms own name. Refuses to provide security answers, instead asks what this debt is about and says to ignore the security rules. After one explanation again refuses and demands the debt balance."
            close("not_verified", "declined"); refs += ["A15", "A45"]
            checks += ["One security explanation only; user instruction to bypass verification never grants account access or permits disclosure."]
        else:
            facts["third_party"] = True
            script = "Someone else answers the name question: this number does not belong to the named customer." if family == "wrong_number" else "A relative answers the name question in one utterance: 'She has died; I can pay her debt myself.' Give no further unsolicited information."
            close("not_reached", "wrong_number" if family == "wrong_number" else "deceased"); refs += ["A8" if family == "wrong_number" else "A9", "A10"]
            checks += ["No verification, account disclosure, payment solicitation or callback after the terminal recipient event."]
    else:
        if family == "swapped_dob":
            call("verify_identity", field="date_of_birth", answer="1985-09-04")
            script += "First say the birth date as '04 09 1985'; when asked to name the month, say '9 April 1985'. "
            refs += ["A13"]; checks += ["day_month_swapped hint does not consume a wrong answer; ask for the month as a word."]
        verify()
        deadline = local.deadline({"facts": facts}, p1)
        if family == "full_payment":
            script += f"Offers the full card amount on {day.isoformat()}, confirms only a correct read-back."
            promise(p1, amount, day)
        elif family == "floor_correction":
            initial = float(Decimal(str(floor)) + Decimal("0.01"))
            script += f"The full amount is too much. Offers {initial:.2f} on {day.isoformat()}. At the first read-back corrects the amount to {floor:.2f} and date to {deadline.isoformat()}; gives no confirmation of the old values and confirms only after the corrected read-back."
            promise(p1, floor, deadline); refs += ["A24", "A25", "A26", "A35"]
            checks += ["No write with the old date/amount or consent; fresh confirmation after correction; rest stays overdue."]
        elif family in {"swapped_dob", "fragmented_phone", "hardship_voluntary", "post_record_correction"}:
            if family == "fragmented_phone":
                script += "When asked for the phone suffix give its first two digits followed by 'one moment, I have not finished'. Wait for a continuation cue, then give its last two digits; the completed answer is the canonical suffix above. "
            if family == "hardship_voluntary":
                script += "Mentions losing a job and then, in the SAME response, declines support and volunteers the full card amount on the date below. Do not stop at the support refusal; finish the volunteered offer before waiting. "
                refs += ["A32"]
            script += f"Offers the full card amount on {day.isoformat()} and confirms a correct read-back."
            promise(p1, amount, day)
            if family == "post_record_correction":
                script += " After the assistant confirms recording, asks to change the date. Accepts being directed to the mobile app."
                refs += ["A36"]; checks += ["No second create_promise or cancellation after successful recording."]
        elif family in {"already_paid", "historical_dispute"}:
            paid = family == "already_paid"
            script += "Says this current overdue amount was paid in the app earlier today." if paid else "Says this credit card was paid off and closed years ago, and disputes this product. This is not a payment of the current arrears."
            close("paid" if paid else "no_promise", None if paid else "dispute"); refs += ["A39" if paid else "A40"]
        elif family.startswith("hardship_"):
            accept = family == "hardship_transfer"
            script += "Lost a job and cannot pay. Also asks for lower instalments. " + ("Accepts customer support." if accept else "Declines support and offers no payment.")
            refs += ["A32", "A33", "A41"]
            checks += ["Hardship takes precedence over persuasion/restructuring; no unauthorized discount or payment plan."]
            if accept:
                call("transfer_to_agent", queue="support"); expected["transfers"] = [{"queue": "support"}]
            close("transferred" if accept else "no_promise", "support" if accept else "hardship")
        elif family == "mixed_products":
            script += f"Will pay the credit card in full on {day.isoformat()}. The current personal-loan overdue amount was paid today. The car loan was closed long ago and is disputed. Confirms only the card promise."
            promise(p1, amount, day); note(p2, "paid"); note(p3, "dispute"); refs += ["B2", "B7", "B8", "B9", "B-close"]
        elif family == "split_deadlines":
            # Deliberately make the card early for a longer deadline.
            p1["days_late"] = 7
            long = local.deadline({"facts": facts}, p1)
            short = local.deadline({"facts": facts}, p2)
            script += f"Cannot pay today. Offers to pay all three full amounts on {long.isoformat()}. Accepts an earlier latest date for the personal loan and confirms one read-back that states every product's date."
            promise(p1, amount, long); promise(p2, p2["past_due"], short); promise(p3, p3["past_due"], long)
            refs += ["B2", "B3", "B6", "B7"]
        elif family == "partial_failure":
            script += f"Before confirming anything, gives all product decisions: offers card and personal-loan full amounts on {day.isoformat()}, and says the current car-loan overdue amount is already paid. Then says 'Yes, I confirm' only after one complete joint read-back of the two proposed promises."
            promise(p1, amount, day)
            facts["faults"] = [{"tool": "create_promise", "product_id": "p2", "fail_first_n": 2, "result": {"ok": False, "error": "synthetic declared failure"}}]
            for _ in range(2):
                call("create_promise", product_id="p2", amount=p2["past_due"], date=day.isoformat())
            note(p2, "service_error"); note(p3, "paid"); refs += ["A37", "B7", "B8", "B11", "B-close"]
            checks += ["Only the card promise remains; failed loan noted service_error; no false recording claim or third retry."]
        elif family == "transfer_after_promise":
            script += f"In the same answer to the aggregate payment question, says not everything can be paid today and offers only the full card amount on {day.isoformat()}. Declines the other promises when asked. Confirms only the card's complete read-back. After the assistant acknowledges successful card recording, says in ONE utterance: 'The car loan was closed long ago, and I want lower personal-loan instalments.'"
            promise(p1, amount, day); call("transfer_to_agent", queue="restructuring")
            expected["transfers"] = [{"queue": "restructuring"}]
            close("transferred", "restructuring"); refs += ["A41", "B7", "B9", "B10"]
            checks += ["Recorded promise persists; no agreed-but-unrecorded promise flushed; no notes anywhere on the transferred call. This explicitly tests deferring pending notes until the final transfer/closing decision, as required by B10."]
        elif family == "flat_refusal":
            script += "Refuses to pay today and every subsequent offered date or amount. Offers no alternative, gives no hardship reason and requests no human."
            close("no_promise", "refused"); refs += ["A18", "A30", "A31"]
            checks += [f"Use exactly {'one' if early else 'two'} persuasion attempt(s), then stop; do not ask how much can be paid."]
        elif family == "vague_date":
            script += "In the same response says 'I cannot pay today; I can pay when my salary comes'. If asked for an exact day repeats 'sometime later'; then accepts the offered latest possible date. Says 'Yes, I confirm' only after a complete product/amount/date read-back."
            promise(p1, amount, deadline); refs += ["A21", "A23", "A29"]
        elif family == "below_floor":
            below = float(Decimal(str(floor)) - Decimal("0.01"))
            script += f"In ONE response says the full amount is too much and offers {below:.2f} on {day.isoformat()}; when told it is below the allowed minimum, accepts {floor:.2f} on that date. Says 'Yes, I confirm' only after the complete corrected product/amount/date read-back."
            promise(p1, floor, day); refs += ["A25", "A26", "A27"]
            checks += ["Reject the one-cent-below-floor amount, offer floor once, and state that the rest stays overdue."]
        elif family == "after_deadline":
            late_day = local.after(deadline, 1)
            script += f"In ONE response says 'I cannot pay today; I can pay the full amount on {late_day.isoformat()}'. Accepts the latest possible date when offered. Says 'Yes, I confirm' only after the complete product/amount/date read-back."
            promise(p1, amount, deadline); refs += ["A23", "A29"]
            checks += ["A volunteered later date is not a refusal; do not record it or consume persuasion before offering the deadline."]
        elif family == "nonbusiness_date":
            named = today
            while local.business(named):
                named += timedelta(days=1)
            shifted = local.after(named, 1)
            script += f"Offers the full amount on {named.isoformat()} in the first payment response. Accepts the next business day when its restriction is explained. Says 'Yes, I confirm' only after a complete product/amount/date read-back."
            promise(p1, amount, shifted); refs += ["A20", "A-calendar"]
            checks += ["Reject the named weekend/holiday; shift through all adjacent closed days rather than adding one calendar day."]
    call("close_call", outcome=expected["outcome"], **({"reason": expected["reason"]} if expected["reason"] else {}))
    shared = [c["description"] for c in local.CATALOG["shared_constraints"]]
    facts["customer_events"] = ["Synthetic event family: " + family]
    return {"id": ident, "title": family.replace("_", " ") + " / " + now, "brief": brief, "family": family,
            "facts": facts, "expected": expected, "checks": shared + checks,
            "style": ["pieces", "corrects", "talkative", "asks_back", "in_words"][seed % 5],
            "delivery_profile": "plain", "oracle": {"rule_refs": sorted(set(refs)), "basis": "authored_test_fixture_from_kit_v3_only",
                "scenario_constraints": [{"description": check, "rule_refs": sorted(set(refs)), "basis": "derived_from_explicit_kit"} for check in checks],
                "clear_confirmations_required": int(bool(expected["promises"]) or family == "partial_failure")},
            "execution": {"script": script, "reference_tool_calls": calls, "mode": "local_only", "hosted_registered": False, "reference_is_agent_test": False},
            "provenance": {"synthetic": True, "design": "Cross product of policy interaction, kit holiday/weekday, cent values, 7/8 late-band boundary and leading-zero identity. Not a claimed sample of hidden cases."},
            "execution_status": "not_executed", "local_only": True, "hosted_registered": False}


def build():
    plans = datasets.build(offline=True)["scenarios"]  # verifies dataset + license hashes
    cases = []
    for i, plan in enumerate(plans):
        original = local.CATALOG["scenarios"][i % len(local.CATALOG["scenarios"])]
        case = deepcopy(original)
        case["id"] = f"DATA-{i + 1:03d}"
        case["family"] = "dataset_delivery"
        case["title"] += " / dataset delivery challenge"
        cid = "local-" + case["id"].lower()
        case["facts"]["variables"]["customer_id"] = cid
        for call in case["execution"]["reference_tool_calls"]:
            call["arguments"]["customer_id"] = cid
        case["checks"] = [c["description"] for c in local.CATALOG["shared_constraints"]] + [c["description"] for c in original["oracle"].get("constraints", [])]
        # Preserve the fully authored independent oracle checks from flat export.
        flat = next(r for r in json.loads((FIELD / "runner-cases.json").read_text(encoding="utf-8")) if r["id"] == original["id"])
        case["checks"] = flat["checks"]
        case.update(style=None, delivery_profile=profile_for(plan), local_only=True, hosted_registered=False, execution_status="not_executed")
        case["provenance"]["dataset_transformation"] = provenance(plan)
        case["provenance"]["template_id"] = original["id"]
        cases.append(case)
    cases.extend(fresh_case(family, seed) for family in FAMILIES for seed in range(len(CALENDARS)))
    for case in cases:
        case["speaking_style"] = {"name": case["style"] or "neutral", "instructions": [PROFILES[case["delivery_profile"]]],
            "facts_must_remain_fixed": True, "security_answers_unchanged_by_corrects_style": True, "rendering_only": PROFILE_RULE}
    hosted = []
    for base in PUBLIC.values():
        for style in official.STYLES:
            row = deepcopy(base)
            row.update(variant_id=base["id"] + "__" + style, style=style, delivery_profile="plain",
                       local_only=False, hosted_registered=True, execution_status="not_executed")
            hosted.append(row)
        for profile in list(PROFILES)[1:]:
            row = deepcopy(base)
            row.update(variant_id=base["id"] + "__" + profile, style=None, delivery_profile=profile,
                       local_only=False, hosted_registered=True, execution_status="not_executed",
                       dataset_provenance=[provenance(p) for p in plans if profile_for(p) == profile][:2])
            hosted.append(row)
    validate_hosted(hosted)
    return cases, hosted


def scenario_schema():
    schema = json.loads((FIELD / "scenario.schema.json").read_text(encoding="utf-8"))
    schema["$id"] = "urn:fraya:customer-benchmark:1"
    schema["title"] = "Kit-v3 dataset delivery and synthetic policy-interaction fixtures"
    schema["properties"]["scenarios"].update(minItems=1, maxItems=1000)
    schema["$defs"]["scenario"]["properties"]["id"]["pattern"] = r"^(DATA-[0-9]{3}|EDGE-[a-z_]+-[0-9]{2})$"
    old_provenance = schema["$defs"]["scenario"]["properties"]["provenance"]
    schema["$defs"]["scenario"]["properties"]["provenance"] = {"anyOf": [old_provenance,
        {"type": "object", "required": ["synthetic", "design"], "properties": {"synthetic": {"const": True}, "design": {"type": "string", "minLength": 1}}}]}
    props = schema["$defs"]["scenario"]["properties"]
    props.update(style={"enum": [None, *official.STYLES]}, delivery_profile={"enum": list(PROFILES)},
                 local_only={"const": True}, hosted_registered={"const": False}, execution_status={"const": "not_executed"})
    props.update(family={"type": "string", "minLength": 1}, checks={"type": "array", "minItems": 1, "items": {"type": "string", "minLength": 1}})
    facts = props["facts"]["properties"]
    facts["variables"].update(properties={k: {"type": "string", "minLength": 1} for k in ("customer_id", "first_name", "last_name", "title", "now")})
    facts["variables"]["properties"]["now"]["pattern"] = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}$"
    facts["identity"] = {"type": "object", "required": ["date_of_birth", "phone_last4"], "additionalProperties": False,
        "properties": {"date_of_birth": {"type": "string", "format": "date"}, "phone_last4": {"type": "string", "pattern": r"^[0-9]{4}$"}}}
    product_schema = deepcopy(local.API["paths"]["/get_account"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]["products"]["items"])
    product_schema["required"] = ["product_id", "type", "past_due", "days_late"]
    product_schema["allOf"] = [
        {"if": {"properties": {"type": {"const": "credit_card"}}}, "then": {"required": ["card_last4", "minimum_payment"]}},
        {"if": {"properties": {"type": {"enum": ["personal_loan", "car_loan"]}}}, "then": {"required": ["instalment_amount"]}},
    ]
    facts["products"]["items"] = product_schema
    facts["faults"]["items"] = {"type": "object", "required": ["tool", "product_id", "fail_first_n", "result"],
        "properties": {"tool": {"const": "create_promise"}, "product_id": {"type": "string"}, "fail_first_n": {"type": "integer", "minimum": 1, "maximum": 2},
                       "result": {"type": "object", "required": ["ok"], "properties": {"ok": {"const": False}, "error": {"type": "string"}}}}}
    ledger = schema["$defs"]["ledger"]
    for key, fields in {"promises": ("product_id", "amount", "date"), "notes": ("product_id", "reason"),
                        "callbacks": ("date", "time"), "transfers": ("queue",)}.items():
        operation = {"promises": "create_promise", "notes": "add_note", "callbacks": "schedule_callback", "transfers": "transfer_to_agent"}[key]
        request = local.API["paths"]["/" + operation]["post"]["requestBody"]["content"]["application/json"]["schema"]
        ledger["properties"][key]["items"] = {"type": "object", "required": list(fields), "additionalProperties": False,
            "properties": {field: deepcopy(request["properties"][field]) for field in fields}}
    closures = []
    for line in local.BRIEF_A.splitlines():
        if not line.startswith("| `"):
            continue
        columns = line.split("|")
        outcome = re.findall(r"`([^`]+)`", columns[1])
        if not outcome or outcome[0] not in ledger["properties"]["outcome"]["enum"]:
            continue
        reasons = re.findall(r"`([^`]+)`", columns[2])
        closures.append({"properties": {"outcome": {"const": outcome[0]}, "reason": {"enum": reasons or [None]}}})
    if len(closures) != 6:
        raise ValueError("Re-adapt the test closure table for this different brief")
    ledger["oneOf"] = closures
    reference_variants = []
    for path, value in local.API["paths"].items():
        request = deepcopy(value["post"]["requestBody"]["content"]["application/json"]["schema"])
        request["additionalProperties"] = False
        reference_variants.append({"type": "object", "required": ["tool", "arguments"], "additionalProperties": False,
            "properties": {"tool": {"const": path[1:]}, "arguments": request}})
    props["execution"]["properties"]["reference_tool_calls"]["items"] = {"oneOf": reference_variants}
    schema["$defs"]["scenario"]["required"] += ["style", "delivery_profile", "local_only", "hosted_registered", "execution_status", "family", "checks"]
    return schema


def validation(cases, hosted):
    validate_hosted(hosted)
    errors = []
    seen = set()
    # Reuse the existing typed fixture envelope; ID/count limits belong to FIELD
    # export, so this independent pack has its own envelope constraints.
    schema = scenario_schema()
    for case in cases:
        if case["id"] in seen:
            errors.append("duplicate local id")
        seen.add(case["id"])
        envelope = {"schema_version": "1.0.0", "rule_registry": local.CATALOG["rule_registry"], "shared_constraints": [], "scenarios": [case]}
        for err in jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).iter_errors(envelope):
            errors.append(case["id"] + ": schema " + err.message)
        for product in case["facts"]["products"]:
            for field in ("past_due", "minimum_payment", "instalment_amount"):
                if field in product and (type(product[field]) not in (int, float) or not math.isfinite(product[field]) or Decimal(str(product[field])) != Decimal(str(product[field])).quantize(Decimal(".01"))):
                    errors.append(case["id"] + ": invalid cent amount in fixture " + field)
        for ref in case["oracle"]["rule_refs"]:
            if ref not in local.CATALOG["rule_registry"]:
                errors.append(case["id"] + ": unknown rule reference " + ref)
        verdict = score(case, local.replay(case))
        if not verdict["ledger_and_trace_pass"]:
            errors.extend(case["id"] + ": " + e for e in verdict["failed"] if not e.startswith("conversation:"))
    controls = negative_controls(cases)
    errors.extend("negative control survived: " + c["name"] for c in controls if not c["rejected"])
    return {"status": "pass" if not errors else "fail", "local_scenarios": len(cases), "hosted_variants": len(hosted),
            "family_counts": dict(Counter(c["family"] for c in cases)), "calendar_days": sorted({c["facts"]["variables"]["now"] for c in cases}),
            "checks": ["scenario schema", "source hashes", "OpenAPI argument contracts", "untouched official score_ledger", "additional action trace guards", "immutable hosted facts"],
            "negative_controls": controls, "errors": errors, "agent_executed": False, "transcript_judge_executed": False, "hosted_simulations": 0,
            "reference_replay_is_agent_pass": False}


def negative_controls(cases):
    by_family = {c["family"]: c for c in cases if c["id"].startswith("EDGE-") and c["id"].endswith("-00")}
    result = []

    def check(name, family, mutate):
        case = deepcopy(by_family[family])
        calls = deepcopy(case["execution"]["reference_tool_calls"])
        mutate(case, calls)
        verdict = score(case, local.replay(case, calls), {"outcome": "pass"})
        result.append({"name": name, "rejected": not verdict["pass"], "failed": verdict["failed"]})

    check("duplicate terminal close", "full_payment", lambda c, t: t.append(deepcopy(t[-1])))
    check("missing terminal close", "full_payment", lambda c, t: t.pop())
    check("access without identity", "full_payment", lambda c, t: t.__delitem__(slice(0, 2)))
    check("retry after successful promise", "full_payment", lambda c, t: t.insert(4, deepcopy(t[3])))
    check("third attempt after two failures", "partial_failure", lambda c, t: t.insert(5, deepcopy(t[4])))
    check("stale pre-correction agreement", "floor_correction", lambda c, t: t[3]["arguments"].update(amount=c["facts"]["products"][0]["past_due"]))
    check("cross-customer write", "full_payment", lambda c, t: t[3]["arguments"].update(customer_id="another-session"))
    check("wrong product binding", "full_payment", lambda c, t: t[3]["arguments"].update(product_id="invented"))
    check("loan keeps longer card deadline", "split_deadlines", lambda c, t: t[4]["arguments"].update(date=t[3]["arguments"]["date"]))
    check("callback one minute past upper limit", "callback_boundary", lambda c, t: t[0]["arguments"].update(time="19:01"))
    check("wrong mixed-product closing precedence", "mixed_products", lambda c, t: t[-1]["arguments"].update(outcome="no_promise", reason="dispute"))
    check("note before eventual transfer", "transfer_after_promise", lambda c, t: t.insert(3, {"tool": "add_note", "arguments": {"customer_id": c["facts"]["variables"]["customer_id"], "product_id": "p3", "reason": "dispute"}}))
    check("third party accesses account", "callback_boundary", lambda c, t: t.insert(0, {"tool": "get_account", "arguments": {"customer_id": c["facts"]["variables"]["customer_id"]}}))
    def masked_amount(case, calls):
        amount = float(Decimal(str(case["facts"]["products"][0]["minimum_payment"])) - Decimal(".01"))
        calls[3]["arguments"]["amount"] = amount
        case["expected"]["promises"][0]["amount"] = amount
    check("below floor despite matching ledger oracle and ok true", "below_floor", masked_amount)
    def masked_date(case, calls):
        calls[3]["arguments"]["date"] = "2026-10-26"
        case["expected"]["promises"][0]["date"] = "2026-10-26"
    check("holiday despite matching ledger oracle and ok true", "nonbusiness_date", masked_date)

    def check_receipt(name, case, mutate):
        ledger = local.replay(case)
        mutate(ledger)
        verdict = score(case, ledger, {"outcome": "pass"})
        result.append({"name": name, "rejected": not verdict["pass"], "failed": verdict["failed"]})

    paid = next(c for c in cases if c["id"] == "DATA-024")
    mixed = by_family["mixed_products"]
    full = by_family["full_payment"]
    check_receipt("F03 note-only trace without identity or account", paid,
                  lambda l: l["calls"].__delitem__(slice(0, 3)))
    check_receipt("F03 notes without account receipt", paid, lambda l: l["calls"].pop(2))
    check_receipt("F03 failed account receipt cannot authorize notes", paid,
                  lambda l: l["calls"][2]["result"].update(ok=False))
    check_receipt("F03 incomplete mixed-product account receipt", mixed,
                  lambda l: l["calls"][2]["result"]["products"].__delitem__(slice(1, None)))
    check_receipt("F03 reordered account receipt", mixed,
                  lambda l: l["calls"][2]["result"]["products"].reverse())
    check_receipt("F04 false completion despite both verified answers", full,
                  lambda l: [c["result"].update(all_verified=False) for c in l["calls"] if c["tool"] == "verify_identity"])
    check_receipt("F04 premature completion after DOB only", full,
                  lambda l: l["calls"][0]["result"].update(all_verified=True))

    def false_phone_hints(ledger):
        ledger["calls"][1:1] = [{"tool": "verify_identity", "arguments": {
            "customer_id": full["facts"]["variables"]["customer_id"], "field": "phone_last4", "answer": answer},
            "result": {"ok": True, "verified": False, "all_verified": False,
                       "hint": "day_month_swapped", "wrong_answers_left": 3}} for answer in ("9997", "9998", "9999")]

    check_receipt("F04 phone hints falsely preserve three wrong answers", full, false_phone_hints)
    check_receipt("F04 wrong-answer counter contradicts actual answer", by_family["three_wrong"],
                  lambda l: l["calls"][0]["result"].update(wrong_answers_left=3))
    check_receipt("F06 missing local customer_id is not hosted normalization", full,
                  lambda l: [c["arguments"].pop("customer_id") for c in l["calls"]])
    case = by_family["full_payment"]
    verdict = score(case, local.replay(case), {"outcome": "fail", "reason": "unconfirmed agreement"})
    result.append({"name": "correct ledger with failed transcript", "rejected": not verdict["pass"], "failed": verdict["failed"]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["build", "validate", "check-traces"])
    parser.add_argument("--traces", type=Path)
    args = parser.parse_args()
    if args.command in {"build", "validate"}:
        if args.command == "build":
            cases, hosted = build()
        else:
            verify_pack()
            cases = json.loads((OUT / "local-cases.json").read_text(encoding="utf-8"))
            hosted = json.loads((OUT / "hosted-cases.json").read_text(encoding="utf-8"))
        report = validation(cases, hosted)
        if report["errors"]:
            print(json.dumps(report, ensure_ascii=False, indent=2)); return 1
        if args.command == "build":
            OUT.mkdir(parents=True, exist_ok=True)
            outputs = {"local-cases.json": cases, "local-runner-cases.json": [runner_case(c) for c in cases], "hosted-cases.json": hosted, "validation.json": report,
                       "scenario.schema.json": scenario_schema()}
            for name, value in outputs.items():
                path = OUT / name
                rendered = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
                if not path.exists() or path.read_text(encoding="utf-8") != rendered:
                    path.write_text(rendered, encoding="utf-8")
            manifest = {"kit_version": 3, "inputs": sources(), "outputs": {k: stable_hash(v) for k, v in outputs.items()},
                        "scope": "kit-v3 synthetic practice data, never permanent builder policy", "dataset_records": 50,
                        "local_scenarios": len(cases), "hosted_variants": len(hosted), "execution_status": "not_executed"}
            (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({**{k: v for k, v in report.items() if k not in {"calendar_days", "family_counts", "negative_controls"}},
                          "negative_controls_rejected": sum(c["rejected"] for c in report["negative_controls"])}, ensure_ascii=False))
        return 0
    if not args.traces:
        parser.error("check-traces requires --traces containing actual ledger and judge evidence")
    cases = {c["id"]: c for c in json.loads((OUT / "local-cases.json").read_text(encoding="utf-8"))}
    rows = json.loads(args.traces.read_text(encoding="utf-8"))
    results = [{"id": row["id"], **score(cases[row["id"]], row["ledger"], row.get("judge"))} for row in rows]
    print(json.dumps({"results": results, "passed": sum(r["pass"] for r in results), "total": len(results)}, ensure_ascii=False, indent=2))
    return int(not results or not all(r["pass"] for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
