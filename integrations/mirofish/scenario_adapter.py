"""Offline, standard-library scenario contracts; this module executes no agents.

From the repository root (Python 3.10+; no credentials or installation needed)::

    python -B integrations/mirofish/scenario_adapter.py build
    python -B integrations/mirofish/scenario_adapter.py build --seed-text seed.md
    python -B integrations/mirofish/scenario_adapter.py verify
    python -B integrations/mirofish/scenario_adapter.py seed --case SYN-048 --output gap.txt
    python -B integrations/mirofish/scenario_adapter.py seed --case PUB-01 --style pieces --output pieces.md

Output names resolve inside this adapter's scenarios/ directory. Seeds are plain
UTF-8 .txt or .md files for local MiroFish intake, not its simulation API payload.
The catalog always contains all 50 synthetic and 13 official cases. An optional
seed selection does not shrink the catalog. Only named delivery styles are
accepted; fixture/intent/oracle overrides are deliberately unsupported.

Logical immutability is enforced by digests plus comparison with source files,
not by signatures or Python dict mutability. Never treat an expected_output as
an observed execution result. In particular run_cases.py provisions hosted
sessions with only {"case": case_id}; a persona edit cannot register SYN fixtures.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, time
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
STATUS = "scenario_only_not_executed"
SCHEMA_VERSION = "1.0.0"
SYNTHETIC_FILE = "analysis/synthetic-cases.json"
OFFICIAL_FILE = "competition-v3/build-the-builder/public-test-set.json"
KIT = "competition-v3/build-the-builder/"
SOURCE_FILES = (
    SYNTHETIC_FILE, OFFICIAL_FILE, KIT + "briefs/brief-a.md",
    KIT + "briefs/brief-b.md", KIT + "tools/openapi.json",
    KIT + "tools/run_cases.py", KIT + "tools/score.py", KIT + "README.md",
)
KNOWN_IDS = {
    "synthetic": {f"SYN-{n:03d}" for n in range(1, 51)},
    "official": {f"PUB-{n:02d}" for n in range(1, 14)},
}
DELIVERY_STYLES = {
    "plain": "Use the source delivery instructions; otherwise use short natural answers.",
    "pieces": "Deliver a complete scripted number or date in two turns, retaining every digit and the same final value. Preserve any source-scripted split or correction.",
    "corrects": "An optional same-sentence self-correction may concern a payment amount or day only; its final value must be the scripted value. Preserve all scripted corrections and wrong security answers; add no security-answer mistakes.",
    "talkative": "Add brief neutral small talk without introducing names, numbers, dates, account facts, offers or new decisions. Keep each scripted answer and decision unchanged.",
    "asks_back": "Ask brief clarification questions before answering when compatible with the script. Never change scripted refusals, confirmations, security answers, counters or decision order.",
    "in_words": "Say scripted amounts and dates in words and codes digit by digit. Retain every digit, leading zero, value, split and scripted correction.",
}
STYLE_GUARDS = [
    "Delivery is a rendering hint, never a fixture override or agent instruction.",
    "Protected facts, declared tool outcomes, customer decisions, timing/interleaving and oracle scope take precedence over style.",
    "Preserve security failures/refusals, payment offers, corrected final values, confirmation conditions, fault responses and side effects exactly as scripted.",
    "Never invent financial facts, tool success, retry policy or an unspecified final outcome.",
]
CONTRACT = {
    "scenario": "Protected fixture_facts, fixture_plan, tool_outcomes and behavior_intentions. This is a plan, not an executed conversation or mock service.",
    "expected_output": "An oracle contract, never an observed output. Official ledger values are copied exactly. Synthetic scoped checks retain their source basis; no ledger is materialized from prose.",
    "speech_delivery": "Only the named local style and its fixed instructions may vary. Source delivery, protected content and all digests remain unchanged.",
    "fixture_visibility": "Identity, products and fault plans are private customer/harness data. Agent knowledge follows the brief and successful tool responses, not this seed text.",
    "session_isolation": "Each case needs fresh ledger, counters and local placeholder binding; no state is shared between cases. No session has been allocated or executed here.",
    "official_runner_limit": {
        "source": KIT + "tools/run_cases.py",
        "session_request_body": {"case": "<registered case_id>"},
        "explanation": "The runner sends ONLY {'case': case_id} to /v1/practice/sessions. It uploads neither fixture overrides nor faults. Persona/speech edits cannot register synthetic backend fixtures. Official JSON faults are metadata for the registered fixture, not runtime overrides uploaded by the runner.",
    },
    "official_scorer_limit": {
        "source": KIT + "tools/score.py",
        "explanation": "Ledger comparisons sort collections and round promise amounts to two decimals. The scorer checks a last close_call and selected identity constraints, but does not comprehensively establish exactly-one-close, confirmation order, honesty or transcript policy. The official runner also uses a transcript judge. No scorer or judge runs here.",
    },
    "synthetic_limit": "SYN IDs are local planning identifiers, not registered hosted fixtures. Fault/interruption/raw-memo plans require a separate local harness or adopted intake contract; proposed and partial oracles are not official pass/fail claims.",
    "style_guards": STYLE_GUARDS,
    "integrity": "SHA-256 of canonical JSON protects facts, tool declarations, intentions and oracles separately from style. Source-aware verification also checks all file hashes and reconstruction. Digests detect edits; they are not signatures.",
    "execution": {"status": STATUS, "network_requests": 0, "agent_runs": 0, "bank_calls": 0},
}
SYNTHETIC_KEYS = {
    "id", "brief", "persona", "category", "trigger", "expected_backend_invariants",
    "expected_conversation_checks", "source_rules", "expectation_classification",
    "oracle_scope", "open_questions",
}
OFFICIAL_KEYS = {
    "id", "brief", "family", "level", "title", "variables", "identity",
    "products", "script", "expected", "checks", "faults", "third_party",
}
SETUP_KEYS = {
    "now", "phase", "identity", "product_A", "products_B_in_returned_order",
    "callback_offer", "local_fault", "effective_brief", "raw_memo",
}
PRODUCT_KEYS = {
    "product_id", "type", "card_last4", "past_due", "days_late",
    "minimum_payment", "instalment_amount",
}


class AdapterError(ValueError):
    """Invalid source, unsupported override, or altered contract."""


def canonical_bytes(value: Any) -> bytes:
    """No clock, random identifiers, host paths or float NaNs enter serialization."""
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"not canonical JSON: {exc}") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _object(value: Any, allowed: set[str], required: set[str], label: str) -> None:
    if not isinstance(value, dict):
        raise AdapterError(f"{label}: expected an object")
    extra, missing = set(value) - allowed, required - set(value)
    if extra or missing:
        raise AdapterError(f"{label}: unknown fields/overrides {sorted(extra)}; missing fields {sorted(missing)}")


def _strings(value: Any, label: str) -> None:
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise AdapterError(f"{label}: expected a list of strings")


def _text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise AdapterError(f"{label}: expected nonempty text")


def _load_json(raw: bytes, label: str) -> Any:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise AdapterError(f"{label}: duplicate JSON key {key!r}")
            result[key] = value
        return result

    def constant(value: str) -> None:
        raise AdapterError(f"{label}: nonfinite JSON value {value}")

    try:
        result = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                            parse_constant=constant)
        canonical_bytes(result)  # Also reject overflowing numeric literals (e.g. 1e999).
        return result
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise AdapterError(f"{label}: invalid UTF-8 JSON: {exc}") from exc


def _validate_product(product: Any, label: str, *, local: bool) -> None:
    required = {"type", "past_due", "days_late"} | ({"product_id"} if local else set())
    _object(product, PRODUCT_KEYS, required, label)
    kind = product["type"]
    if kind not in ("credit_card", "personal_loan", "car_loan"):
        raise AdapterError(f"{label}: unknown product fixture type {kind!r}")
    specific = {"card_last4", "minimum_payment"} if kind == "credit_card" else {"instalment_amount"}
    incompatible = {"instalment_amount"} if kind == "credit_card" else {"card_last4", "minimum_payment"}
    if not specific <= set(product) or incompatible & set(product):
        raise AdapterError(f"{label}: missing or incompatible product-specific fixture fields")
    for key in ("past_due", "minimum_payment", "instalment_amount"):
        if key in product:
            number = product[key]
            if type(number) not in (int, float) or not math.isfinite(number):
                raise AdapterError(f"{label}.{key}: expected a finite number")
    if type(product["days_late"]) is not int:
        raise AdapterError(f"{label}.days_late: expected an integer")
    for key in ("product_id", "card_last4"):
        if key in product:
            _text(product[key], f"{label}.{key}")


def _validate_identity(identity: Any, label: str) -> None:
    keys = {"date_of_birth", "phone_last4"}
    _object(identity, keys, keys, label)
    try:
        if date.fromisoformat(identity["date_of_birth"]).isoformat() != identity["date_of_birth"]:
            raise ValueError("not ISO date")
    except (TypeError, ValueError) as exc:
        raise AdapterError(f"{label}: invalid ISO date_of_birth") from exc
    digits = identity["phone_last4"]
    if not isinstance(digits, str) or len(digits) != 4 or not digits.isascii() or not digits.isdigit():
        raise AdapterError(f"{label}: phone_last4 must preserve four digits as text")


def _validate_setup(setup: Any, brief: str) -> None:
    _object(setup, SETUP_KEYS, set(), "trigger.setup")
    if "phase" in setup and setup["phase"] not in {"opening", "verification", "opening_after_name_confirmation"}:
        raise AdapterError(f"trigger.setup: unknown phase {setup['phase']!r}")
    if "effective_brief" in setup and setup["effective_brief"] != brief:
        raise AdapterError("trigger.setup: an effective_brief override cannot change the case brief")
    if "product_A" in setup and brief != "A":
        raise AdapterError("trigger.setup.product_A: cannot override Brief B products")
    if "products_B_in_returned_order" in setup and brief != "B":
        raise AdapterError("trigger.setup.products_B_in_returned_order: cannot override Brief A products")
    if "identity" in setup:
        _object(setup["identity"], {"date_of_birth", "phone_last4"}, set(), "trigger.setup.identity")
    if "product_A" in setup:
        _object(setup["product_A"], PRODUCT_KEYS, set(), "trigger.setup.product_A")
    if "raw_memo" in setup:
        _object(setup["raw_memo"], {"origin", "text", "foreign_customer_id"},
                {"origin", "text"}, "trigger.setup.raw_memo")
        for key, value in setup["raw_memo"].items():
            _text(value, f"trigger.setup.raw_memo.{key}")
    if "local_fault" in setup:
        _text(setup["local_fault"], "trigger.setup.local_fault")
    if "callback_offer" in setup:
        _object(setup["callback_offer"], {"date", "time"}, {"date", "time"}, "trigger.setup.callback_offer")
        try:
            date.fromisoformat(setup["callback_offer"]["date"])
            time.fromisoformat(setup["callback_offer"]["time"])
        except (TypeError, ValueError) as exc:
            raise AdapterError("trigger.setup.callback_offer: unreadable date/time") from exc


def resolve_fixture(baseline: dict[str, Any], setup: dict[str, Any], brief: str,
                    case_id: str) -> dict[str, Any]:
    """Resolve source overrides only; no policy, calendar or ledger is inferred.

    Nested identity/product scalar fields merge. A product type change discards
    the old type's exclusive fields before applying new fields. The B product
    list is replaced wholesale, never merged by index. Raw memo text stays data.
    """
    if brief not in ("A", "B") or case_id not in KNOWN_IDS["synthetic"]:
        raise AdapterError(f"unknown synthetic fixture/brief: {case_id!r}/{brief!r}")
    _object(baseline, {"call_variables", "identity", "product_A", "products_B_in_returned_order", "instructions"},
            {"call_variables", "identity", "product_A", "products_B_in_returned_order", "instructions"}, "local_fixture_baseline")
    _validate_setup(setup, brief)
    variables = deepcopy(baseline["call_variables"])
    _object(variables, {"customer_id", "first_name", "last_name", "title", "now"},
            {"customer_id", "first_name", "last_name", "title", "now"}, "baseline.call_variables")
    for key, value in variables.items():
        _text(value, f"baseline.call_variables.{key}")
    if "now" in setup:
        variables["now"] = setup["now"]
    try:
        datetime.fromisoformat(variables["now"])
    except (TypeError, ValueError) as exc:
        raise AdapterError("fixture now: expected an ISO datetime") from exc
    placeholder = variables["customer_id"]
    variables["customer_id"] = "local:" + case_id
    identity = deepcopy(baseline["identity"])
    identity.update(deepcopy(setup.get("identity", {})))
    _validate_identity(identity, "resolved identity")
    if brief == "A":
        product = deepcopy(baseline["product_A"])
        patch = setup.get("product_A", {})
        if "type" in patch and patch["type"] != product["type"]:
            obsolete = ("instalment_amount",) if patch["type"] == "credit_card" else ("card_last4", "minimum_payment")
            for key in obsolete:
                product.pop(key, None)
        product.update(deepcopy(patch))
        products = [product]
    else:
        products = deepcopy(setup.get("products_B_in_returned_order", baseline["products_B_in_returned_order"]))
    if not isinstance(products, list) or not products:
        raise AdapterError("resolved products: expected a nonempty list")
    for index, product in enumerate(products):
        _validate_product(product, f"resolved products[{index}]", local=True)
    ids = [p["product_id"] for p in products]
    if len(ids) != len(set(ids)):
        raise AdapterError("resolved products: duplicate product_id")
    return {
        "variables": variables, "identity": identity, "products": products,
        "session_binding": {"kind": "local_placeholder_not_registered",
                            "source_placeholder": placeholder,
                            "customer_id": variables["customer_id"]},
    }


def _checks(checks: Any, labels: dict[str, Any], label: str) -> None:
    if not isinstance(checks, list):
        raise AdapterError(f"{label}: expected a list")
    for check in checks:
        _object(check, {"basis", "check", "source_rules"}, {"basis", "check"}, label)
        if check["basis"] not in labels:
            raise AdapterError(f"{label}: unknown expectation basis {check['basis']!r}")
        _text(check["check"], label)
        if "source_rules" in check:
            _strings(check["source_rules"], label + ".source_rules")


def _check_ids(cases: Any, kind: str) -> None:
    if not isinstance(cases, list) or any(not isinstance(c, dict) or not isinstance(c.get("id"), str) for c in cases):
        raise AdapterError(f"{kind}: expected a list of identified fixtures")
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise AdapterError(f"{kind}: duplicate case IDs")
    expected, actual = KNOWN_IDS[kind], set(ids)
    if actual != expected:
        raise AdapterError(f"{kind}: unknown IDs {sorted(actual - expected)}; missing IDs {sorted(expected - actual)}")


def _validate_sources(synthetic: Any, official: Any) -> None:
    if not isinstance(synthetic, dict) or synthetic.get("version") != "1.0.0":
        raise AdapterError("unknown synthetic fixture version/shape (expected 1.0.0)")
    for key in ("cases", "local_fixture_baseline", "expectation_labels", "coverage_by_source_clauses",
                "common_expected_backend_invariants", "common_expected_conversation_checks", "common_invariant_applicability"):
        if key not in synthetic:
            raise AdapterError(f"synthetic fixture missing {key}")
    _check_ids(synthetic["cases"], "synthetic")
    _check_ids(official, "official")
    labels = synthetic["expectation_labels"]
    if not isinstance(labels, dict):
        raise AdapterError("expectation_labels: expected an object")
    rules = {r["source_rule_id"] for r in synthetic["coverage_by_source_clauses"]}
    for key in ("common_expected_backend_invariants", "common_expected_conversation_checks"):
        _checks(synthetic[key], labels, key)
    for case in synthetic["cases"]:
        _object(case, SYNTHETIC_KEYS, SYNTHETIC_KEYS - {"open_questions"}, case["id"])
        if case["brief"] not in ("A", "B"):
            raise AdapterError(f"{case['id']}: unknown brief")
        _object(case["persona"], {"label", "role", "delivery"}, {"label", "role", "delivery"}, case["id"] + ".persona")
        for key, value in case["persona"].items():
            _text(value, case["id"] + ".persona." + key)
        if case["persona"]["role"] not in ("customer", "third_party"):
            raise AdapterError(f"{case['id']}: unknown persona role")
        trigger = case["trigger"]
        _object(trigger, {"baseline", "setup", "customer_behavior", "fault_injection", "harness_requirements"},
                {"baseline", "setup", "customer_behavior"}, case["id"] + ".trigger")
        if trigger["baseline"] != "local_fixture_baseline":
            raise AdapterError(f"{case['id']}: unknown baseline fixture {trigger['baseline']!r}")
        resolved = resolve_fixture(synthetic["local_fixture_baseline"], trigger["setup"], case["brief"], case["id"])
        _strings(trigger["customer_behavior"], case["id"] + ".customer_behavior")
        if "harness_requirements" in trigger:
            _strings(trigger["harness_requirements"], case["id"] + ".harness_requirements")
        if "fault_injection" in trigger:
            fault = trigger["fault_injection"]
            _object(fault, {"status", "tool", "responses", "side_effects", "target_product_id", "other_products", "queue", "result"},
                    {"status", "tool", "side_effects"}, case["id"] + ".fault_injection")
            if fault["tool"] not in ("create_promise", "transfer_to_agent"):
                raise AdapterError(f"{case['id']}: unknown fault tool")
            if "target_product_id" in fault and fault["target_product_id"] not in [p["product_id"] for p in resolved["products"]]:
                raise AdapterError(f"{case['id']}: unknown fault target_product_id")
            if "queue" in fault and fault["queue"] not in ("general", "support", "restructuring"):
                raise AdapterError(f"{case['id']}: unknown fault queue")
            if ("responses" in fault) == ("result" in fault):
                raise AdapterError(f"{case['id']}: fault must supply responses or result")
            responses = fault.get("responses", [fault.get("result")])
            if not isinstance(responses, list) or not responses:
                raise AdapterError(f"{case['id']}: invalid fault responses")
            for response in responses:
                _object(response, {"ok"}, {"ok"}, case["id"] + ".fault response")
                if type(response["ok"]) is not bool:
                    raise AdapterError(f"{case['id']}: fault response ok must be boolean")
        for key in ("expected_backend_invariants", "expected_conversation_checks"):
            _checks(case[key], labels, case["id"] + "." + key)
        if case["expectation_classification"] not in labels:
            raise AdapterError(f"{case['id']}: unknown expectation classification")
        _strings(case["source_rules"], case["id"] + ".source_rules")
        if set(case["source_rules"]) - rules:
            raise AdapterError(f"{case['id']}: unknown source rule IDs")
        _text(case["oracle_scope"], case["id"] + ".oracle_scope")
        if "open_questions" in case:
            _strings(case["open_questions"], case["id"] + ".open_questions")
    for case in official:
        _object(case, OFFICIAL_KEYS, OFFICIAL_KEYS - {"faults", "third_party"}, case["id"])
        if case["brief"] not in ("A", "B"):
            raise AdapterError(f"{case['id']}: unknown brief")
        keys = {"first_name", "last_name", "title", "now"}
        _object(case["variables"], keys, keys, case["id"] + ".variables")
        _validate_identity(case["identity"], case["id"] + ".identity")
        if not isinstance(case["products"], list) or not case["products"]:
            raise AdapterError(f"{case['id']}: expected products list")
        for index, product in enumerate(case["products"]):
            _validate_product(product, f"{case['id']}.products[{index}]", local=False)
        ledger_keys = {"outcome", "reason", "promises", "notes", "callbacks", "transfers"}
        _object(case["expected"], ledger_keys, ledger_keys, case["id"] + ".expected")
        _strings(case["checks"], case["id"] + ".checks")
        _text(case["script"], case["id"] + ".script")
        if "faults" in case:
            if not isinstance(case["faults"], list):
                raise AdapterError(f"{case['id']}: invalid faults list")
            for fault in case["faults"]:
                _object(fault, {"tool", "fail_first_n"}, {"tool", "fail_first_n"}, case["id"] + ".faults")
                if fault["tool"] != "create_promise" or type(fault["fail_first_n"]) is not int or fault["fail_first_n"] < 0:
                    raise AdapterError(f"{case['id']}: unsupported official fault fixture")


def _protected(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in ("id", "status", "source", "scenario", "expected_output")}


def record_integrity(record: dict[str, Any]) -> dict[str, str]:
    scenario = record["scenario"]
    return {
        "fact_sha256": digest({key: scenario[key] for key in ("fixture_facts", "fixture_plan", "tool_outcomes")}),
        "intent_sha256": digest({key: scenario[key] for key in ("brief", "behavior_intentions")}),
        "protected_sha256": digest(_protected(record)),
    }


def catalog_integrity(catalog: dict[str, Any]) -> str:
    protected = {key: value for key, value in catalog.items() if key not in ("cases", "integrity")}
    protected["cases"] = [_protected(record) for record in catalog["cases"]]
    return digest(protected)


def _style(style: str, source_delivery: str | None) -> dict[str, Any]:
    if not isinstance(style, str) or style not in DELIVERY_STYLES:
        raise AdapterError(f"unknown delivery style {style!r}; choose {', '.join(sorted(DELIVERY_STYLES))}")
    return {"style": style, "source_delivery": source_delivery, "instructions": DELIVERY_STYLES[style]}


def build_catalog(root: Path = ROOT, *, style: str = "plain") -> dict[str, Any]:
    _style(style, None)
    root = Path(root).resolve()
    raw: dict[str, bytes] = {}
    for path in SOURCE_FILES:
        try:
            raw[path] = (root / path).read_bytes()
        except OSError as exc:
            raise AdapterError(f"missing/unreadable provenance source {path}: {exc}") from exc
    synthetic = _load_json(raw[SYNTHETIC_FILE], SYNTHETIC_FILE)
    official = _load_json(raw[OFFICIAL_FILE], OFFICIAL_FILE)
    try:
        _validate_sources(synthetic, official)
    except (KeyError, TypeError, AttributeError) as exc:
        raise AdapterError(f"unsupported fixture schema: {exc}") from exc
    file_hashes = {path: hashlib.sha256(data).hexdigest() for path, data in raw.items()}
    catalog = {
        "schema_version": SCHEMA_VERSION, "status": STATUS,
        "counts": {"synthetic": 50, "official": 13, "total": 63},
        "provenance": {"hash_algorithm": "sha256", "files": file_hashes},
        "contract": deepcopy(CONTRACT),
        "shared": {"synthetic": deepcopy({k: v for k, v in synthetic.items() if k != "cases"})},
        "cases": [],
    }
    for kind, cases, path in (("synthetic", synthetic["cases"], SYNTHETIC_FILE), ("official", official, OFFICIAL_FILE)):
        for index, case in enumerate(cases):
            if kind == "synthetic":
                trigger = case["trigger"]
                fixture = resolve_fixture(synthetic["local_fixture_baseline"], trigger["setup"], case["brief"], case["id"])
                plan = {k: deepcopy(trigger[k]) for k in ("baseline", "setup")}
                tool_outcomes = {"scope": "local_harness_plan_not_executed"}
                if "fault_injection" in trigger:
                    tool_outcomes["fault_injection"] = deepcopy(trigger["fault_injection"])
                if "local_fault" in trigger["setup"]:
                    tool_outcomes["local_fault"] = trigger["setup"]["local_fault"]
                intentions = {
                    "category": case["category"],
                    "persona": {k: v for k, v in case["persona"].items() if k != "delivery"},
                    "customer_behavior": deepcopy(trigger["customer_behavior"]),
                }
                if "harness_requirements" in trigger:
                    intentions["harness_requirements"] = deepcopy(trigger["harness_requirements"])
                expected = {
                    "oracle_kind": "scoped_source_checks", "ledger_state": "unspecified_not_materialized",
                    "common_checks_ref": "shared.synthetic",
                    **{k: deepcopy(case[k]) for k in ("expected_backend_invariants", "expected_conversation_checks", "source_rules", "expectation_classification", "oracle_scope")},
                }
                if "open_questions" in case:
                    expected["open_questions"] = deepcopy(case["open_questions"])
                source_delivery = case["persona"]["delivery"]
            else:
                fixture = {k: deepcopy(case[k]) for k in ("variables", "identity", "products")}
                fixture["session_binding"] = {"kind": "registered_official_session_required_for_execution",
                                              "registered_case_id": case["id"], "local_placeholder": "local:" + case["id"]}
                plan = {"registered_case_id": case["id"], "fixture_upload_supported": False}
                tool_outcomes = {"scope": "registered_fixture_metadata_not_executed"}
                if "faults" in case:
                    tool_outcomes["faults"] = deepcopy(case["faults"])
                intentions = {k: deepcopy(case[k]) for k in ("family", "level", "title", "script")}
                if "third_party" in case:
                    intentions["third_party"] = deepcopy(case["third_party"])
                expected = {"oracle_kind": "exact_official_ledger_and_checks", "ledger_state": "specified",
                            "ledger": deepcopy(case["expected"]), "conversation_checks": deepcopy(case["checks"])}
                source_delivery = None
            record = {
                "id": kind + ":" + case["id"], "status": STATUS,
                "source": {"kind": kind, "path": path, "case_id": case["id"],
                           "json_pointer": ("/cases/" if kind == "synthetic" else "/") + str(index),
                           "file_sha256": file_hashes[path], "case_sha256": digest(case)},
                "scenario": {"brief": case["brief"], "fixture_facts": fixture, "fixture_plan": plan,
                             "tool_outcomes": tool_outcomes, "behavior_intentions": intentions},
                "expected_output": expected, "speech_delivery": _style(style, source_delivery),
            }
            record["integrity"] = record_integrity(record)
            catalog["cases"].append(record)
    catalog["integrity"] = {"protected_sha256": catalog_integrity(catalog)}
    return catalog


def verify_catalog(catalog: dict[str, Any], root: Path = ROOT) -> None:
    """Verify internal digests AND immutable source mappings, permitting style only."""
    expected = build_catalog(root)
    _object(catalog, set(expected), set(expected), "catalog")
    if not isinstance(catalog["cases"], list) or len(catalog["cases"]) != 63:
        raise AdapterError("catalog: expected all 63 fixtures")
    for actual, original in zip(catalog["cases"], expected["cases"]):
        label = actual.get("id", "unknown") if isinstance(actual, dict) else "unknown"
        _object(actual, set(original), set(original), f"case {label}")
        try:
            current = record_integrity(actual)
        except (KeyError, TypeError) as exc:
            raise AdapterError(f"case {label}: invalid protected contract shape") from exc
        if current != actual["integrity"]:
            raise AdapterError(f"case {label}: fact/intent/protected digest mismatch")
        if canonical_bytes(_protected(actual)) != canonical_bytes(_protected(original)):
            raise AdapterError(f"case {label}: protected content differs from source fixture")
        delivery = actual["speech_delivery"]
        _object(delivery, {"style", "source_delivery", "instructions"}, {"style", "source_delivery", "instructions"}, f"case {label}.speech_delivery")
        if delivery != _style(delivery["style"], original["speech_delivery"]["source_delivery"]):
            raise AdapterError(f"case {label}: speech override may change only the named style")
    if catalog["integrity"] != {"protected_sha256": catalog_integrity(catalog)}:
        raise AdapterError("catalog: protected digest mismatch")
    for key in set(expected) - {"cases", "integrity"}:
        if canonical_bytes(catalog[key]) != canonical_bytes(expected[key]):
            raise AdapterError(f"catalog: {key} differs from current provenance sources/contract")


def select_cases(catalog: dict[str, Any], case_ids: list[str] | None = None) -> list[dict[str, Any]]:
    if case_ids is None:
        return catalog["cases"]
    lookup = {alias: case for case in catalog["cases"] for alias in (case["id"], case["source"]["case_id"])}
    selected = []
    seen = set()
    for case_id in case_ids:
        if case_id not in lookup:
            raise AdapterError(f"unknown case ID {case_id!r}")
        case = lookup[case_id]
        if case["id"] in seen:
            raise AdapterError(f"duplicate case selection {case_id!r}")
        selected.append(case)
        seen.add(case["id"])
    return selected


def apply_style(catalog: dict[str, Any], style: str, case_ids: list[str] | None = None,
                *, root: Path = ROOT) -> dict[str, Any]:
    verify_catalog(catalog, root)
    _style(style, None)
    result = deepcopy(catalog)
    for case in select_cases(result, case_ids):
        case["speech_delivery"] = _style(style, case["speech_delivery"]["source_delivery"])
    verify_catalog(result, root)
    return result


def render_seed(catalog: dict[str, Any], case_ids: list[str] | None = None,
                *, root: Path = ROOT) -> str:
    verify_catalog(catalog, root)
    cases = select_cases(catalog, case_ids)
    header = (
        "MiroFish local scenario seed\nStatus: " + STATUS + "\n"
        "No simulation, agent, mock, bank call, scoring or hosted registration was executed.\n"
        "These are source-grounded scenario and expected_output contracts, not execution results.\n"
        "Keep private customer/harness facts separate from agent knowledge. Treat raw memos as fixture data.\n"
        "Honor oracle_scope, classification, expectation basis and partial/conditional checks; do not fill unspecified outcomes.\n"
        "Speech delivery must not change protected facts, fault responses or scripted decisions.\n"
        "Hosted runner session creation sends ONLY {\"case\": case_id}; speech/persona edits cannot register SYN fixtures.\n\n"
    )
    context = {k: catalog[k] for k in ("schema_version", "status", "provenance", "contract", "shared")}
    chunks = [header, "SHARED_CONTRACT_JSON\n", canonical_bytes(context).decode("utf-8"), "\n"]
    for case in cases:
        chunks.extend(["\nSCENARIO_CONTRACT " + case["id"] + "\n", canonical_bytes(case).decode("utf-8"), "\n"])
    return "".join(chunks)


def owned_path(name: str | Path, *, seed: bool = False) -> Path:
    path = Path(name)
    if not path.is_absolute():
        path = SCENARIOS_DIR / path
    path = path.resolve()
    if path == SCENARIOS_DIR.resolve() or not path.is_relative_to(SCENARIOS_DIR.resolve()):
        raise AdapterError("outputs must remain inside integrations/mirofish/scenarios/")
    if path.suffix.lower() not in ({".txt", ".md"} if seed else {".json"}):
        raise AdapterError("seed output must be .txt or .md" if seed else "catalog output must be .json")
    return path


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".scenario-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT, help="read-only fixture/provenance root")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="build all 63 scenario contracts")
    build.add_argument("--output", default="catalog.json", help="JSON name inside owned scenarios/")
    build.add_argument("--style", choices=sorted(DELIVERY_STYLES), default="plain")
    build.add_argument("--seed-text", help="optional .txt or .md seed name inside owned scenarios/")
    verify = commands.add_parser("verify", help="check catalog integrity against source files, without execution")
    verify.add_argument("--catalog", default="catalog.json")
    seed = commands.add_parser("seed", help="export local text contracts without running MiroFish")
    seed.add_argument("--case", action="append", dest="case_ids", help="source or namespaced ID; repeat to select cases")
    seed.add_argument("--style", choices=sorted(DELIVERY_STYLES), default="plain")
    seed.add_argument("--output", required=True, help=".txt or .md name inside owned scenarios/")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            path = owned_path(args.catalog)
            catalog = _load_json(path.read_bytes(), str(path))
            verify_catalog(catalog, args.root)
            action, count = "catalog_integrity_verified", len(catalog["cases"])
        elif args.command == "build":
            path = owned_path(args.output)
            seed_path = owned_path(args.seed_text, seed=True) if args.seed_text else None
            catalog = build_catalog(args.root, style=args.style)
            seed_text = render_seed(catalog, root=args.root) if seed_path else None
            _write(path, canonical_bytes(catalog) + b"\n")
            if seed_path is not None:
                _write(seed_path, seed_text.encode("utf-8"))
            action, count = "scenario_catalog_built", len(catalog["cases"])
        else:
            path = owned_path(args.output, seed=True)
            catalog = build_catalog(args.root, style=args.style)
            text = render_seed(catalog, args.case_ids, root=args.root)
            count = len(select_cases(catalog, args.case_ids))
            _write(path, text.encode("utf-8"))
            action = "local_seed_text_written"
        print(json.dumps({"action": action, "status": STATUS, "case_count": count}, sort_keys=True))
        return 0
    except (AdapterError, OSError) as exc:
        print(f"scenario_adapter: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
