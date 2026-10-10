"""Offline fixture adapter, ledger oracle and bounded trace checks, never a hosted runner.

validate: schema/contracts, source anchors, calendar, 28 canonical replay fixtures,
and negative control traces. A reference replay is not a generated-agent test.
check-traces: check actual supplied ledger/tool evidence; prose needs its own judge.
"""
from collections import Counter
from copy import deepcopy
from datetime import date, datetime, timedelta
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import sys

import jsonschema

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
KIT = ROOT / "competition-v3/build-the-builder"
API = json.loads((KIT / "tools/openapi.json").read_text(encoding="utf-8"))
CATALOG = json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))
CASES = {c["id"]: c for c in CATALOG["scenarios"]}
SCORE = runpy.run_path(str(KIT / "tools/score.py"))["score_ledger"]
BRIEF_A = (KIT / "briefs/brief-a.md").read_text(encoding="utf-8")
CALENDAR_LINE = next(line for line in BRIEF_A.splitlines() if line.startswith("Business days are"))
HOLIDAYS = {date.fromisoformat(s) for s in re.findall(r"\d{4}-\d{2}-\d{2}", CALENDAR_LINE)}
BANDS = [(int(lo), int(hi), int(offset)) for lo, hi, offset in re.findall(r"\|\s*(\d+) to (\d+)\s*\|[^|]+\|\s*the (\d+)(?:th|st|nd|rd) business day", BRIEF_A)]
assert len(BANDS) == 2, "This local adapter supports the inspected kit table; re-adapt for a new brief."

def business(day):
    return day.weekday() < 5 and day not in HOLIDAYS

def after(day, count):
    while count:
        day += timedelta(days=1)
        count -= int(business(day))
    return day

def deadline(case, product):
    offset = next(n for lo, hi, n in BANDS if lo <= product["days_late"] <= hi)
    return after(date.fromisoformat(case["facts"]["variables"]["now"][:10]), offset)

def request_errors(call):
    path = "/" + call["tool"]
    if path not in API["paths"]:
        return ["tool not in supplied OpenAPI: " + call["tool"]]
    schema = API["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]
    errors = [e.message for e in jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker()).iter_errors(call["arguments"])]
    if set(call["arguments"]) - set(schema["properties"]):
        errors.append("fixture uses undocumented request fields")
    return errors

class Bank:
    """A fresh local fixture per instance; no network and no credentials.

    Like the supplied OpenAPI mock, create_promise does not enforce dates/floors.
    The separate oracle below checks those even when the stub returns ok:true.
    This mock's error strings/ids are synthetic and not asserted as hosted behavior.
    """
    def __init__(self, case):
        self.case = case
        self.facts = case["facts"]
        self.verified = set()
        self.wrong = 0
        self.attempts = Counter()
        self.closed = False
        self.ledger = {"outcome": None, "reason": None, "promises": [], "notes": [], "callbacks": [], "transfers": [], "calls": []}

    def call(self, tool, arguments):
        args = deepcopy(arguments)
        errors = request_errors({"tool": tool, "arguments": args})
        if errors:
            result = {"ok": False, "error": "; ".join(errors)}
        elif args["customer_id"] != self.facts["variables"]["customer_id"]:
            result = {"ok": False, "error": "wrong local customer_id"}
        elif self.closed:
            result = {"ok": False, "error": "local call already closed"}
        else:
            result = self._apply(tool, args)
        self.ledger["calls"].append({"tool": tool, "arguments": args, "result": result})
        return result

    def _apply(self, tool, a):
        if tool == "verify_identity":
            field, answer = a["field"], a["answer"]
            if self.wrong >= 3:
                return {"ok": False, "verified": False, "wrong_answers_left": 0}
            if field == "date_of_birth":
                try:
                    parsed = date.fromisoformat(answer)
                except ValueError:
                    return {"ok": False, "verified": False, "wrong_answers_left": 3 - self.wrong, "error": "unreadable local date"}
                dob = date.fromisoformat(self.facts["identity"][field])
                if parsed != dob and parsed.year == dob.year and parsed.day == dob.month and parsed.month == dob.day:
                    return {"ok": True, "verified": False, "all_verified": False, "wrong_answers_left": 3 - self.wrong, "hint": "day_month_swapped"}
            passed = answer == self.facts["identity"][field]
            if passed:
                self.verified.add(field)
            else:
                self.wrong += 1
            return {"ok": True, "verified": passed, "all_verified": len(self.verified) == 2, "wrong_answers_left": 3 - self.wrong}
        if tool in ("get_account", "create_promise") and len(self.verified) != 2:
            return {"ok": False, "error": "identity not verified"}
        if tool == "get_account":
            return {"ok": True, "products": deepcopy(self.facts["products"])}
        if tool in ("create_promise", "add_note"):
            if a["product_id"] not in {p["product_id"] for p in self.facts["products"]}:
                return {"ok": False, "error": "unknown product_id"}
        if tool == "create_promise":
            key = (tool, a["product_id"])
            self.attempts[key] += 1
            for fault in self.facts["faults"]:
                if fault["tool"] == tool and fault["product_id"] == a["product_id"] and self.attempts[key] <= fault["fail_first_n"]:
                    return deepcopy(fault["result"])
            if any(p["product_id"] == a["product_id"] for p in self.ledger["promises"]):
                return {"ok": False, "error": "local promise already recorded"}
            self.ledger["promises"].append({k: a[k] for k in ("product_id", "amount", "date")})
            return {"ok": True, "promise_id": "synthetic-" + a["product_id"]}
        if tool == "add_note":
            self.ledger["notes"].append({k: a[k] for k in ("product_id", "reason")})
        elif tool == "schedule_callback":
            self.ledger["callbacks"].append({k: a[k] for k in ("date", "time")})
        elif tool == "transfer_to_agent":
            self.ledger["transfers"].append({"queue": a["queue"]})
        elif tool == "close_call":
            self.ledger["outcome"], self.ledger["reason"] = a["outcome"], a.get("reason")
            self.closed = True
        return {"ok": True}

def replay(case, calls=None):
    bank = Bank(case)
    for call in calls if calls is not None else case["execution"]["reference_tool_calls"]:
        bank.call(call["tool"], call["arguments"])
    return bank.ledger

def trace_errors(case, ledger):
    """Independently check chronology/contract and selected policy consequences.

    Not a transcript judge. Cannot establish a spoken clear yes, empathy, opening,
    persuasion count, read-back, or truthfulness without actual conversation evidence.
    """
    bad, verified, recorded, seen_account = [], set(), set(), False
    calls = ledger["calls"]
    tools = [c["tool"] for c in calls]
    if tools.count("close_call") != 1 or not tools or tools[-1] != "close_call":
        bad.append("A46: exactly one terminal close_call required")
    if case["facts"]["third_party"] and any(t in tools for t in ("verify_identity", "get_account", "create_promise")):
        bad.append("A5/A10: third-party account or identity action")
    if case["brief"] == "A" and "add_note" in tools:
        bad.append("A-close: Brief A uses no add_note")
    if "transfer_to_agent" in tools and "add_note" in tools:
        bad.append("B10: notes anywhere on a transferred call forbidden")
    products = {p["product_id"]: p for p in case["facts"]["products"]}
    counters = Counter()
    reconstructed = {"outcome": None, "reason": None, "promises": [], "notes": [], "callbacks": [], "transfers": []}
    transferred = False
    for c in calls:
        tool, a, result = c["tool"], c["arguments"], c["result"]
        bad.extend("OpenAPI: " + x for x in request_errors(c))
        if a.get("customer_id") != case["facts"]["variables"]["customer_id"]:
            bad.append("A-vars: wrong customer_id")
        if tool == "verify_identity":
            if a["field"] == "phone_last4" and "date_of_birth" not in verified:
                bad.append("A11: phone verification before DOB passed")
            if result.get("verified"):
                verified.add(a["field"])
        if tool in ("get_account", "create_promise") and len(verified) != 2:
            bad.append("A11/A16: account access/promise before verification")
        if tool == "get_account" and result.get("ok"):
            seen_account = True
        if tool in ("create_promise", "add_note") and a.get("product_id") not in products:
            bad.append("O-get_account: unknown product id")
        if tool == "create_promise":
            if not seen_account:
                bad.append("A16/O-get_account: product not supplied by account tool")
            if transferred:
                bad.append("B10: promise write after transfer")
            pid = a.get("product_id")
            counters[pid] += 1
            if counters[pid] > 2:
                bad.append("A37/B11: more than one promise retry")
            if pid in recorded:
                bad.append("A36: another promise call for recorded product")
            p = products.get(pid)
            if p:
                floor = p["minimum_payment"] if p["type"] == "credit_card" else p["instalment_amount"]
                if not floor <= a["amount"] <= p["past_due"]:
                    bad.append("A25/A27: invalid amount")
                day = date.fromisoformat(a["date"])
                today = date.fromisoformat(case["facts"]["variables"]["now"][:10])
                if not business(day) or not today <= day <= deadline(case, p):
                    bad.append("A18/A19: invalid promise date")
            if result.get("ok"):
                recorded.add(pid)
                reconstructed["promises"].append({k: a[k] for k in ("product_id", "amount", "date")})
        if tool == "schedule_callback":
            now = datetime.fromisoformat(case["facts"]["variables"]["now"])
            at = datetime.fromisoformat(a["date"] + "T" + a["time"])
            if at.date() not in {now.date(), after(now.date(), 1)} or not "10:00" <= a["time"] <= "19:00" or at <= now:
                bad.append("A6: invalid callback date/time")
        if tool == "transfer_to_agent" and result.get("ok"):
            transferred = True
        if result.get("ok"):
            if tool == "add_note":
                reconstructed["notes"].append({k: a[k] for k in ("product_id", "reason")})
            elif tool == "schedule_callback":
                reconstructed["callbacks"].append({k: a[k] for k in ("date", "time")})
            elif tool == "transfer_to_agent":
                reconstructed["transfers"].append({"queue": a["queue"]})
            elif tool == "close_call":
                reconstructed["outcome"], reconstructed["reason"] = a["outcome"], a.get("reason")
    if any(reconstructed[k] != ledger[k] for k in reconstructed):
        bad.append("tool evidence and reported ledger disagree")
    return bad

def evaluate(case, ledger):
    result = SCORE({"expected": case["expected"]}, ledger)
    result["failed"].extend(trace_errors(case, ledger))
    result["pass"] = not result["failed"]
    result["scope"] = "ledger_and_selected_tool_trace_guards_only"
    result["transcript_verdict"] = "not_assessed"
    result["is_agent_policy_pass"] = False
    return result

def validation():
    failures = []
    schema = json.loads((HERE / "scenario.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(CATALOG, schema)
    sources = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))["sources"]
    source_map = {s["id"]: s for s in sources}
    exported = json.loads((HERE / "runner-cases.json").read_text(encoding="utf-8"))
    assert len(CASES) == len(CATALOG["scenarios"]) == len(exported) == 28
    assert len(source_map) == len(sources) == 16
    for record in json.loads((HERE / "official-inputs.json").read_text(encoding="utf-8")):
        if hashlib.sha256((ROOT / record["path"]).read_bytes()).hexdigest() != record["sha256"]:
            failures.append("inspected source changed: " + record["path"])
    for key, ref in CATALOG["rule_registry"].items():
        path = ROOT / ref["path"]
        if "line" in ref:
            lines = path.read_text(encoding="utf-8").splitlines()
            assert 0 < ref["line"] <= len(lines), key
            if re.fullmatch("[AB][0-9]+", key):
                assert lines[ref["line"] - 1].startswith(key[1:] + ". "), key
        if "json_pointer" in ref:
            target = API
            for segment in ref["json_pointer"].strip("/").split("/"):
                target = target[segment.replace("~1", "/").replace("~0", "~")]
            assert target, key
    assert sum(k.startswith("A") and k[1:].isdigit() for k in CATALOG["rule_registry"]) == 47
    assert sum(k.startswith("B") and k[1:].isdigit() for k in CATALOG["rule_registry"]) == 11
    rows = []
    for case, runner in zip(CATALOG["scenarios"], exported):
        assert case["id"] == runner["id"] and case["expected"] == runner["expected"]
        assert case["facts"]["variables"] == runner["variables"]
        assert case["facts"]["products"] == runner["products"]
        assert case["facts"]["identity"] == runner["identity"]
        assert case["execution"]["script"] == runner["script"]
        assert runner["hosted_registered"] is False
        for ref in case["oracle"]["rule_refs"]:
            assert ref in CATALOG["rule_registry"], (case["id"], ref)
        for item in case["provenance"]["sources"]:
            src = source_map[item["id"]]
            assert item["url"] == src["url"] and item["published_on"] == src["published_on"]
            assert item["publication_label"] == src["publication_label"] and item["accessed_on"] == src["accessed_on"]
        if case["brief"] == "A":
            assert len(case["facts"]["products"]) == 1
        result = evaluate(case, replay(case))
        rows.append({"id": case["id"], **result})
        failures.extend(case["id"] + ": " + x for x in result["failed"])
    mapping = json.loads((HERE / "hosted-style-mapping.json").read_text(encoding="utf-8"))
    public = {c["id"] for c in json.loads((KIT / "public-test-set.json").read_text(encoding="utf-8"))}
    for m in mapping["mappings"]:
        assert m["registered_case"] in public
        assert set(m["field_ids"]) <= CASES.keys()
        assert set(m["styles"]) <= {"pieces", "corrects", "talkative", "asks_back", "in_words"}
    mutations = negative_controls()
    failures.extend(x["name"] for x in mutations if not x["rejected"])
    return {"status": "pass" if not failures else "fail", "scenarios": len(CASES), "sources": len(sources), "sources_by_platform": dict(Counter(s["platform"] for s in sources)), "publication_dates_exact_or_indexed": sum(s["published_on"] is not None for s in sources), "publication_dates_unknown": sum(s["published_on"] is None for s in sources), "rule_anchors_checked": len(CATALOG["rule_registry"]), "schema_valid": True, "official_input_hashes_match": not any(x.startswith("inspected source changed") for x in failures), "canonical_replays": rows, "negative_controls": mutations, "failures": failures, "transcript_judge_executed": False, "agent_under_test_executed": False, "hosted_calls": 0}

def negative_controls():
    tests = []
    def sample(cid):
        c = CASES[cid]
        return c, deepcopy(c["execution"]["reference_tool_calls"])
    def record(name, case, calls):
        result = evaluate(case, replay(case, calls))
        tests.append({"name": name, "rejected": not result["pass"], "failed": result["failed"]})
    c, t = sample("FIELD-01")
    record("duplicate terminal close", c, t + [deepcopy(t[-1])])
    c, t = sample("FIELD-10")
    record("account access without identity", c, t[2:])
    c, t = sample("FIELD-17")
    record("missing terminal close", c, t[:-1])
    c, t = sample("FIELD-17")
    t[3]["arguments"]["amount"] = 159
    record("one below product floor despite ok true", c, t)
    c, t = sample("FIELD-17")
    t[3]["arguments"]["amount"] = 240
    t[3]["arguments"]["date"] = "2026-10-30"
    record("stale pre-correction amount and date", c, t)
    c, t = sample("FIELD-17")
    t[3]["arguments"]["date"] = "2026-10-26"
    record("holiday promise despite ok true", c, t)
    c, t = sample("FIELD-26")
    t[4]["arguments"]["date"] = "2026-11-06"
    record("late product retains date past its own deadline", c, t)
    c, t = sample("FIELD-17")
    t[3]["arguments"]["product_id"] = "invented-product"
    record("unknown product id", c, t)
    c, t = sample("FIELD-28")
    t.insert(6, deepcopy(t[5]))
    record("third attempt after two promise failures", c, t)
    c, t = sample("FIELD-27")
    t.insert(3, {"tool": "add_note", "arguments": {"customer_id": c["facts"]["variables"]["customer_id"], "product_id": "p1", "reason": "dispute"}})
    record("note before transfer", c, t)
    c, t = sample("FIELD-22")
    t.insert(4, deepcopy(t[3]))
    record("second write to a recorded product", c, t)
    c, t = sample("FIELD-25")
    t[-1]["arguments"]["reason"] = "dispute"
    record("closure follows complaint mention order", c, t)
    c, t = sample("FIELD-02")
    t[0]["arguments"]["time"] = "19:01"
    record("callback above upper boundary", c, t)
    c, t = sample("FIELD-08")
    t[-1]["arguments"] = {"customer_id": c["facts"]["variables"]["customer_id"], "outcome": "paid"}
    record("historical closure misclassified as current payment", c, t)
    return tests

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "replay", "check-traces"])
    parser.add_argument("--id", choices=sorted(CASES))
    parser.add_argument("--traces", type=Path, help="JSON list of {id,ledger}; calls contain tool,arguments,result")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    if args.command == "validate":
        result = validation()
    elif args.command == "replay":
        if not args.id:
            parser.error("replay requires --id")
        result = {"id": args.id, "ledger": replay(CASES[args.id]), "kind": "canonical_fixture_replay_not_agent_test"}
    else:
        if args.traces is None:
            parser.error("check-traces requires --traces")
        supplied = json.loads(args.traces.read_text(encoding="utf-8"))
        result = {"results": [{"id": row["id"], **evaluate(CASES[row["id"]], row["ledger"])} for row in supplied], "transcript_judge_executed": False}
    output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        target = args.out.resolve()
        if not target.is_relative_to(HERE):
            parser.error("output must stay within research/field-cases")
        target.write_text(output, encoding="utf-8")
        print(json.dumps({"saved": str(target), "status": result.get("status", "written"), "scenarios": result.get("scenarios"), "negative_controls": len(result.get("negative_controls", []))}))
    else:
        print(output, end="")
    return int(result.get("status") == "fail" or any(not r["pass"] for r in result.get("results", [])))

if __name__ == "__main__":
    sys.exit(main())
