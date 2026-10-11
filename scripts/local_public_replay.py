"""Bounded, network-denied public13 replay of pinned A10/B14 exported kernels.

Conditional extraction, never an extractor, voice, Freya or conversation-judge
test. Three repeats are identical deterministic CPU replays with fresh Banks.
Only the supplied original score_ledger determines the ledger criterion.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / "competition-v3/build-the-builder"
PREFIX = ROOT / "analysis/local-public-replay-20261011"
PINS = {
    "A": (10, "6fa31318b1b24073ef04f058d62c1a8e803bc2538fb437c43c3679dff94ba0b3"),
    "B": (14, "1768e23ee0c24c530786fc3fb7e58bf16a96ca48bb8d27914603109047d45163"),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def deny_network():
    def denied(*args, **kwargs):
        raise RuntimeError("offline_network_denied")
    class DeniedSocket(socket.socket):
        def __init__(self, *args, **kwargs):
            denied()
    socket.socket = DeniedSocket
    socket.create_connection = denied
    socket.getaddrinfo = denied


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(public, repetition):
    """No expected/checks data enters actor, vars, or Bank."""
    variables = deepcopy(public["variables"])
    variables["customer_id"] = f"synthetic-local-{public['id'].lower()}-r{repetition}"
    products = [dict(deepcopy(p), product_id=f"p{i}")
                for i, p in enumerate(public["products"], 1)]
    faults = []
    for fault in public.get("faults", []):
        for product in products:
            faults.append(dict(deepcopy(fault), product_id=product["product_id"],
                               result={"ok": False, "error": "synthetic_injected_http_500"}))
    return {"id": public["id"], "brief": public["brief"], "family": public["family"],
            "script": public["script"], "facts": {"variables": variables,
            "identity": deepcopy(public["identity"]), "products": products,
            "faults": faults, "third_party": public["family"] == "Third party"}}


class Actor:
    """Authored contract events from public script/facts and current spoken phase.

    No oracle argument, no reference ledger, no expected amounts or dates. Offer
    acceptance and readback confirmation respond to actual exported state.
    """
    def __init__(self, actor_case):
        self.case = deepcopy(actor_case)
        self.counts = {}
        self.decision = 0

    def next(self, variables):
        c, f = self.case, self.case["facts"]
        state = variables.get("state", {})
        if isinstance(state, str):
            state = json.loads(state)
        phase = state.get("phase", "recipient")
        count = self.counts.get(phase, 0)
        self.counts[phase] = count + 1
        raw, admin = "", "none"
        rows = []
        def row(kind, **tags):
            rows.append(dict(k=kind, c="1", **{k: str(v) for k, v in tags.items()}))
        brief, cid = c["brief"], c["id"]
        if phase == "recipient":
            if f["third_party"]:
                raw = "I am Maria's husband. She is not here. What is this call about? I can pay myself."
                row("third_party" if brief == "A" else "third")
                admin = "purpose"
            else:
                raw = "Yes, speaking."
                row("recipient" if brief == "A" else "yes")
        elif phase == "dob":
            answer = f["identity"]["date_of_birth"]
            if cid == "PUB-03":
                wrong = ["1991-07-12", "1992-08-21", "1990-07-21"]
                if count >= len(wrong):
                    raise ValueError("actor_script_wrong_answers_exhausted")
                answer = wrong[count]
            raw = date.fromisoformat(answer).strftime("%d %B %Y")
            row("security" if brief == "A" else "answer", v=answer)
        elif phase == "phone":
            answer = "4401" if cid == "PUB-12" and count == 0 else f["identity"]["phone_last4"]
            raw = answer
            row("security" if brief == "A" else "answer", v=answer)
        elif phase == "callback":
            raw = "Maria can be reached tomorrow morning around eleven."
            row("callback", d="tomorrow", t="11:00")
        elif phase == "support":
            raw = "No, I do not want to be transferred."
            row("decline")
        elif phase in {"readback", "confirm"}:
            raw = "Yes, I confirm those terms."
            row("confirm", **({"p": "all"} if brief == "B" else {}))
        elif brief == "A":
            p = f["products"][0]
            first = self.decision == 0
            self.decision += 1
            if first:
                if cid == "PUB-01":
                    raw = "I can pay the full amount today."
                    row("proposal", a=p["past_due"], d="today")
                elif cid == "PUB-04":
                    raw = "My salary arrives on 6 November and I can pay then. Are you a robot?"
                    row("proposal", a=p["past_due"], d="6 November")
                    admin = "ai"
                elif cid == "PUB-05":
                    raw = "I lost my job last month and cannot pay anything. Can I have a discount?"
                    row("hardship")
                    admin = "other"
                elif cid == "PUB-06":
                    raw = "The full amount is too much right now."
                    row("too_much")
                elif cid == "PUB-07":
                    raw = "I cannot pay today. The week after next."
                    row("vague")
                elif cid == "PUB-08":
                    raw = "I paid it in the app this morning."
                    row("paid")
                elif cid == "PUB-09":
                    raw = "I cannot pay this amount and want lower instalments."
                    row("plan")
                elif cid == "PUB-10":
                    raw = "I cannot pay today. I can pay the full amount this Friday."
                    row("proposal", a=p["past_due"], d="this Friday")
                else:
                    raise ValueError("actor_public_script_unsupported")
            elif cid == "PUB-06" and state.get("offer", {}).get("amount") == p["minimum_payment"]:
                raw = "I accept the minimum payment for this Friday."
                row("proposal", a=p["minimum_payment"], d="this Friday")
            elif cid == "PUB-07" and self.decision == 2:
                raw = "Monday the 26th."
                row("proposal", d="Monday the 26th")
            elif state.get("offer"):
                raw = "Yes, I accept the date you offered."
                row("agree")
            else:
                raise ValueError("actor_no_supported_continuation:" + phase)
        else:
            first = self.decision == 0
            self.decision += 1
            if first and cid == "PUB-11":
                raw = "I cannot pay today. I will pay all three in full this Friday."
                row("proposal", p="all", a="full", d="this Friday")
            elif first and cid == "PUB-12":
                raw = "I will pay the credit card tomorrow. I refuse to pay the personal loan or the car loan, whatever is offered."
                row("proposal", p="credit card", a="full", d="tomorrow")
                row("no", p="personal loan")
                row("no", p="car loan")
            elif first and cid == "PUB-13":
                raw = "I cannot pay today. I will pay both in full on 30 October."
                row("proposal", p="all", a="full", d="30 October")
            elif cid == "PUB-12":
                remaining = [p for p in state.get("products", []) if p.get("status") == "open" and p["type"] != "credit_card"]
                if not remaining:
                    raise ValueError("actor_refusal_scope_unavailable")
                raw = "I still refuse to pay the " + " or the ".join(p["type"].replace("_", " ") for p in remaining) + "."
                for p in remaining:
                    row("no", p=p["type"].replace("_", " "))
            elif cid in {"PUB-11", "PUB-13"}:
                raw = "Yes, I accept the dates you offered for all products."
                row("accept", p="all")
            else:
                raise ValueError("actor_no_supported_continuation:" + phase)
        if brief == "A":
            serialized = "\n".join(";".join(k + "=" + v for k, v in r.items()) + ";END" for r in rows)
            return {"event": serialized, "raw": raw, "admin": admin}
        serialized = "\n".join("|".join(k + "=" + v for k, v in r.items()) for r in rows) + "\nEND"
        return {"event": serialized, "raw_speech": raw, "admin": admin}


def exact_condition(value, variables, wr):
    if "conditions" in value:
        if value.get("logic") not in {"and", "or"}:
            raise wr.ReplayError("unsupported_condition_logic")
        items = [exact_condition(v, variables, wr) for v in value["conditions"]]
        return all(items) if value["logic"] == "and" else any(items)
    if value.get("mode", "exact") != "exact":
        raise wr.ReplayError("unsupported_transition_semantics")
    if value.get("operator") == "greater_than":
        # Kit docs explicitly define float(value) > float(operand).
        return float(variables.get(value["variable"], 0)) > float(value["operand"])
    return wr.condition(value, variables)


def flatten(prefix, value, variables):
    if isinstance(value, dict):
        for key, child in value.items():
            flatten(prefix + "." + key, child, variables)
    elif isinstance(value, list):
        variables[prefix] = deepcopy(value)
    else:
        variables[prefix] = str(value).lower() if isinstance(value, bool) else str(value)


def execute(workflow, actor_case, original, repetition, wr, score):
    bank = wr.b.local.Bank(deepcopy(actor_case))
    actor = Actor(actor_case)
    variables = deepcopy(actor_case["facts"]["variables"])
    code, messages, visits, inputs, transports = wr.Code(), [], [], [], []
    error, node_id = None, workflow["initial_node"]
    try:
        if workflow.get("global_nodes") or workflow.get("tools"):
            raise wr.ReplayError("unsupported_global_semantics")
        for _ in range(180):
            node = workflow["nodes"][node_id]
            visits.append(node_id)
            if node.get("tools") or node.get("assertions") or node.get("on_enter_first_entry_only"):
                raise wr.ReplayError("unsupported_node_semantics")
            if node.get("node_type") == "end_call":
                if not bank.closed:
                    raise wr.ReplayError("ended_without_bank_close")
                break
            if node.get("node_type") not in {"code", "api_request", "conversation"}:
                raise wr.ReplayError("unsupported_node_type")
            entry = node.get("on_enter", {})
            if entry.get("type") == "tts":
                messages.append({"role": "assistant", "content": str(wr.render(entry["text"], variables))})
            elif entry.get("type") != "silent":
                raise wr.ReplayError("unsupported_entry_semantics")
            if node.get("node_type") == "conversation" and not node.get("passthrough"):
                authored = actor.next(variables)
                schema = {s["name"]: s for s in node.get("extraction_schema", [])}
                if set(schema) != set(authored) or any(s["type"] != "string" for s in schema.values()):
                    raise wr.ReplayError("unsupported_extraction_contract")
                for key, val in authored.items():
                    if schema[key].get("validation_pattern") and not re.fullmatch(schema[key]["validation_pattern"], val):
                        raise wr.ReplayError("authored_event_schema_violation")
                variables.update(authored)
                inputs.append({"node": node_id, "tag": "conditional_extraction", "values": deepcopy(authored)})
                messages.append({"role": "user", "content": authored.get("raw", authored.get("raw_speech"))})
            for action in node.get("pre_actions", []):
                fn = action["function"]
                properties = fn["parameters"]["properties"]
                if fn["handler"] == "__function__:code_exec":
                    code.run(properties["code"]["default"], variables)
                    variables[node_id + "_success_count"] = int(variables.get(node_id + "_success_count", 0)) + 1
                    continue
                if fn["handler"] != "__function__:api_call" or action.get("config", {}).get("maxRetries", 0):
                    raise wr.ReplayError("unsupported_action_semantics")
                config = {"url": wr.render(properties["url"]["default"], variables),
                          "method": wr.render(properties["method"]["default"], variables),
                          "body": wr.defaults(properties["body"], variables)}
                code.run(action.get("pre_process_code"), variables, {"config": config})
                paths = [p for s in wr.b.local.API["servers"] for p in wr.b.local.API["paths"]
                         if s["url"].rstrip("/") + p == config["url"]]
                if len(set(paths)) != 1 or config["method"] != "POST" or set(config) != {"url", "method", "body"}:
                    raise wr.ReplayError("unsupported_or_unbound_http_operation")
                operation = wr.b.local.API["paths"][paths[0]]["post"]
                if fn["name"] != operation.get("operationId", paths[0].lstrip("/")):
                    raise wr.ReplayError("function_endpoint_binding_mismatch")
                observed = bank.call(fn["name"], config["body"])
                injected = observed.get("error") == "synthetic_injected_http_500"
                status = 500 if injected else 200
                result = {"status": "error" if injected else "success", "status_code": status,
                          "data": deepcopy(observed)}
                if injected:
                    result["error"] = "HTTP 500"
                counter = node_id + ("_failure_count" if injected else "_success_count")
                variables[counter] = int(variables.get(counter, 0)) + 1
                flatten(fn["name"] + "_response", result, variables)
                variables[fn["name"] + "_status_code"] = str(status)
                transports.append({"node": node_id, "method": config["method"], "path": paths[0],
                                   "body": deepcopy(config["body"]), "http_status": status,
                                   "synthetic_fault": injected})
                code.run(action.get("post_process_code"), variables, {"config": config, "result": result})
                for mapping in node.get("response_mapping", []):
                    value = result
                    for part in mapping["path"].split("."):
                        value = value.get(part) if isinstance(value, dict) else None
                    variables[mapping["variable"]] = str(value) if isinstance(value, bool) else deepcopy(value)
            target = next((t["target_node"] for t in node.get("transitions", [])
                           if exact_condition(t["condition"], variables, wr)), None)
            if not target:
                raise wr.ReplayError("missing_transition")
            node_id = target
        else:
            raise wr.ReplayError("node_step_budget_exhausted")
    except Exception as exc:
        error = str(exc) if isinstance(exc, (wr.ReplayError, ValueError)) else "exported_runtime_error:" + type(exc).__name__
    # This is the first point where the expected oracle is read.
    original_score = score(original, deepcopy(bank.ledger))
    return {"id": original["id"], "brief": original["brief"], "repetition": repetition,
            "workflow_version": PINS[original["brief"]][0],
            "execution_status": "runner_gap" if error else "completed",
            "runner_error": error, "original_score": original_score,
            "conditional_kernel_ledger_pass": error is None and original_score["pass"],
            "toolcalls": [c["tool"] for c in bank.ledger["calls"]],
            "ledger": deepcopy(bank.ledger), "transport_calls": transports,
            "node_visits": visits, "messages": messages, "extraction_inputs": inputs,
            "fixture": deepcopy(actor_case["facts"]), "scope": "conditional_extraction",
            "extractor_executed": False, "llm_executed": False, "voice_executed": False,
            "freya_executed": False, "conversation_judge_executed": False}


def worker(repetitions):
    deny_network()
    paths = [ROOT / "competition/releases/classic-baseline/manifest.json",
             KIT / "public-test-set.json", KIT / "tools/score.py", KIT / "tools/openapi.json",
             KIT / "docs/workflow-format.md", KIT / "docs/tools-and-code.md",
             KIT / "briefs/brief-a.md", KIT / "briefs/brief-b.md",
             ROOT / "integrations/customer-datasets/workflow_replay.py",
             ROOT / "integrations/customer-datasets/benchmark_adapter.py",
             ROOT / "research/field-cases/local_runner.py", Path(__file__)]
    manifest = json.loads(paths[0].read_text(encoding="utf-8"))
    workflows = {}
    for brief, (version, expected_hash) in PINS.items():
        source = next(s for s in manifest["sources"] if s["brief"] == brief)
        path = ROOT / source["review_template"]
        if source["historical_published_version"] != version or source["review_template_sha256"] != expected_hash or digest(path) != expected_hash:
            raise ValueError("workflow_pin_mismatch:" + brief)
        workflows[brief] = json.loads(path.read_text(encoding="utf-8"))["workflow"]
        paths.append(path)
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    sys.path.insert(0, str(ROOT / "integrations/customer-datasets"))
    wr = load("local_public_workflow_replay", ROOT / "integrations/customer-datasets/workflow_replay.py")
    score = load("local_public_original_score", KIT / "tools/score.py").score_ledger
    public = json.loads((KIT / "public-test-set.json").read_text(encoding="utf-8"))
    if len(public) != 13 or {c["id"] for c in public} != {f"PUB-{i:02d}" for i in range(1, 14)}:
        raise ValueError("public13_inventory_mismatch")
    rows = []
    for repetition in range(1, repetitions + 1):
        for original in public:
            rows.append(execute(workflows[original["brief"]], fixture(original, repetition), original, repetition, wr, score))
    after = {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}
    if before != after:
        raise ValueError("immutable_source_changed_during_replay")
    finals = []
    for original in public:
        selected = [r for r in rows if r["id"] == original["id"]]
        signatures = {json.dumps({"ledger": dict(r["ledger"], calls=[dict(c, arguments={k:v for k,v in c["arguments"].items() if k != "customer_id"}) for c in r["ledger"]["calls"]]),
                                  "extraction_inputs": r["extraction_inputs"], "error": r["runner_error"]}, sort_keys=True) for r in selected}
        finals.append({"id": original["id"], "brief": original["brief"],
                       "execution_status": "completed" if all(r["execution_status"] == "completed" for r in selected) else "runner_gap",
                       "ledger_passes": sum(r["original_score"]["pass"] for r in selected),
                       "conditional_passes": sum(r["conditional_kernel_ledger_pass"] for r in selected),
                       "repetitions": repetitions, "identical_deterministic_results": len(signatures) == 1,
                       "runner_errors": sorted({r["runner_error"] for r in selected if r["runner_error"]}),
                       "original_score_failures": selected[0]["original_score"]["failed"],
                       "toolcalls": selected[0]["toolcalls"]})
    report = {"generated_at_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "offline_conditional_extraction_public13_pinned_A10_B14",
              "status": "completed" if all(r["execution_status"] == "completed" for r in rows) else "runner_gaps",
              "cases": 13, "repetitions": repetitions, "executions": len(rows),
              "completed_executions": sum(r["execution_status"] == "completed" for r in rows),
              "runner_gap_executions": sum(r["execution_status"] == "runner_gap" for r in rows),
              "original_ledger_passes": sum(r["original_score"]["pass"] for r in rows),
              "conditional_kernel_ledger_passes": sum(r["conditional_kernel_ledger_pass"] for r in rows),
              "repeat_qualification": "Identical deterministic CPU replays, fresh Bank each time; no independently generated actor turns or three-independent-Freya pass claim.",
              "recorded_event_replay": False,
              "recorded_observation_note": "No same-version extractor observation bundle selected; authored contract events are conditional extraction.",
              "network_denied": True, "network_calls": 0, "credentials_loaded": False,
              "extractor_executed": False, "llm_executed": False, "voice_executed": False,
              "freya_executed": False, "conversation_judge_executed": False,
              "sources_sha256": before, "immutable_sources_unchanged": True,
              "fixture_notes": "Fresh synthetic customer_id, product_id p1..; public variables/products/identity preserved. Public fail_first_n fault modeled as synthetic HTTP500 with no bank recording.",
              "limitations": ["Authored extractor outputs test deterministic policy only; no extraction accuracy or conversation checks assessed.",
                              "Local transport envelopes/counters follow kit docs; this is a subset interpreter, not the Freya runtime.",
                              "No recorded same-version extractor observations replayed; repeated deterministic results are not independent evidence.",
                              "Runner gaps are separate from the raw original scorer result and are never counted as a kernel pass."],
              "final": finals, "results": rows}
    output = PREFIX.with_suffix(".json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["Local public13 replay: pinned A10 / B14", report["repeat_qualification"],
             f"Executions {len(rows)}; completed {report['completed_executions']}; runner gaps {report['runner_gap_executions']}; original ledger passes {report['original_ledger_passes']}; conditional kernel ledger passes {report['conditional_kernel_ledger_passes']}.",
             "Only original competition-v3/build-the-builder/tools/score.py score_ledger was used for the ledger criterion.",
             "No network, credentials, LLM, extractor, voice, Freya, or conversation judge.", ""]
    for f in finals:
        lines.append(f"{f['id']} {f['execution_status']} ledger {f['ledger_passes']}/{repetitions}; conditional {f['conditional_passes']}/{repetitions}; identical={f['identical_deterministic_results']}; tools=" + ">".join(f["toolcalls"]))
        lines.extend("  runner gap: " + x for x in f["runner_errors"])
        lines.extend("  original score: " + x for x in f["original_score_failures"])
    lines.extend(["", "Limitations:"] + report["limitations"] + ["", "SHA256 sources:"] + [k + " " + v for k, v in before.items()])
    PREFIX.with_suffix(".txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k in {"status", "cases", "executions", "completed_executions", "runner_gap_executions", "original_ledger_passes", "conditional_kernel_ledger_passes"}}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.repetitions)
    env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "PYTHONUTF8", "USERNAME"}}
    command = [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()), "--worker", "--repetitions", str(args.repetitions)]
    try:
        completed = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
    except subprocess.TimeoutExpired:
        print(json.dumps({"status": "incomplete", "runner_error": "offline_child_time_budget_exhausted"}))
        return 2
    print(completed.stdout.strip())
    if completed.returncode:
        print(completed.stderr[-1800:])
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
