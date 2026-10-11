"""Bounded public13 conditional local ledger replay: candidate A and frozen B14.

Requires a parent-validated artifact and its exact SHA256. Three deterministic
repeats use fresh mock Banks; they do not qualify independent actors, extraction,
voice or conversation judging. Only the original competition-v3 score_ledger
receives expected outcomes. No training, external inference or remote calls.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "competition-v3/build-the-builder"
PREFIX = ROOT / "analysis/final-sprint-public-replay-20261011"
B_SHA = "1768e23ee0c24c530786fc3fb7e58bf16a96ca48bb8d27914603109047d45163"
# Original immutable kit pins, also recorded by the earlier public replay.
KIT_PINS = {
    "public-test-set.json": "fb7f4c0082eecb724a6faab771b4339bc62655627e49251e6bb2a0cf59a72fcb",
    "tools/score.py": "daf55989d47915d9a4f0387c2a4f6748580fcdf66b7d3ec61356925efb0d17d7",
    "tools/openapi.json": "9a8410b12e5c82b6c6a30e9ed7030574d6f919cafdb1e035cef7bd876b0badb8",
    "docs/workflow-format.md": "4ff70b5a37b647122e6a6f3ca1a523b207dbcdf6afb32058de8451a8c7d1dcfc",
    "docs/tools-and-code.md": "56be9c87fbfddf5855c25fe83d4633bafd885d7cba5677133c15d211eb21b711",
    "briefs/brief-a.md": "d57c049c89aec4615f5b939c5a96ee9bd194142d17045bc4036615cfbdf0f1c7",
    "briefs/brief-b.md": "c59c70099148b91c13e9c5e40246a63b58638f09469d735f8eb65771bb63d550",
}
SOURCE_FILES = (
    "scripts/local_public_replay.py", "scripts/compare_local_candidate_kernels.py",
    "integrations/customer-datasets/workflow_replay.py",
    "integrations/customer-datasets/benchmark_adapter.py",
    "integrations/customer-datasets/adapter.py", "research/field-cases/local_runner.py",
    "research/field-cases/scenarios.json", "competition/validation.py",
    "competition/releases/classic-baseline/manifest.json",
    "competition/releases/classic-baseline/b.review-template.json",
    "competition-v3/build-the-builder/tools/run_cases.py",
    "competition-v3/build-the-builder/freya.py",
)
SCOPE = ("public13 conditional local ledger replay; three deterministic repeats "
         "with fresh mock Banks; no independent actor, extractor, voice or judge qualification")


class AdapterUnsupported(ValueError):
    def __str__(self):
        return "ADAPTER_UNSUPPORTED:" + super().__str__()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def label(path):
    path = Path(path).resolve()
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def snapshot(paths):
    return {label(p): digest(p) for p in sorted(set(paths), key=str)}


def deny_network():
    def denied(*args, **kwargs):
        raise RuntimeError("offline_network_denied")
    class DeniedSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            denied()
    socket.socket = DeniedSocket
    for key in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        setattr(socket, key, denied)
    urllib.request.urlopen = denied
    urllib.request.OpenerDirector.open = denied


def schema_contract(schema, brief):
    """Select only from actual extraction declarations, before executing anything."""
    if not isinstance(schema, list) or not schema:
        raise AdapterUnsupported("missing_extraction_schema")
    if any(not isinstance(s, dict) or s.get("type") != "string" or
           not isinstance(s.get("name"), str) for s in schema):
        raise AdapterUnsupported("non_string_extraction_schema")
    fields = {s["name"]: s for s in schema}
    if len(fields) != len(schema):
        raise AdapterUnsupported("duplicate_extraction_field")
    names = frozenset(fields)
    choices = {
        frozenset(("event", "raw", "admin")): "frozen",
        frozenset(("recipient_act", "raw", "admin")): "recipient",
        frozenset(("security_answer_event", "raw", "admin")): "classic",
        frozenset(("security_value", "raw", "admin")): "security_value",
        frozenset(("security_act", "security_value", "raw", "admin")): "security_act_value",
        frozenset(("event", "raw", "admin", "recipient_act", "security_answer_copy")): "live_copy",
    }
    if brief == "B":
        if names != frozenset(("event", "raw_speech", "admin")):
            raise AdapterUnsupported("B_schema_not_frozen_contract")
        if "scalar-v6" not in fields["event"].get("description", ""):
            raise AdapterUnsupported("B_event_grammar_not_declared")
        return "frozen"
    contract = choices.get(names)
    if contract is None:
        raise AdapterUnsupported("unknown_actual_schema:" + ",".join(sorted(names)))
    if "event" in fields and not fields["event"].get("description", "").startswith("Tagged-primary-v8."):
        raise AdapterUnsupported("A_event_grammar_not_declared")
    if "recipient_act" in fields:
        declared = set(fields["recipient_act"].get("enum_values", []))
        needed = ({"SELF", "OTHER", "WRONG_NUMBER", "DECEASED", "UNKNOWN"}
                  if contract == "live_copy" else
                  {"recipient", "third_party", "wrong_number", "deceased", "unknown"})
        if declared != needed:
            raise AdapterUnsupported("recipient_enum_not_supported")
    for key in ("security_answer_event", "security_value", "security_answer_copy"):
        if key in fields:
            description = fields[key].get("description", "").lower()
            if "yyyy-mm-dd" not in description or "four" not in description:
                raise AdapterUnsupported("security_copy_contract_not_declared:" + key)
    if contract == "live_copy":
        if "Outside recipient emit UNKNOWN" not in fields["recipient_act"].get("description", ""):
            raise AdapterUnsupported("recipient_outside_phase_default_not_declared")
        if "Otherwise empty string" not in fields["security_answer_copy"].get("description", ""):
            raise AdapterUnsupported("security_outside_phase_default_not_declared")
    return contract


class SchemaNodes(dict):
    """Expose the actual current node's schema to the reused actor, never an oracle."""
    def __getitem__(self, key):
        node = super().__getitem__(key)
        self.current_schema = node.get("extraction_schema", [])
        return node


def actor_factory(driver, comparison, nodes):
    base = driver.Actor
    adapters = {
        "frozen": comparison.contract_actor(base, "frozen"),
        "recipient": comparison.contract_actor(base, "v2"),
        "classic": comparison.contract_actor(base, "classic"),
        "security_value": comparison.contract_actor(base, "v2", "security_value"),
        "security_act_value": comparison.contract_actor(base, "v2", "security_act_value"),
    }
    class SchemaActor:
        def __init__(self, case):
            # fixture() projects script/facts only; expected/checks never reach here.
            self.core = base(case)

        def mapped(self, contract, variables):
            proxy = object.__new__(adapters[contract])
            proxy.__dict__ = self.core.__dict__
            return proxy.next(variables)

        def next(self, variables):
            schema = nodes.current_schema
            contract = schema_contract(schema, self.core.case["brief"])
            state = variables.get("state", {})
            if isinstance(state, str):
                state = json.loads(state)
            phase = state.get("phase", "recipient")
            if contract == "recipient" and phase != "recipient":
                raise AdapterUnsupported("recipient_schema_outside_recipient_phase")
            if contract in {"classic", "security_value", "security_act_value"} and phase not in {"dob", "phone"}:
                raise AdapterUnsupported("security_schema_outside_security_phase")
            if contract == "live_copy":
                # Reuse existing contract_actor mappings of the same authored event.
                if phase == "recipient":
                    mapped = self.mapped("recipient", variables)
                    kind = mapped.pop("recipient_act")
                    result = dict(mapped, event="k=" + kind + ";c=1;END",
                                  recipient_act={"recipient": "SELF", "third_party": "OTHER",
                                                 "wrong_number": "WRONG_NUMBER", "deceased": "DECEASED",
                                                 "unknown": "UNKNOWN"}[kind], security_answer_copy="")
                elif phase in {"dob", "phone"}:
                    mapped = self.mapped("security_value", variables)
                    answer = mapped.pop("security_value")
                    result = dict(mapped, event="k=security;c=1;v=" + answer + ";END",
                                  recipient_act="UNKNOWN", security_answer_copy=answer)
                else:
                    result = dict(self.mapped("frozen", variables),
                                  recipient_act="UNKNOWN", security_answer_copy="")
            else:
                result = self.mapped(contract, variables)
            if set(result) != {s["name"] for s in schema}:
                raise AdapterUnsupported("mapped_fields_do_not_match_actual_schema")
            for field in schema:
                value = result[field["name"]]
                if field.get("enum_values") and value not in field["enum_values"]:
                    raise AdapterUnsupported("authored_value_outside_declared_enum")
                if field.get("validation_pattern") and not re.fullmatch(field["validation_pattern"], value):
                    raise AdapterUnsupported("authored_value_outside_declared_pattern")
            return result
    return SchemaActor


def worker(args, before, paths):
    deny_network()
    # Snapshot before imports: imported adapters read their own local sources.
    if snapshot(paths) != before:
        raise ValueError("SOURCE_PIN_CHANGED_BEFORE_WORKER")
    for relative, expected in KIT_PINS.items():
        if digest(KIT / relative) != expected:
            raise ValueError("ORIGINAL_KIT_PIN_MISMATCH:" + relative)
    frozen_path = ROOT / "competition/releases/classic-baseline/b.review-template.json"
    if digest(frozen_path) != B_SHA:
        raise ValueError("FROZEN_B14_PIN_MISMATCH")
    if digest(args.candidate_workflow) != args.candidate_sha256:
        raise ValueError("CANDIDATE_SHA256_MISMATCH")
    driver = load("final_public_driver", ROOT / "scripts/local_public_replay.py")
    comparison = load("final_public_contracts", ROOT / "scripts/compare_local_candidate_kernels.py")
    sys.path.insert(0, str(ROOT / "integrations/customer-datasets"))
    wr = load("final_public_workflow_replay", ROOT / "integrations/customer-datasets/workflow_replay.py")
    validation = load("final_public_validation", ROOT / "competition/validation.py")
    scorer = load("final_public_original_scorer", KIT / "tools/score.py").score_ledger
    raw = json.loads(args.candidate_workflow.read_text(encoding="utf-8"))
    candidate = raw.get("workflow", raw)
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))["workflow"]
    workflows = {"A": candidate, "B": frozen}
    mappings = {}
    validation_notes = {}
    for brief, workflow in workflows.items():
        historical = brief == "B" or args.candidate_sha256 == driver.PINS["A"][1]
        # Immutable published exports contain platform-populated nulls/config;
        # the current builder-input validator cannot validate those exports.
        errors = [] if historical else validation.validate(workflow, wr.b.local.API)
        validation_notes[brief] = ("hash-pinned historical export; builder-input validation inapplicable"
                                   if historical else "current builder-input validation passed")
        if errors:
            raise ValueError("WORKFLOW_VALIDATION_FAILED:" + brief + ":" + json.dumps(errors))
        if not isinstance(workflow.get("test_variables", {}), dict):
            raise AdapterUnsupported("test_variables_not_declared_object")
        defaults = workflow.get("test_variables", {})
        if any(re.search(r"key|token|secret|password|credential", k, re.I) and v
               for k, v in defaults.items()):
            raise AdapterUnsupported("credential_like_call_default")
        mappings[brief] = {
            node_id: {"fields": [s["name"] for s in node.get("extraction_schema", [])],
                      "mapping": schema_contract(node.get("extraction_schema"), brief)}
            for node_id, node in workflow["nodes"].items()
            if node.get("node_type") == "conversation" and not node.get("passthrough")
        }
    public = json.loads((KIT / "public-test-set.json").read_text(encoding="utf-8"))
    if (len(public) != 13 or {c["id"] for c in public} != {f"PUB-{i:02d}" for i in range(1, 14)}
            or sum(c["brief"] == "A" for c in public) != 10 or sum(c["brief"] == "B" for c in public) != 3):
        raise ValueError("PUBLIC13_INVENTORY_MISMATCH")
    driver.exact_condition = comparison.documented_condition
    base_actor = driver.Actor
    rows = []
    for repetition in range(1, 4):
        for original in public:
            workflow = deepcopy(workflows[original["brief"]])
            nodes = SchemaNodes(workflow["nodes"])
            workflow["nodes"] = nodes
            case = driver.fixture(original, repetition)
            # Only documented actual test_variables defaults; call values win.
            case["facts"]["variables"] = dict(deepcopy(workflow.get("test_variables", {})),
                                              **case["facts"]["variables"])
            driver.Actor = base_actor
            driver.Actor = actor_factory(driver, comparison, nodes)
            row = driver.execute(workflow, case, original, repetition, wr, scorer)
            row["workflow_version"] = None if original["brief"] == "A" else 14
            row["workflow_sha256"] = args.candidate_sha256 if original["brief"] == "A" else B_SHA
            row["arm"] = "candidate_A" if original["brief"] == "A" else "frozen_B14_control"
            # Runtime/placeholder exceptions are harness gaps, not proved policy failures.
            row["failure_domain"] = ("ADAPTER_UNSUPPORTED" if row["runner_error"] else
                                     "ledger_mismatch" if not row["original_score"]["pass"] else None)
            rows.append(row)
            if row["runner_error"] and "ADAPTER_UNSUPPORTED:" in row["runner_error"]:
                raise AdapterUnsupported(row["runner_error"])
    gaps = [r for r in rows if r["runner_error"]]
    return {
        "status": "RUNNER_GAPS" if gaps else "COMPLETED_LOCAL_CONDITIONAL_REPLAY",
        "scope": SCOPE, "cases": 13, "repetitions": 3, "executions": len(rows),
        "completed_executions": sum(r["execution_status"] == "completed" for r in rows),
        "conditional_kernel_ledger_passes": sum(r["conditional_kernel_ledger_pass"] for r in rows),
        "original_ledger_passes": sum(r["original_score"]["pass"] for r in rows),
        "A_candidate_passes": sum(r["conditional_kernel_ledger_pass"] for r in rows if r["brief"] == "A"),
        "B14_control_passes": sum(r["conditional_kernel_ledger_pass"] for r in rows if r["brief"] == "B"),
        "candidate_workflow": label(args.candidate_workflow), "candidate_sha256": args.candidate_sha256,
        "frozen_B14_sha256": B_SHA, "actual_schema_mappings": mappings,
        "validation_notes": validation_notes,
        "declared_test_variables": {b: w.get("test_variables", {}) for b, w in workflows.items()},
        "runner_errors": sorted({r["runner_error"] for r in gaps}), "results": rows,
        "network_denied": True, "network_calls": 0, "credentials_loaded": False,
        "extractor_executed": False, "llm_executed": False, "voice_executed": False,
        "freya_executed": False, "conversation_judge_executed": False,
        "independent_actor_repetitions": False,
        "limitations": ["Authored conditional extraction; deterministic repeats are not independent actor evidence.",
                        "Reuses existing API envelope, counters, post-hooks, mappings and explicit graph retries; unsupported tool retries fail closed.",
                        "An uninitialized optional placeholder, including reason, is a harness gap pending source/doc crosscheck; not a proved policy failure.",
                        "Parent owns completed generation and coverage validation; exact SHA and local validation do not establish generation provenance.",
                        "Exported Python executes locally, including any embedded deterministic student code; no separate inference service is invoked."],
    }


def output_paths(prefix):
    return [Path(str(prefix) + ".json"), Path(str(prefix) + ".txt")]


def write_report(prefix, report):
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    json_path, text_path = output_paths(prefix)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [report["status"], SCOPE,
             "No network, credentials, external inference, extractor, voice or conversation judge.",
             "Source hashes before/after: " + str(report.get("immutable_sources_unchanged")),
             "Candidate SHA256: " + str(report.get("candidate_sha256"))]
    if "executions" in report:
        lines.append(f"Completed {report['completed_executions']}/{report['executions']}; conditional ledger passes {report['conditional_kernel_ledger_passes']}/{report['executions']}; A {report['A_candidate_passes']}/30; B14 {report['B14_control_passes']}/9.")
    lines.extend(report.get("runner_errors", []))
    if report.get("runner_error"):
        lines.append(report["runner_error"])
    # Exclusive creation is deliberate: historical reports are never overwritten.
    with json_path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with text_path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-workflow", type=Path, required=True,
                        help="Parent-validated final A workflow; never select a pending run implicitly")
    parser.add_argument("--candidate-sha256", required=True, help="Exact final artifact SHA256 (64 hex digits)")
    parser.add_argument("--output-prefix", type=Path, required=True, help="Fresh authorized analysis prefix")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source-pins", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-fA-F]{64}", args.candidate_sha256):
        parser.error("--candidate-sha256 must be exact 64 hex digits")
    args.candidate_sha256 = args.candidate_sha256.lower()
    args.candidate_workflow = args.candidate_workflow.resolve()
    args.output_prefix = args.output_prefix.resolve()
    if args.output_prefix.parent != PREFIX.parent or not (args.output_prefix.name == PREFIX.name or
            args.output_prefix.name.startswith(PREFIX.name + ".")):
        parser.error("output must use analysis/final-sprint-public-replay-20261011[.NEWNAME]")
    if any(p.exists() for p in output_paths(args.output_prefix)):
        print(json.dumps({"status": "OUTPUT_EXISTS", "runner_error": "never_overwrite_historical_evidence"}))
        return 2
    paths = [ROOT / p for p in SOURCE_FILES] + [KIT / p for p in KIT_PINS]
    paths += [Path(__file__).resolve(), args.candidate_workflow]
    before, report = {}, {}
    try:
        before = snapshot(paths)
        if digest(args.candidate_workflow) != args.candidate_sha256:
            raise ValueError("CANDIDATE_SHA256_MISMATCH")
        if args.worker:
            if not args.source_pins:
                raise ValueError("WORKER_REQUIRES_OUTER_SOURCE_PINS")
            if json.loads(args.source_pins) != before:
                raise ValueError("SOURCE_PIN_CHANGED_BEFORE_WORKER")
            report = worker(args, before, paths)
        else:
            environment = {k: v for k, v in os.environ.items() if k.upper() in
                           {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "PYTHONUTF8"}}
            command = [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()),
                       "--candidate-workflow", str(args.candidate_workflow),
                       "--candidate-sha256", args.candidate_sha256,
                       "--output-prefix", str(args.output_prefix), "--worker",
                       "--source-pins", json.dumps(before, separators=(",", ":"))]
            try:
                completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                           text=True, encoding="utf-8", timeout=90)
            except subprocess.TimeoutExpired:
                report = {"status": "HARNESS_TIMEOUT", "runner_error": "outer_timeout_90_seconds"}
            else:
                if snapshot(paths) != before:
                    print(json.dumps({"status": "SOURCE_PIN_CHANGED_AFTER_WORKER"}))
                    return 2
                if completed.stdout.strip():
                    print(completed.stdout.strip())
                if not completed.returncode:
                    return 0
                if any(p.exists() for p in output_paths(args.output_prefix)):
                    return completed.returncode
                report = {"status": "RUNNER_ERROR", "runner_error": "worker_failed_without_report",
                          "worker_returncode": completed.returncode}
    except AdapterUnsupported as exc:
        report = {"status": "ADAPTER_UNSUPPORTED", "runner_error": str(exc)}
    except Exception as exc:
        report = {"status": "RUNNER_ERROR", "runner_error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
    after = {}
    try:
        after = snapshot(paths)
    except OSError:
        report["status"] = "SOURCE_PIN_CHANGED"
    if before and before != after:
        report["status"] = "SOURCE_PIN_CHANGED"
    report.update(scope=SCOPE, candidate_sha256=args.candidate_sha256,
                  source_hashes_before=before, source_hashes_after=after,
                  immutable_sources_unchanged=bool(before) and before == after)
    write_report(args.output_prefix, report)
    print(json.dumps({k: report[k] for k in ("status", "runner_error", "executions", "completed_executions",
                                            "conditional_kernel_ledger_passes", "A_candidate_passes", "B14_control_passes") if k in report}))
    return 0 if report["status"] == "COMPLETED_LOCAL_CONDITIONAL_REPLAY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
