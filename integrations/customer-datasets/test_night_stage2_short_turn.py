"""Source-only local validation. Never imports runners, actors or old catalogs.

The unchanged speech adapter functions/classes are executed from their AST in
an isolated module. Its dependency facts, calendar and rule IDs come only from
the four authorized original sources. This is adapter compatibility validation,
not a conversation, benchmark, reference replay, or independent qualification.
"""
import ast
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import socket
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
KIT = ROOT / "competition-v3/build-the-builder"
PACK = ROOT / "research/customer-benchmark/night-stage2-short-turn-cases.json"
MANIFEST = PACK.with_suffix(".manifest.json")
REPORT = ROOT / "analysis/night-stage2-short-turn-pack.json"
ADAPTER = ROOT / "integrations/customer-datasets/speech_stress_adapter.py"
SOURCE_PATHS = [KIT / "briefs/brief-a.md", KIT / "briefs/brief-b.md",
                KIT / "tools/openapi.json", KIT / "public-test-set.json", ADAPTER]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def lf_bytes(path):
    return path.read_bytes().replace(b"\r\n", b"\n")


def source_pin(path):
    return {"path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(lf_bytes(path)).hexdigest(),
            "hash_method": "utf8_lf_normalized_v1"}


def unique_json(path):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def original_sources():
    a = (KIT / "briefs/brief-a.md").read_text(encoding="utf-8")
    b = (KIT / "briefs/brief-b.md").read_text(encoding="utf-8")
    api = unique_json(KIT / "tools/openapi.json")
    public = {row["id"]: row for row in unique_json(KIT / "public-test-set.json")}
    calendar_line = next(line for line in a.splitlines() if line.startswith("Business days are"))
    holidays = {date.fromisoformat(v) for v in re.findall(r"\d{4}-\d{2}-\d{2}", calendar_line)}
    rules = {"A" + v for v in re.findall(r"^(\d+)\. ", a, re.M)}
    rules |= {"B" + v for v in re.findall(r"^(\d+)\. ", b, re.M)}
    rules |= {"A-calendar", "B-close", "B-inherits-A"}
    if not re.search(r"1 to 7.*12th business day", a) or not re.search(r"8 to 45.*7th business day", a):
        raise ValueError("date policy changed; source review required")

    def business(day):
        return day.weekday() < 5 and day not in holidays

    def after(day, count):
        while count:
            day += timedelta(days=1)
            if business(day):
                count -= 1
        return day

    def deadline(fixture, product):
        today = date.fromisoformat(fixture["facts"]["variables"]["now"][:10])
        return after(today, 12 if product["days_late"] <= 7 else 7)

    return a, b, api, public, rules, business, after, deadline


def isolated_adapter():
    """Run exact original definitions without their prohibited import graph."""
    _, _, api, public, rules, business, after, deadline = original_sources()
    tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    wanted = {"_request_schema", "_record_schema", "scenario_schema", "_validate_rows",
              "Promise", "Note", "Callback", "Transfer", "ExpectedLedger", "StressScenario",
              "StressCatalog", "catalog", "validate_hosted", "kernel_case"}
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
             and node.name in wanted]
    if {node.name for node in nodes} != wanted:
        raise ValueError("original adapter interface changed")
    scope_node = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "SCOPE" for t in node.targets))
    module = ModuleType("night_stage2_isolated_original_adapter")
    sys.modules[module.__name__] = module
    module.__dict__.update(deepcopy=deepcopy, dataclass=dataclass, date=date, datetime=datetime,
                           Decimal=Decimal, json=json, Path=Path, OUT=PACK,
                           SCOPE=ast.literal_eval(scope_node.value),
                           runner=SimpleNamespace(digest=digest),
                           b=SimpleNamespace(PUBLIC=public, jsonschema=jsonschema,
                             local=SimpleNamespace(API=api, CATALOG={"rule_registry": rules},
                               business=business, after=after, deadline=deadline)))
    source_module = ast.Module(body=nodes, type_ignores=[])
    exec(compile(source_module, str(ADAPTER), "exec"), module.__dict__)
    return module


def pointer(value, locator):
    for component in locator.strip("/").split("/"):
        key = component.replace("~1", "/").replace("~0", "~")
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def derive_expected(row, spec):
    """Independent policy calculation from authored final decisions, not expected."""
    _, _, _, public, _, business, _, deadline = original_sources()
    base = public[row["id"]]
    products = {"p" + str(i + 1): p for i, p in enumerate(base["products"])}
    ledger = {"outcome": None, "reason": None, "promises": [], "notes": [],
              "callbacks": [], "transfers": []}
    for decision in spec["final_decisions"]:
        pid, status = decision["product_id"], decision["status"]
        product = products[pid]
        if status == "promise":
            basis = decision["amount"]
            amount = product[basis["fixture_field"]] if "fixture_field" in basis else basis["authored_value"]
            floor = product.get("minimum_payment", product.get("instalment_amount"))
            if not Decimal(str(floor)) <= Decimal(str(amount)) <= Decimal(str(product["past_due"])):
                raise ValueError("derived amount outside source floor")
            fixture = {"facts": {"variables": base["variables"]}}
            today = date.fromisoformat(base["variables"]["now"][:10])
            basis = decision.get("date_basis", "authored_literal")
            if basis == "today":
                day = today
            elif basis == "this_friday":
                day = today + timedelta(days=4 - today.weekday())
            elif basis == "attempt_one_friday":
                # A30 chooses the last business day of this week, except on
                # that day when it chooses next week's last business day.
                friday = today + timedelta(days=4 - today.weekday())
                day = friday
                while not business(day):
                    day -= timedelta(days=1)
                if day <= today:
                    day = friday + timedelta(days=7)
                    while not business(day):
                        day -= timedelta(days=1)
            elif basis == "attempt_two_deadline":
                if product["days_late"] <= 7:
                    raise ValueError("early band has no second persuasion attempt")
                day = deadline(fixture, product)
            else:
                day = date.fromisoformat(decision["date"])
            if day.isoformat() != decision["date"]:
                raise ValueError("authored date differs from source-derived relative/offer date")
            if decision.get("aggregate_deadline_clamp"):
                day = min(day, deadline(fixture, product))
            if not business(day) or not date.fromisoformat(base["variables"]["now"][:10]) <= day <= deadline(fixture, product):
                raise ValueError("derived date outside source window")
            ledger["promises"].append({"product_id": pid, "amount": amount, "date": day.isoformat()})
        elif status in {"paid", "dispute", "refused", "hardship", "service_error"}:
            if row["brief"] == "B" and not spec.get("transfer_reason"):
                ledger["notes"].append({"product_id": pid, "reason": status})
        else:
            raise ValueError("unsupported authored disposition")
    if spec.get("transfer_reason"):
        reason = spec["transfer_reason"]
        ledger.update(outcome="transferred", reason=reason,
                      transfers=[{"queue": {"human": "general", "support": "support", "restructuring": "restructuring"}[reason]}])
    elif ledger["promises"]:
        ledger["outcome"] = "promise"
    elif row["brief"] == "B":
        notes = {n["product_id"]: n["reason"] for n in ledger["notes"]}
        first = next((notes[pid] for pid in products if notes[pid] != "paid"), None)
        ledger.update(outcome="paid" if first is None else "no_promise", reason=first)
    else:
        status = spec["final_decisions"][0]["status"]
        ledger.update(outcome="paid" if status == "paid" else "no_promise",
                      reason=None if status == "paid" else status)
    return ledger


def validate_pack(rows, manifest):
    adapter = isolated_adapter()
    adapter.validate_hosted(rows)
    if len(rows) != 12 or Counter(r["brief"] for r in rows) != {"A": 6, "B": 6}:
        raise ValueError("requires exactly six A and six B")
    if manifest["normalized_pack_sha256"] != digest(rows):
        raise ValueError("normalized pack hash mismatch")
    if manifest["source_hashes"] != [source_pin(p) for p in SOURCE_PATHS]:
        raise ValueError("authorized source changed")
    original_tree = ast.parse(ADAPTER.read_text(encoding="utf-8"))
    pins_node = next(n for n in original_tree.body if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "PINS" for t in n.targets))
    original_pins = ast.literal_eval(pins_node.value)
    for source in SOURCE_PATHS[:4]:
        if source_pin(source)["sha256"] != original_pins[source.relative_to(KIT).as_posix()]:
            raise ValueError("original competition source differs from immutable adapter source pin")
    specs = {spec["variant_id"]: spec for spec in manifest["cases"]}
    if set(specs) != {r["variant_id"] for r in rows}:
        raise ValueError("manifest cases differ")
    for ref in manifest["source_refs"].values():
        path = ROOT / ref["path"]
        if path not in SOURCE_PATHS:
            raise ValueError("unauthorized source reference")
        lines = lf_bytes(path).decode("utf-8").splitlines(keepends=True)
        start, end = ref["span"]["start_line"], ref["span"]["end_line"]
        if not 1 <= start <= end <= len(lines):
            raise ValueError("invalid source span")
        excerpt = "".join(lines[start - 1:end]).encode("utf-8")
        if hashlib.sha256(excerpt).hexdigest() != ref["span_sha256"] or source_pin(path)["sha256"] != ref["source_sha256"]:
            raise ValueError("source span/hash mismatch")
    for row in rows:
        spec = specs[row["variant_id"]]
        if not row["variant_id"].startswith(row["id"] + "__speech_night_stage2_"):
            raise ValueError("exclusive variant namespace missing")
        if len(spec["ideas"]) not in {2, 3}:
            raise ValueError("case must have two or three stress ideas")
        # OpenAPI amounts are numbers; 420 and 420.0 are the same sourced
        # amount. Schema validation has already rejected boolean amounts.
        if derive_expected(row, spec) != row["expected"]:
            raise ValueError("ledger differs from source/script decisions: " + row["variant_id"])
        if re.search(r"https?://|customer_id|product_id|\bp[123]\b", row["script"]):
            raise ValueError("backend/source identifiers leaked to actor")
        if spec["script_sha256"] != hashlib.sha256(row["script"].encode("utf-8")).hexdigest():
            raise ValueError("script source binding mismatch")
        step_ids = {s["step_id"] for s in spec["steps"]}
        if len(step_ids) != len(spec["steps"]):
            raise ValueError("duplicate step IDs")
        for step in spec["steps"]:
            if not 1 <= len(step["say"]) <= 120 or not step["phase"] or not step["cue"]:
                raise ValueError("short conditional step missing or too long")
            if json.dumps(step["say"], ensure_ascii=False) not in row["script"]:
                raise ValueError("exact short response missing from script")
        for decision in spec["final_decisions"]:
            if not set(decision["script_steps"]) <= step_ids:
                raise ValueError("decision references unknown behavior")
            linked = [s for s in spec["steps"] if s["step_id"] in decision["script_steps"]]
            if decision["status"] == "promise":
                text = " ".join(s["say"] + " " + s["cue"] for s in linked)
                amount = decision["amount"]
                if "authored_value" in amount and not re.search(r"(?<!\d)" + re.escape(str(amount["authored_value"])) + r"(?!\d)", text):
                    raise ValueError("authored amount absent from linked behavior")
                if decision.get("date_basis", "authored_literal") == "authored_literal":
                    day = date.fromisoformat(decision["date"])
                    month = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"][day.month]
                    if f"{day.day} {month}" not in text:
                        raise ValueError("authored date absent from linked behavior")
        expected_paths = {"/outcome", "/reason"}
        for key in ("promises", "notes", "callbacks", "transfers"):
            expected_paths |= {"/" + key + "/" + str(i) for i in range(len(row["expected"][key]))}
        if {r["expected_pointer"] for r in spec["expected_record_refs"]} != expected_paths:
            raise ValueError("expected record source coverage incomplete")
        for record in spec["expected_record_refs"]:
            pointer(row["expected"], record["expected_pointer"])
            if not record["source_refs"] or not set(record["source_refs"]) <= set(manifest["source_refs"]):
                raise ValueError("unresolved expected source ref")
            if not record["script_steps"] or not set(record["script_steps"]) <= step_ids:
                raise ValueError("unresolved expected script ref")
        for prefix in ("[ledger]", "[dialogue]", "[actor]"):
            if not any(c.startswith(prefix) for c in row["checks"]):
                raise ValueError("missing criterion class")
    return adapter


def author_pack(designs):
    """Serialize reviewed source-grounded designs; no actor or judge invocation."""
    a, btext, api, public, _, _, _, _ = original_sources()
    scope = isolated_adapter().SCOPE
    shared = [
        "[dialogue] State digital assistant, Freya Bank and recording; confirm name before security. No account purpose/product/amount before both security questions pass.",
        "[dialogue] Ask complete DOB then phone separately; verify_identity must use the actual answers; get_account only after both successful identity receipts.",
        "[dialogue] Propose the full past-due amount first. A first payment ask is 'Can you make this payment today?'; B first asks all products today after stating each in account order.",
        "[dialogue] After successful identity/account tools, state the collections team, late payment, exact product description, past-due amount and days late. B states every late product before its first ask.",
        "[dialogue] After the B aggregate refusal, continue products in get_account order, start at the source first persuasion offer and never ask today again per product. Attempts are per product and respect the early/late bands.",
        "[dialogue] Permit necessary missing amount/date/scope clarifications. Never treat a supplied date or amount as refusal. Do not demand an early consent or an extra arbitrary dialogue turn.",
        "[dialogue] Read every currently agreed product, amount and date; clear current confirmation is required before any create_promise. A correction or consent pause requires fresh complete readback and new clear consent.",
        "[dialogue] Claim recording only after ok:true; retry a failed promise once. Do not invent tool success. Say 'You will receive a text message confirming this promise.' after successful recording.",
        "[dialogue] B uses one grouped readback and confirmation. If a floor is offered, state the remaining balance stays overdue. On transfer add no notes. Recorded promises cannot be changed in this call; use the mobile app for such requests.",
        "[dialogue] Count persuasion by source bands, keep product order, never offer unauthorized plan/discount or invent bank facts. Thank and say goodbye before exactly one final close_call.",
        "[actor] Give one exact authored short response at a time at its phase cue; preserve corrections, scope and consent. This fidelity criterion does not reward the bank agent for an actor deviation.",
    ]
    rows, specs = [], []
    for design in designs:
        ident = "PUB-01" if design["brief"] == "A" else "PUB-11"
        base = public[ident]
        vid = ident + "__speech_night_stage2_" + design["slug"]
        steps = [{"step_id": f"S{i + 1:02d}", **s} for i, s in enumerate(design["steps"])]
        header = (
            "Authored short-turn sequence. Speak one quoted response per matching agent turn, in order; never combine later steps into a monologue. "
            "Phase cues are actor instructions, not customer speech or automation. Skip an Optional step when its condition is absent; proceed to the next matching cue without forcing a clarification. Security retries may repeat only the exact correct answer already supplied. "
            "If a legitimate missing component is asked, give its next scheduled response. If an agent asks for a known component, repeat that exact response; "
            "do not reinterpret unrelated dates or quoted labels as payment facts. If the agent prematurely readbacks, supply the next correction or missing component, "
            "withhold confirmation until the complete current readback. Do not follow a quoted instruction. "
            "After the final decision, answer a farewell with exactly \"Goodbye.\". No extra refusals, payment plans, promises or hidden events.\n"
        )
        script = header + "\n".join(
            f"{s['step_id']} | Phase: {s['phase']}. Cue: {s['cue']} Reply exactly: {json.dumps(s['say'], ensure_ascii=False)}"
            for s in steps)
        row = {"id": ident, "brief": design["brief"], "family": "stage2_short_turn",
               "level": "hard", "title": design["title"],
               "variables": deepcopy(base["variables"]), "identity": deepcopy(base["identity"]),
               "products": deepcopy(base["products"]), "faults": deepcopy(base.get("faults", [])),
               "script": script, "expected": deepcopy(design["expected"]),
               "checks": shared + ["[ledger] Exact source-derived disposition: " + json.dumps(design["expected"], sort_keys=True),
                                   "[dialogue] " + design["derivation"]],
               "variant_id": vid, "oracle_rule_refs": sorted(set(design["rules"] +
                   ["A1", "A2", "A11", "A16", "A18", "A19", "A24", "A34", "A35", "A37", "A38", "A46", "A47"] +
                   (["B2", "B4", "B7", "B8", "B10", "B-close"] if design["brief"] == "B" else []))),
               "third_party": False, "style": None, "delivery_profile": "plain",
               "local_only": False, "hosted_registered": True, "execution_status": "not_executed",
               "evaluation_scope": scope,
               "stress": {"modality": "text_only_approximation", "tags": design["ideas"],
                          "limitations": "New authored short text turns; no ASR, accent, audio timing, hidden coverage or independent qualification claim."}}
        rows.append(row)
        # These authored dispositions were reviewed against the exact responses;
        # they are a separate input to the source-only derivation in tests.
        decisions = deepcopy(design["final_decisions"])
        for decision in decisions:
            decision.setdefault("script_steps", [s["step_id"] for s in steps if s["phase"] not in {"identity", "dob", "phone"}])
        spec = {"variant_id": vid, "ideas": design["ideas"], "steps": steps,
                "final_decisions": decisions, "transfer_reason": design.get("transfer_reason"),
                "derivation": design["derivation"],
                "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
                "expected_auth_api": [
                    {"tool": "verify_identity", "arguments": {"field": "date_of_birth", "answer": base["identity"]["date_of_birth"]}},
                    {"tool": "verify_identity", "arguments": {"field": "phone_last4", "answer": base["identity"]["phone_last4"]}},
                    {"tool": "get_account", "arguments": {}}],
                "first_payment_ask": "Can you make this payment today?" if design["brief"] == "A" else "Can you pay all of these today?",
                "first_payment_ask_basis": "exact source quote A28" if design["brief"] == "A" else "required meaning B4; source does not prescribe an exact spoken sentence",
                "first_payment_ask_source_refs": ["A28"] if design["brief"] == "A" else ["B2", "B4"],
                "product_order": ["p" + str(i + 1) for i in range(len(base["products"]))],
                "efficiency": "Necessary missing-component clarification allowed; no repeat today ask per B product; respect source persuasion budgets; no fabricated recording success.",
                "expected_record_refs": []}
        for key in ("outcome", "reason", "promises", "notes", "callbacks", "transfers"):
            paths = ["/" + key] if key in {"outcome", "reason"} else ["/" + key + "/" + str(i) for i in range(len(row["expected"][key]))]
            tool = {"outcome": "close_call", "reason": "close_call", "promises": "create_promise",
                    "notes": "add_note", "callbacks": "schedule_callback", "transfers": "transfer_to_agent"}[key]
            for path in paths:
                spec["expected_record_refs"].append({"expected_pointer": path,
                   "source_refs": row["oracle_rule_refs"] + ["O-" + tool, "fixture-" + ident],
                   "script_steps": [s["step_id"] for s in steps if s["phase"] not in {"identity", "dob", "phone"}]})
        specs.append(spec)

    refs = {}
    def span_ref(key, path, start, end, locator):
        lines = lf_bytes(path).decode("utf-8").splitlines(keepends=True)
        refs[key] = {"path": path.relative_to(ROOT).as_posix(), "locator": locator,
                     "span": {"start_line": start, "end_line": end},
                     "source_sha256": source_pin(path)["sha256"],
                     "span_sha256": hashlib.sha256("".join(lines[start - 1:end]).encode("utf-8")).hexdigest()}
    for prefix, text, path in (("A", a, KIT / "briefs/brief-a.md"), ("B", btext, KIT / "briefs/brief-b.md")):
        lines = text.splitlines()
        starts = [(i + 1, m.group(1)) for i, line in enumerate(lines) if (m := re.match(r"^(\d+)\. ", line))]
        for index, (start, number) in enumerate(starts):
            end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
            span_ref(prefix + number, path, start, end, "rule " + number)
    calendar = next(i + 1 for i, line in enumerate(a.splitlines()) if line.startswith("Business days are"))
    span_ref("A-calendar", KIT / "briefs/brief-a.md", calendar, calendar, "business calendar")
    closing = next(i + 1 for i, line in enumerate(btext.splitlines()) if line == "## Closing")
    span_ref("B-close", KIT / "briefs/brief-b.md", closing, len(btext.splitlines()), "closing precedence")
    span_ref("B-inherits-A", KIT / "briefs/brief-b.md", 5, 5, "inheritance")
    api_lines = (KIT / "tools/openapi.json").read_text(encoding="utf-8").splitlines()
    endpoints = [(i + 1, m.group(1)) for i, line in enumerate(api_lines) if (m := re.match(r'^\s*"/([^" ]+)": \{', line))]
    for index, (start, name) in enumerate(endpoints):
        end = endpoints[index + 1][0] - 1 if index + 1 < len(endpoints) else len(api_lines)
        span_ref("O-" + name, KIT / "tools/openapi.json", start, end, "/paths/~1" + name)
    fixture_lines = (KIT / "public-test-set.json").read_text(encoding="utf-8").splitlines()
    fixture_starts = [(i + 1, m.group(1)) for i, line in enumerate(fixture_lines) if (m := re.search(r'"id": "(PUB-\d+)"', line))]
    for ident in ("PUB-01", "PUB-11"):
        index = next(i for i, (_, name) in enumerate(fixture_starts) if name == ident)
        start = fixture_starts[index][0] - 1
        end = fixture_starts[index + 1][0] - 2 if index + 1 < len(fixture_starts) else len(fixture_lines)
        span_ref("fixture-" + ident, KIT / "public-test-set.json", start, end, "/" + str(list(public).index(ident)))
    manifest = {"schema_version": "1.0.0", "pack": PACK.name,
        "normalized_pack_sha256": digest(rows), "normalized_pack_hash_method": "sha256_canonical_json_utf8_sorted_keys_compact_ensure_ascii_false",
        "source_hashes": [source_pin(p) for p in SOURCE_PATHS], "source_refs": refs,
        "case_count": 12, "brief_counts": {"A": 6, "B": 6}, "cases": specs,
        "stress_properties": sorted({tag for d in designs for tag in d["ideas"]}),
        "exclusions": ["ASR/accent/audio timing", "hidden fixture coverage", "model/judge verdict tuning",
                       "extra actor automation/model parameters", "new bank registration or bank fact changes"],
        "license": {"authored_content": "CC0-1.0", "source_kit": "Original supplied competition kit; redistribution license not established in authorized read scope. Source rights are not relicensed.",
                    "third_party_customer_dataset": "None; all reserved bank fixtures are explicitly synthetic."},
        "provenance": {"synthetic": True, "source_policy": "Original v3 briefs/API/registered fixtures plus explicitly authored customer behavior only",
            "authoring": "Two independent source-only drafting subagents; parent source review/integration and local validator owner",
            "actual_customer_privacy_upload": False, "old_pack_wording_reused": False},
        "freshness": {"authored_utc_date": "2026-10-11", "new_exclusive_namespace": True,
                      "sampling": "Adaptively sampled from explicit parent instructions; no blind or independent qualification claim",
                      "benchmark_results_seen_or_used": False, "independent_qualification": False},
        "repetition_plan": {"repetitions_per_variant": 3, "total_conversations": 36, "status": "plan_only_not_executed",
            "independence": "Parent starts each repetition with fresh isolated call/session and reset fixture ledger; same pinned pack, no adaptive script/expectation edits between repetitions",
            "reporting": "Retain each repetition separately including actor deviations and failures; report all three, not best-of-three",
            "execution_owner": "parent only; no queue/slot/state mutation by authoring workers"},
        "read_scope": {"ground_truth": [str(p.relative_to(ROOT).as_posix()) for p in SOURCE_PATHS[:4]],
            "format_and_validator_source": ["integrations/customer-datasets/adapter.py", "integrations/customer-datasets/benchmark_adapter.py",
                "integrations/customer-datasets/speech_stress_adapter.py", "integrations/customer-datasets/security_stress_adapter.py",
                "integrations/customer-datasets/redteam_adapter.py", "integrations/customer-datasets/test_night_stress_pack.py"],
            "existing_pack": "night-stress-cases.json parsed only for top-level shape/count and one row key list; no scripts/expectations/wording displayed or copied",
            "read_scope_exception": "Source-adapter inspection output included embedded legacy security/redteam examples and fixed derivation text beyond pack-format definitions. These were not copied or used to derive new expectations. Strict zero-exposure to old variant wording is therefore not claimed.",
            "filename_inventory_only": "rg filenames to locate sources and adapters; no candidate/controller/model/reviewer/transcript/DEV contents read",
            "adapter_execution": "Exact unchanged AST definitions only; normal import graph, source fixtures from other packs, runner/scorer/actor and environment access excluded"},
        "limitations": ["Local structural/policy validation only; no bank agent conversation or platform test ran",
            "Authored conditional text steps depend on actor fidelity; they are instructions, not extra actor automation",
            "Adapter compatibility tested by isolated exact source definitions; full import graph deliberately excluded",
            "Expected dialogue claims have not been empirically assessed; no generated judge verdict",
            "Adapter inspection exposed embedded legacy examples/derivation text; excluded from design evidence, but this is a read-scope exception",
            "Original kit redistribution license not audited outside authorized read scope"]}
    PACK.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["raw_pack_sha256"] = hashlib.sha256(PACK.read_bytes()).hexdigest()
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rows, manifest


class Stage2PackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = unique_json(PACK)
        cls.manifest = unique_json(MANIFEST)

    def test_source_grounded_pack_and_unchanged_adapter_load(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
             patch.object(urllib.request, "urlopen", side_effect=AssertionError("HTTP forbidden")):
            adapter = validate_pack(self.rows, self.manifest)
            self.assertEqual(adapter.catalog(PACK).to_rows(), self.rows)
            jsonschema.Draft202012Validator.check_schema(adapter.scenario_schema())

    def test_every_immutable_fixture_field_matches_original(self):
        public = original_sources()[3]
        for row in self.rows:
            for key in ("brief", "variables", "identity", "products", "faults"):
                self.assertEqual(digest(row[key]), digest(public[row["id"]].get(key, [])))

    def test_openapi_expected_record_contracts(self):
        api = original_sources()[2]
        for row in self.rows:
            for key, tool in (("promises", "create_promise"), ("notes", "add_note"),
                              ("callbacks", "schedule_callback"), ("transfers", "transfer_to_agent")):
                schema = api["paths"]["/" + tool]["post"]["requestBody"]["content"]["application/json"]["schema"]
                for record in row["expected"][key]:
                    jsonschema.Draft7Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
                        {"customer_id": "reserved-synthetic-local-validation", **record})
            close = {"customer_id": "reserved-synthetic-local-validation", "outcome": row["expected"]["outcome"]}
            if row["expected"]["reason"] is not None:
                close["reason"] = row["expected"]["reason"]
            schema = api["paths"]["/close_call"]["post"]["requestBody"]["content"]["application/json"]["schema"]
            jsonschema.Draft7Validator(schema).validate(close)

    def test_authentication_first_asks_and_order_source_derived(self):
        a, _, api, public, _, _, _, _ = original_sources()
        exact_first_ask = re.search(r'28\. First ask: "([^"]+)"', a).group(1)
        by_id = {r["variant_id"]: r for r in self.rows}
        for spec in self.manifest["cases"]:
            row = by_id[spec["variant_id"]]
            base = public[row["id"]]
            expected_auth = [
                {"tool": "verify_identity", "arguments": {"field": "date_of_birth", "answer": base["identity"]["date_of_birth"]}},
                {"tool": "verify_identity", "arguments": {"field": "phone_last4", "answer": base["identity"]["phone_last4"]}},
                {"tool": "get_account", "arguments": {}}]
            self.assertEqual(spec["expected_auth_api"], expected_auth)
            for call in expected_auth:
                schema = api["paths"]["/" + call["tool"]]["post"]["requestBody"]["content"]["application/json"]["schema"]
                jsonschema.Draft7Validator(schema).validate({"customer_id": "reserved-synthetic-local-validation", **call["arguments"]})
            self.assertEqual(spec["product_order"], ["p" + str(i + 1) for i in range(len(base["products"]))])
            if row["brief"] == "A":
                self.assertEqual(spec["first_payment_ask"], exact_first_ask)
                self.assertEqual(spec["first_payment_ask_source_refs"], ["A28"])
            else:
                self.assertEqual(spec["first_payment_ask_source_refs"], ["B2", "B4"])
                self.assertIn("required meaning", spec["first_payment_ask_basis"])

    def test_relative_offer_date_mutation_rejected(self):
        row = next(r for r in self.rows if r["variant_id"].endswith("actual_second_offer"))
        spec = deepcopy(next(c for c in self.manifest["cases"] if c["variant_id"] == row["variant_id"]))
        spec["final_decisions"][0]["date"] = "2026-10-22"
        with self.assertRaisesRegex(ValueError, "source-derived"):
            derive_expected(row, spec)

    def test_short_step_and_script_mutation_rejected(self):
        manifest = deepcopy(self.manifest)
        manifest["cases"][0]["steps"][0]["say"] = "x" * 121
        with self.assertRaises(ValueError):
            validate_pack(self.rows, manifest)

    def test_legal_but_wrong_ledger_rejected_by_independent_derivation(self):
        rows = deepcopy(self.rows)
        row = next(r for r in rows if r["expected"]["promises"])
        product = row["products"][0]
        row["expected"]["promises"][0]["amount"] = product["past_due"] if row["expected"]["promises"][0]["amount"] != product["past_due"] else product.get("minimum_payment", product.get("instalment_amount"))
        manifest = deepcopy(self.manifest)
        manifest["normalized_pack_sha256"] = digest(rows)
        with self.assertRaisesRegex(ValueError, "source/script"):
            validate_pack(rows, manifest)

    def test_source_span_tampering_rejected(self):
        manifest = deepcopy(self.manifest)
        next(iter(manifest["source_refs"].values()))["span_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "span/hash"):
            validate_pack(self.rows, manifest)

    def test_original_adapter_rejects_fixture_schema_and_scope_mutations(self):
        adapter = isolated_adapter()
        controls = []
        row = deepcopy(self.rows[0]); row["products"][0]["past_due"] += 1; controls.append(row)
        row = deepcopy(self.rows[0]); row["unexpected_automation"] = True; controls.append(row)
        row = deepcopy(self.rows[0]); row["delivery_profile"] = "custom"; controls.append(row)
        row = deepcopy(self.rows[0]); row["expected"]["notes"] = [{"product_id": "p1", "reason": "paid"}]; controls.append(row)
        for row in controls:
            with self.assertRaises(ValueError):
                adapter.validate_hosted([row])

    def test_calendar_and_outcome_boundaries(self):
        _, _, _, public, _, business, _, deadline = original_sources()
        self.assertFalse(business(date(2026, 10, 26)))
        self.assertEqual(deadline({"facts": {"variables": public["PUB-01"]["variables"]}}, public["PUB-01"]["products"][0]), date(2026, 11, 2))
        self.assertEqual(deadline({"facts": {"variables": public["PUB-11"]["variables"]}}, public["PUB-11"]["products"][0]), date(2026, 10, 23))
        transfer_rows = [r for r in self.rows if r["expected"]["outcome"] == "transferred"]
        self.assertTrue(transfer_rows)
        self.assertTrue(all(not r["expected"]["notes"] for r in transfer_rows))


def main():
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Stage2PackTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    rows, manifest = unique_json(PACK), unique_json(MANIFEST)
    utterances = [s["say"] for c in manifest["cases"] for s in c["steps"]]
    report = {"status": "pass" if result.wasSuccessful() else "fail", "cases": len(rows),
              "brief_counts": dict(Counter(r["brief"] for r in rows)),
              "outcome_counts": dict(Counter(r["expected"]["outcome"] for r in rows)),
              "expected_record_counts": {key: sum(len(r["expected"][key]) for r in rows) for key in ("promises", "notes", "callbacks", "transfers")},
              "registered_fixture_ids": sorted({r["id"] for r in rows}),
              "normalized_pack_sha256": digest(rows), "utterance_count": len(utterances),
              "max_utterance_unicode_characters": max(map(len, utterances)),
              "utterances_at_or_below_80": sum(len(u) <= 80 for u in utterances),
              "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "qa_scope": ["original adapter AST definitions unchanged", "typed catalog load/schema validation",
                 "source-derived ledger and closure", "OpenAPI records", "source spans/hashes",
                 "immutable official fixture facts", "exact short conditional steps", "negative mutation controls"],
              "source_hashes": manifest["source_hashes"], "read_scope": manifest["read_scope"],
              "repetition_plan": manifest["repetition_plan"], "freshness": manifest["freshness"],
              "limitations": manifest["limitations"], "agent_executed": False,
              "reference_replay_executed": False, "transcript_judge_executed": False,
              "hosted_simulations": 0, "parent_queue_slots_state_touched": False,
              "test_source_sha256": hashlib.sha256(lf_bytes(Path(__file__))).hexdigest()}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT.with_suffix(".txt").write_text(
        "Night stage 2 short-turn pack: " + report["status"] + "\n" +
        "12 variants: 6 A + 6 B, unmodified registered PUB-01/PUB-11 bank facts.\n" +
        f"Local validator tests: {result.testsRun}; failures={len(result.failures)}; errors={len(result.errors)}.\n" +
        f"Customer utterances: {len(utterances)}; maximum Unicode characters={max(map(len, utterances))}.\n" +
        "Canonical JSON SHA-256: " + digest(rows) + "\n" +
        "QA: isolated unchanged adapter definitions, source/script oracle, schema, API, short steps, fixture and span pins.\n" +
        "No benchmark, actor, judge, replay, platform, Git, cloud, training, credentials or parent queue/slots/state used.\n" +
        "Plan only: three fresh independent conversations per variant (36 total), parent-owned execution.\n" +
        "Fresh authored scenarios sampled adaptively from parent instructions; not independent qualification.\n" +
        "Text-only stress; no ASR, accent, acoustic or hidden-coverage claim.\n" +
        "Full adapter import graph deliberately excluded; exact adapter functions tested with source-grounded dependencies.\n" +
        "Read scope and complete provenance/source spans are in the manifest and JSON report.\n" +
        "Read-scope exception: adapter inspection exposed embedded legacy examples/derivations; none was copied or used. Strict zero-exposure is not claimed.\n" +
        "Original kit redistribution license not established in authorized read scope; authored text CC0-1.0.\n",
        encoding="utf-8")
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
