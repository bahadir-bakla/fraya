"""Offline authored speech-text challenges; never voice/ASR certification.

Only immutable registered bank facts are reused. Actor scripts and expected
ledgers are independent authored data. This entry point permits keyless plans
and offline evidence checks, and deliberately has no live execution path.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

import benchmark_adapter as b
import benchmark_runner as runner

KIT = b.KIT
OUT = b.OUT / "speech-stress-cases.json"
SCOPE = "authored_text_only_speech_stress_on_registered_bank_facts_not_official_pub_score"
PINS = {
    "tools/score.py": "daf55989d47915d9a4f0387c2a4f6748580fcdf66b7d3ec61356925efb0d17d7",
    "tools/openapi.json": "9a8410b12e5c82b6c6a30e9ed7030574d6f919cafdb1e035cef7bd876b0badb8",
    "tools/run_cases.py": "c96da9f9189d82850e46bfc551603ff5a62847025b5c50a77b923ad999f3767c",
    "public-test-set.json": "fb7f4c0082eecb724a6faab771b4339bc62655627e49251e6bb2a0cf59a72fcb",
    "briefs/brief-a.md": "d57c049c89aec4615f5b939c5a96ee9bd194142d17045bc4036615cfbdf0f1c7",
    "briefs/brief-b.md": "c59c70099148b91c13e9c5e40246a63b58638f09469d735f8eb65771bb63d550",
}


def _source_pins():
    result = {}
    for name, wanted in PINS.items():
        actual = hashlib.sha256((KIT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != wanted:
            raise ValueError("Original kit source changed: " + name)
        result[name] = actual
    return result


def _request_schema(tool):
    return deepcopy(b.local.API["paths"]["/" + tool]["post"]["requestBody"]["content"]["application/json"]["schema"])


def _record_schema(tool):
    schema = _request_schema(tool)
    schema["properties"].pop("customer_id")
    schema["required"].remove("customer_id")
    if tool == "add_note":
        # The scorer's expected ledger contains disposition, not optional prose.
        schema["properties"].pop("text", None)
    schema["additionalProperties"] = False
    return schema


def scenario_schema():
    """Typed envelope composed from the original ZIP's OpenAPI contracts."""
    text = {"type": "string", "minLength": 1}
    texts = {"type": "array", "minItems": 1, "items": text}
    ledger = {"type": "object", "additionalProperties": False,
              "required": ["outcome", "reason", "promises", "notes", "callbacks", "transfers"],
              "properties": {
                  "outcome": _request_schema("close_call")["properties"]["outcome"],
                  "reason": {"type": ["string", "null"]},
                  **{key: {"type": "array", "items": _record_schema(tool)} for key, tool in (
                      ("promises", "create_promise"), ("notes", "add_note"),
                      ("callbacks", "schedule_callback"), ("transfers", "transfer_to_agent"))}}}
    props = {
        "id": {"enum": ["PUB-01", "PUB-11"]}, "brief": {"enum": ["A", "B"]},
        "variant_id": {"type": "string", "pattern": r"^PUB-(01|11)__speech_[a-z0-9_]+$"},
        "family": text, "level": text, "title": text, "script": text,
        "variables": {"type": "object"}, "identity": {"type": "object"},
        "products": {"type": "array"}, "faults": {"type": "array"},
        "expected": ledger, "checks": texts, "oracle_rule_refs": texts,
        "third_party": {"type": "boolean"}, "style": {"const": None},
        "delivery_profile": {"const": "plain"}, "local_only": {"const": False},
        "hosted_registered": {"const": True}, "execution_status": {"const": "not_executed"},
        "evaluation_scope": {"const": SCOPE},
        "stress": {"type": "object", "additionalProperties": False,
                   "required": ["modality", "tags", "limitations"],
                   "properties": {"modality": {"const": "text_only_approximation"},
                                  "tags": texts, "limitations": text}},
    }
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "array", "minItems": 1, "maxItems": 12,
            "items": {"type": "object", "additionalProperties": False,
                      "required": list(props), "properties": props}}


def _validate_rows(rows):
    try:
        b.jsonschema.Draft202012Validator(scenario_schema(), format_checker=b.jsonschema.FormatChecker()).validate(rows)
        # Reject NaN/Infinity and JSON-incompatible values before making snapshots.
        json.dumps(rows, allow_nan=False)
    except (b.jsonschema.ValidationError, TypeError, ValueError) as error:
        raise ValueError("Invalid speech stress catalog: " + str(error).splitlines()[0]) from None
    seen = set()
    reasons = {"promise": {None}, "paid": {None},
               "no_promise": {"refused", "hardship", "dispute", "service_error"},
               "not_verified": {"failed", "declined"},
               "not_reached": {"callback", "no_callback", "wrong_number", "deceased", "unclear"},
               "transferred": {"restructuring", "human", "support"}}
    for row in rows:
        base = b.PUBLIC[row["id"]]
        if row["variant_id"] in seen or not row["variant_id"].startswith(row["id"] + "__speech_"):
            raise ValueError("Duplicate or mismatched authored variant")
        seen.add(row["variant_id"])
        for field in ("brief", "variables", "identity", "products", "faults"):
            # JSON canonical comparison distinguishes false from zero.
            if runner.digest(row[field]) != runner.digest(base.get(field, [])):
                raise ValueError("Immutable registered bank fact changed: " + field)
        if any(ref not in b.local.CATALOG["rule_registry"] for ref in row["oracle_rule_refs"]):
            raise ValueError("Unknown original rule reference")
        exp = row["expected"]
        if exp["reason"] not in reasons[exp["outcome"]]:
            raise ValueError("Invalid closing outcome/reason pair")
        fixture = kernel_case(row)
        products = {p["product_id"]: p for p in fixture["facts"]["products"]}
        used = set()
        for collection in ("promises", "notes"):
            for record in exp[collection]:
                pid = record["product_id"]
                if pid not in products or pid in used:
                    raise ValueError("Unknown or repeated product disposition")
                used.add(pid)
                if collection == "promises":
                    p = products[pid]
                    floor = p.get("minimum_payment", p.get("instalment_amount"))
                    amount = Decimal(str(record["amount"]))
                    if not Decimal(str(floor)) <= amount <= Decimal(str(p["past_due"])) or amount != amount.quantize(Decimal("0.01")):
                        raise ValueError("Promise violates original amount floor/range")
                    day = date.fromisoformat(record["date"])
                    today = date.fromisoformat(row["variables"]["now"][:10])
                    if not b.local.business(day) or not today <= day <= b.local.deadline(fixture, p):
                        raise ValueError("Promise violates original per-product date window")
        if row["brief"] == "A" and exp["notes"]:
            raise ValueError("Brief A forbids notes")
        if row["third_party"] and (exp["promises"] or exp["notes"] or exp["outcome"] != "not_reached"):
            raise ValueError("Sibling recipient cannot authorize account actions")
        if exp["outcome"] in {"not_verified", "not_reached"} and (used or exp["transfers"]):
            raise ValueError("Unverified/unreached oracle has account effects")
        if len(exp["callbacks"]) > 1 or len(exp["transfers"]) > 1:
            raise ValueError("Repeated callback/transfer")
        for callback in exp["callbacks"]:
            now = datetime.fromisoformat(row["variables"]["now"])
            at = datetime.fromisoformat(callback["date"] + "T" + callback["time"])
            if at.date() not in {now.date(), b.local.after(now.date(), 1)} or not "10:00" <= callback["time"] <= "19:00" or at <= now:
                raise ValueError("Callback outside original window")
        if bool(exp["callbacks"]) != (exp["outcome"] == "not_reached" and exp["reason"] == "callback"):
            raise ValueError("Callback does not match close outcome")
        if exp["outcome"] == "transferred":
            queue = {"human": "general", "support": "support", "restructuring": "restructuring"}[exp["reason"]]
            if exp["transfers"] != [{"queue": queue}] or exp["notes"]:
                raise ValueError("Transfer oracle contradicts queue or note prohibition")
        elif exp["transfers"]:
            raise ValueError("Transfer requires transferred outcome")
        elif bool(exp["promises"]) != (exp["outcome"] == "promise"):
            raise ValueError("Promise close must match recorded promises")
        if row["brief"] == "B" and exp["outcome"] in {"promise", "paid", "no_promise"}:
            if used != set(products):
                raise ValueError("Brief B requires every product disposition")
            if not exp["promises"]:
                notes = {n["product_id"]: n["reason"] for n in exp["notes"]}
                first = next((notes[pid] for pid in products if notes[pid] != "paid"), None)
                if (exp["outcome"], exp["reason"]) != (("paid", None) if first is None else ("no_promise", first)):
                    raise ValueError("Brief B close does not match account-order notes")


@dataclass(frozen=True)
class Promise:
    product_id: str
    amount: Decimal
    date: str


@dataclass(frozen=True)
class Note:
    product_id: str
    reason: str


@dataclass(frozen=True)
class Callback:
    date: str
    time: str


@dataclass(frozen=True)
class Transfer:
    queue: str


@dataclass(frozen=True)
class ExpectedLedger:
    outcome: str
    reason: str | None
    promises: tuple[Promise, ...]
    notes: tuple[Note, ...]
    callbacks: tuple[Callback, ...]
    transfers: tuple[Transfer, ...]

    @classmethod
    def from_dict(cls, expected):
        return cls(expected["outcome"], expected["reason"],
                   tuple(Promise(p["product_id"], Decimal(str(p["amount"])), p["date"]) for p in expected["promises"]),
                   tuple(Note(**n) for n in expected["notes"]),
                   tuple(Callback(**c) for c in expected["callbacks"]),
                   tuple(Transfer(**t) for t in expected["transfers"]))


@dataclass(frozen=True)
class StressScenario:
    bank_case_id: str
    variant_id: str
    script: str
    expected: ExpectedLedger
    _snapshot: str

    def to_row(self):
        return json.loads(self._snapshot)


@dataclass(frozen=True)
class StressCatalog:
    scenarios: tuple[StressScenario, ...]

    @classmethod
    def from_rows(cls, rows):
        _validate_rows(rows)
        return cls(tuple(StressScenario(row["id"], row["variant_id"], row["script"],
                                       ExpectedLedger.from_dict(row["expected"]),
                                       json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False)) for row in rows))

    def to_rows(self):
        return [scenario.to_row() for scenario in self.scenarios]

    def __len__(self):
        return len(self.scenarios)


def catalog(path=OUT):
    return StressCatalog.from_rows(json.loads(Path(path).read_text(encoding="utf-8")))


def validate_hosted(rows):
    """Validate own authored contracts, never redteam_adapter catalog equality."""
    _validate_rows(rows.to_rows() if isinstance(rows, StressCatalog) else rows)


def verify_pack(path=OUT):
    sources = _source_pins()
    pack = catalog(path)
    if not 8 <= len(pack) <= 12:
        raise ValueError("Full speech stress pack requires eight to twelve cases")
    return {"evaluation_scope": SCOPE, "modality": "text_only_approximation",
            "sources": sources, "catalog_sha256": runner.digest(pack.to_rows()),
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
            "hash_method": "utf8_lf_normalized_v1", "execution_status": "not_executed"}


def kernel_case(row):
    """Synthetic offline receipt fixture, not a registration or actor prompt."""
    case = deepcopy(row)
    case["facts"] = {"variables": {**row["variables"], "customer_id": "local-" + row["variant_id"]},
                     "identity": deepcopy(row["identity"]),
                     "products": [{"product_id": "p" + str(i + 1), **product} for i, product in enumerate(row["products"])],
                     "third_party": row["third_party"], "faults": deepcopy(row["faults"])}
    return case


def persona_for(row):
    validate_hosted([row])
    # Only the minimal actor fields enter the formatter; no expected ledger,
    # account payload, backend IDs, rule registry, checks, or receipt program.
    actor = {key: deepcopy(row[key]) for key in ("id", "brief", "family", "title", "variables", "script", "third_party", "style")}
    actor["checks"] = []
    spec = b.official.persona_for(actor, {"identity": {} if row["third_party"] else row["identity"]})
    spec["prompt"] = spec["prompt"].replace(
        '- If the caller reads something back and it matches what you agreed, say "Yes, I confirm."',
        '- Follow the authored scenario for consent. A negative or qualified confirmation is never a yes. Confirm only when the scenario permits it and the whole read-back matches your final decision.')
    spec["prompt"] += ("\nThese are text-only approximations of rapid speech, dialect and code switching; no audio or ASR behavior is simulated. "
                       "Keep the conversation in English, retaining only the short interjections explicitly written in the scenario. "
                       "The authored scenario takes precedence over generic delivery rules, including fragmentation and self-correction. "
                       "Never invent missing dates, amounts, consent or sibling authority.")
    spec["name"] = row["variant_id"]
    # Evaluation-only criteria are distinct from the actor prompt.
    spec["successCriteria"] = ("Authoritative authored customer behavior (quoted evaluation data):\n"
                               + json.dumps({"customer_script": row["script"]}, ensure_ascii=False)
                               + "\n- " + "\n- ".join(row["checks"] + b.TRANSCRIPT_CHECKS))
    return spec


def score(case, ledger, judge=None):
    try:
        row = {k: v for k, v in case.items() if k not in {"facts", "_session_customer_id"}}
        validate_hosted([row])
        if "facts" in case and runner.digest(case["facts"]) != runner.digest(kernel_case(row)["facts"]):
            raise ValueError("Synthetic receipt fixture differs from immutable bank facts")
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"pass": False, "ledger_and_trace_pass": False, "transcript_pass": False,
                "failed": ["invalid authored speech contract"], "execution_status": "reference_only"}
    result = b.score(case, ledger, judge)
    result.update(modality="text_only_approximation", voice_asr_certified=False)
    return result


def plan(pack=None, **settings):
    """Accept a typed catalog or validated row selection for keyless planning."""
    pack = catalog() if pack is None else pack
    rows = pack.to_rows() if isinstance(pack, StressCatalog) else pack
    result = runner.plan(rows, sys.modules[__name__], **settings)
    result.update(modality="text_only_approximation", voice_asr_certified=False,
                  execution_supported=False,
                  execution_requires=["Live execution is disabled for this offline pack"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=OUT)
    parser.add_argument("--brief", choices=["A", "B"])
    parser.add_argument("--only")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--parallel-reps", action="store_true")
    parser.add_argument("--execute", action="store_true", help="Rejected: this adapter is offline only")
    args = parser.parse_args(argv)
    try:
        if args.execute:
            raise runner.RunnerError("speech_stress_offline_only")
        manifest = verify_pack(args.cases)
        result = plan(catalog(args.cases), brief=args.brief, only=args.only,
                      reps=args.reps, batch_size=args.batch_size, parallel_reps=args.parallel_reps)
        result["source_manifest"] = manifest
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, runner.RunnerError) as error:
        print(json.dumps({"execution_status": "not_completed", "error_code": str(error)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
