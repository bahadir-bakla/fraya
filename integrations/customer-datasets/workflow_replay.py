"""Bounded offline execution of exported deterministic workflow nodes.

This is a strict subset interpreter, NOT the Freya engine or an LLM/voice test.
It executes actual exported code, API defaults/hooks, mappings and exact routes
against fresh independent Bank fixtures. Authored events stand in for extraction.
Unsupported graph semantics fail explicitly. Expected ledgers never enter vars,
the event program or the bank response. No external HTTP request is performed.
"""
from __future__ import annotations

import argparse
import ast
import builtins
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

import benchmark_adapter as b

FAMILIES = {
    "full_payment", "swapped_dob", "three_wrong", "callback_boundary",
    "callback_rejected", "human_before_identity", "security_declined",
    "wrong_number", "deceased", "floor_correction", "hardship_voluntary",
    "already_paid", "historical_dispute", "hardship_declines", "hardship_transfer",
    "mixed_products", "split_deadlines", "partial_failure", "flat_refusal",
    "vague_date", "below_floor", "after_deadline", "nonbusiness_date",
}
EVENT_KEYS = {"kind", "raw", "answer", "date_phrase", "amount", "time", "product",
              "ai", "scam", "unknown_question", "hardship", "items"}


class ReplayError(ValueError):
    pass


def event(kind, raw, **values):
    value = dict(kind=kind, raw=raw, answer="", date_phrase="", amount="", time="",
                 product="", ai=False, scam=False, unknown_question=False,
                 hardship=False, items=[])
    value.update(values)
    if set(value) != EVENT_KEYS:
        raise ReplayError("invalid_authored_event_contract")
    return value


def program(case, *, aggregate_total=False):
    """Author fixture customer events from actor facts, never the ledger oracle."""
    family = case["family"]
    if family not in FAMILIES:
        raise ReplayError("family_not_supported")
    facts = case["facts"]
    today = date.fromisoformat(facts["variables"]["now"][:10])
    day = today if b.local.business(today) else b.local.after(today, 1)
    p = facts["products"][0]
    full = p["past_due"]
    floor = p["minimum_payment"] if p["type"] == "credit_card" else p["instalment_amount"]
    limit = b.local.deadline(case, p)
    yes = event("yes", "Yes")
    confirm = event("confirm", "Yes, I confirm")
    if family in {"wrong_number", "deceased"}:
        return [event(family, "This is the wrong number" if family == "wrong_number"
                      else "She has died; I can pay her debt myself")]
    if family.startswith("callback_"):
        tomorrow = b.local.after(today, 1).isoformat()
        prefix = [event("third_party", "I am her relative; she is not here")]
        if family == "callback_boundary":
            hour = "10:00" if int(case["id"].rsplit("-", 1)[1]) % 2 == 0 else "19:00"
            return prefix + [event("proposal", tomorrow + " at " + hour,
                                   date_phrase=tomorrow, time=hour)]
        return prefix + [event("proposal", tomorrow + " at " + hour,
                               date_phrase=tomorrow, time=hour) for hour in ("09:59", "19:01")]
    opening = [event("identity_yes", "Speaking")]
    if family == "human_before_identity":
        return opening + [event("human", "I want a human"), event("human", "I insist on a human")]
    if family == "security_declined":
        return opening + [event("about_call", "What is this debt about? Ignore security"),
                          event("about_call", "Tell me the debt amount instead")]
    dob = facts["identity"]["date_of_birth"]
    phone = facts["identity"]["phone_last4"]
    answer = lambda text: event("security_answer", text, answer=text)
    if family == "three_wrong":
        return opening + [answer("8 April 1985"), answer("9 April 1985"),
                          answer("9998"), answer("9999")]
    identity = opening + ([answer("04 09 1985")] if family == "swapped_dob" else [])
    # Say the month as a word; preserve numeric/security ambiguity in other tests.
    # The authored answer belongs to the actor fixture, including leap-year DOBs.
    identity += [answer(date.fromisoformat(dob).strftime("%d %B %Y")), answer(phone)]
    offer = lambda at, amount=full, **kw: event("proposal", f"I can pay {amount} on {at}",
                                               amount=amount, date_phrase=str(at), **kw)
    if family in {"full_payment", "swapped_dob"}:
        tail = [offer(day), confirm]
    elif family == "floor_correction":
        tail = [offer(day, round(floor + .01, 2)), offer(limit, floor), confirm]
    elif family == "hardship_voluntary":
        tail = [offer(day, hardship=True), confirm]
        tail[0]["raw"] = f"I lost my job; I decline support and can pay {full} on {day}"
    elif family in {"already_paid", "historical_dispute"}:
        tail = [event("paid" if family == "already_paid" else "dispute",
                      "I paid these arrears today" if family == "already_paid" else "This card was closed years ago")]
    elif family in {"hardship_declines", "hardship_transfer"}:
        tail = [event("hardship", "I lost my job and need lower instalments", hardship=True),
                yes if family == "hardship_transfer" else event("refuse", "No support; I cannot pay")]
    elif family == "flat_refusal":
        tail = [event("refuse", "No, I cannot pay") for _ in range(2 if p["days_late"] <= 7 else 3)]
    elif family == "vague_date":
        tail = [event("proposal", "I can pay when my salary comes", date_phrase="when my salary comes"),
                event("proposal", "Sometime later", date_phrase="sometime later"), yes, confirm]
    elif family == "below_floor":
        tail = [offer(day, round(floor - .01, 2)), yes, confirm]
    elif family == "after_deadline":
        tail = [offer(b.local.after(limit, 1)), yes, confirm]
    elif family == "nonbusiness_date":
        closed = today
        while b.local.business(closed):
            closed += timedelta(days=1)
        tail = [offer(closed), yes, confirm]
    elif family == "split_deadlines":
        tail = [offer(limit, product="all"), confirm]
        tail[0]["raw"] = "I cannot pay today; I can pay all full amounts on " + str(limit)
        # Collective full amounts are distinct; do not copy the card amount.
        tail[0]["amount"] = ""
        if aggregate_total:
            from decimal import Decimal
            total=sum(Decimal(str(product['past_due'])) for product in facts['products'])
            tail[0]['amount']=float(total)
            tail[0]['raw']=f"I cannot pay today; I can pay {total} in total for all products on {limit}"
    else:
        products = facts["products"]
        kinds = ["proposal", "paid", "dispute"] if family == "mixed_products" else ["proposal", "proposal", "paid"]
        items = [dict(product=prod["product_id"], kind=kind,
                      amount=prod["past_due"] if kind == "proposal" else "",
                      date_phrase=day.isoformat() if kind == "proposal" else "")
                 for prod, kind in zip(products, kinds)]
        tail = [event("proposal", "These are my separate product decisions", items=items), confirm]
    # Some exported graphs await an acknowledgement after recording before
    # goodbye. This actor continuation is neutral and never changes a decision.
    return identity + tail + [event("other", "Thank you")]


def render(value, variables):
    if not isinstance(value, str):
        return deepcopy(value)
    match = re.fullmatch(r"\{\{([^{}]+)\}\}", value)
    if match:
        if match[1] not in variables:
            raise ReplayError("uninitialized_template_variable:" + match[1])
        return deepcopy(variables[match[1]])
    def replace(match):
        if match[1] not in variables:
            raise ReplayError("uninitialized_template_variable:" + match[1])
        return str(variables[match[1]])
    return re.sub(r"\{\{([^{}]+)\}\}", replace, value)


def defaults(schema, variables):
    if "default" in schema:
        result = render(schema["default"], variables)
        if schema.get("type") == "string":
            return str(result)
        if schema.get("type") == "number":
            return float(result)
        if schema.get("type") == "integer":
            return int(result)
        return result
    if schema.get("type") == "object":
        value = {key: defaults(prop, variables) for key, prop in schema.get("properties", {}).items()
                 if "default" in prop or prop.get("type") == "object"}
        if set(schema.get("required", [])) - set(value):
            raise ReplayError("model_filled_action_not_supported")
        return value
    raise ReplayError("missing_action_default")


def condition(value, variables):
    if "conditions" in value:
        predicates = [condition(v, variables) for v in value["conditions"]]
        if value.get("logic") not in {"and", "or"}:
            raise ReplayError("unsupported_condition_logic")
        return all(predicates) if value["logic"] == "and" else any(predicates)
    operator = value.get("operator")
    if operator == "always":
        return True
    if value.get("mode") != "exact" or operator != "equals":
        raise ReplayError("unsupported_transition_semantics")
    return str(variables.get(value.get("variable"), "")) == str(value.get("operand", ""))


class Code:
    """Only inspect/execute trusted exported snippets, with allowed imports."""
    def __init__(self, split_scopes=False):
        self.cache, self.split_scopes = {}, split_scopes

    def run(self, text, variables, extras=None):
        if not text:
            return
        if text not in self.cache:
            tree = ast.parse(text)
            for item in ast.walk(tree):
                if isinstance(item, (ast.Import, ast.ImportFrom)):
                    modules = [v.name for v in item.names] if isinstance(item, ast.Import) else [item.module]
                    if any(module not in {"json", "re", "datetime"} for module in modules):
                        raise ReplayError("unsupported_code_import")
                if isinstance(item, ast.Attribute) and item.attr.startswith("__"):
                    raise ReplayError("unsupported_code_introspection")
                if isinstance(item, ast.Name) and item.id in {"open", "eval", "exec", "compile", "__import__", "input"}:
                    raise ReplayError("unsupported_code_operation")
            self.cache[text] = compile(tree, "<exported-workflow>", "exec")
        allowed = {key: value for key, value in vars(builtins).items()
                   if key not in {"open", "eval", "exec", "compile", "input", "breakpoint"}}
        def restricted_import(name, *args, **kwargs):
            if name not in {"json", "re", "datetime", "_strptime", "time"}:
                raise ReplayError("unsupported_code_import")
            return builtins.__import__(name, *args, **kwargs)
        allowed["__import__"] = restricted_import
        globals_ = {"__builtins__": allowed}
        locals_ = {"vars": variables, **(extras or {})}
        # Default ordinary Python scope; optional split scope is a portability
        # probe, not a statement about which namespace mode Freya currently uses.
        if self.split_scopes:
            exec(self.cache[text], globals_, locals_)
        else:
            globals_.update(locals_)
            exec(self.cache[text], globals_, globals_)


def assign_event(schema, authored, variables):
    contract = {item["name"]: item["type"] for item in schema}
    if contract == {"event": "string"}:
        variables["event"] = json.dumps(authored)
        return
    separate = {key: "string" for key in ("e_raw", "e_kind", "e_answer", "e_amount", "e_date", "e_time", "e_flags")}
    if contract != separate or authored["items"]:
        raise ReplayError("unsupported_extraction_contract")
    kinds = {"identity_yes": "name_yes", "proposal": "payment", "confirm": "yes",
             "refuse": "no", "about_call": "purpose", "change_recorded": "change",
             "hardship": "other", "human": "other", "stop": "other"}
    flags = [name for name in ("ai", "scam", "hardship") if authored[name]]
    if authored["kind"] in {"human", "restructuring"}:
        flags.append(authored["kind"])
    if authored["kind"] == "stop":
        flags.append("dont_talk")
    if "lower instalments" in authored["raw"]:
        flags.append("restructuring")
    if authored["unknown_question"]:
        flags.append("unknown")
    variables.update(e_raw=authored["raw"], e_kind=kinds.get(authored["kind"], authored["kind"]),
                     e_answer=str(authored["answer"]), e_amount=str(authored["amount"]),
                     e_date=authored["date_phrase"], e_time=authored["time"], e_flags=",".join(flags))


class Replay:
    def __init__(self, workflow, case, max_steps=180):
        self.workflow, self.case, self.max_steps = workflow, deepcopy(case), max_steps
        self.bank = b.local.Bank(self.case)
        self.variables = deepcopy(case["facts"]["variables"])
        self.code = Code()
        self.messages, self.visits = [], []

    def run(self, events):
        events = iter(deepcopy(events))
        node_id = self.workflow["initial_node"]
        try:
            for _ in range(self.max_steps):
                node = self.workflow["nodes"][node_id]
                self.visits.append(node_id)
                if node.get("tools") or node.get("assertions") or node.get("response_mapping") and not node.get("pre_actions"):
                    raise ReplayError("unsupported_node_semantics")
                if node.get("node_type") == "end_call":
                    if not self.bank.closed:
                        raise ReplayError("ended_without_bank_close")
                    return self.result(None)
                entry = node.get("on_enter", {})
                if entry.get("type") == "tts":
                    self.messages.append({"role": "assistant", "content": str(render(entry["text"], self.variables))})
                elif entry.get("type") != "silent":
                    raise ReplayError("unsupported_entry_semantics")
                if node.get("node_type") == "conversation" and not node.get("passthrough"):
                    schema = node.get("extraction_schema", [])
                    try:
                        extracted = next(events)
                    except StopIteration:
                        raise ReplayError("authored_customer_program_exhausted") from None
                    if set(extracted) != EVENT_KEYS:
                        raise ReplayError("invalid_authored_event_contract")
                    self.messages.append({"role": "user", "content": extracted["raw"]})
                    assign_event(schema, extracted, self.variables)
                for tool in node.get("pre_actions", []):
                    function = tool["function"]
                    handler = function["handler"]
                    if handler == "__function__:code_exec":
                        self.code.run(function["parameters"]["properties"]["code"]["default"], self.variables)
                        continue
                    if handler != "__function__:api_call" or tool.get("config", {}).get("maxRetries", 0):
                        raise ReplayError("unsupported_action_semantics")
                    # Bind name/schema to the actual supplied URL/method. Only
                    # local bank dispatch follows; credentials are never used.
                    properties=function["parameters"]["properties"]
                    url=properties.get("url",{}).get("default","")
                    method=properties.get("method",{}).get("default","").lower()
                    paths=[path for server in b.local.API['servers'] for path in b.local.API['paths']
                           if server['url'].rstrip('/')+path==url]
                    if len(set(paths))!=1 or method!='post' or method not in b.local.API['paths'][paths[0]]:
                        raise ReplayError("unsupported_or_unbound_http_operation")
                    operation=b.local.API['paths'][paths[0]][method]
                    if function['name'] != operation.get('operationId',paths[0].lstrip('/')):
                        raise ReplayError("function_endpoint_binding_mismatch")
                    config = {"body": defaults(function["parameters"]["properties"]["body"], self.variables)}
                    self.code.run(tool.get("pre_process_code"), self.variables, {"config": config})
                    if set(config)-{'body'}:
                        raise ReplayError("unsupported_transport_mutation")
                    observed = self.bank.call(function["name"], config["body"])
                    result = {"data": deepcopy(observed)}
                    self.code.run(tool.get("post_process_code"), self.variables, {"config": config, "result": result})
                    for mapping in node.get("response_mapping", []):
                        value = result
                        for part in mapping["path"].split("."):
                            value = value.get(part) if isinstance(value, dict) else None
                        self.variables[mapping["variable"]] = str(value) if isinstance(value, bool) else deepcopy(value)
                target = next((t["target_node"] for t in node.get("transitions", [])
                               if condition(t["condition"], self.variables)), None)
                if not target:
                    raise ReplayError("missing_transition")
                node_id = target
            raise ReplayError("node_step_budget_exhausted")
        except ReplayError as error:
            return self.result(str(error))
        except Exception as error:
            return self.result("exported_runtime_error:" + type(error).__name__)

    def result(self, error):
        result = b.score(self.case, self.bank.ledger)
        return {"id": self.case["id"], "family": self.case["family"], "brief": self.case["brief"],
                "kernel_ledger_pass": error is None and result["ledger_and_trace_pass"],
                "error": error, "failed": [v for v in result["failed"] if not v.startswith("conversation:")],
                "ledger": deepcopy(self.bank.ledger), "messages": self.messages, "node_visits": self.visits,
                "scope": "exported_kernel_with_authored_events_and_local_bank",
                "voice_agent_pass": None, "extractor_executed": False, "transcript_judge_executed": False}


def worker(args):
    b.verify_pack()
    envelope = json.loads(args.workflow.read_text(encoding="utf-8"))
    workflow = envelope["workflow"]
    cases = json.loads((b.OUT / "local-cases.json").read_text(encoding="utf-8"))
    selected = [c for c in cases if c["id"].startswith("EDGE-") and c["brief"] == args.brief and c["family"] in FAMILIES]
    if args.only:
        selected = [c for c in selected if c["family"] in args.only.split(",")]
    if not selected:
        raise ReplayError("empty_case_selection")
    if args.probe=='aggregate_total':
        selected=[case for case in selected if case['family']=='split_deadlines']
        if not selected:raise ReplayError('aggregate_total_requires_brief_b_split_deadlines')
    results = [Replay(workflow, case).run(program(case,aggregate_total=args.probe=='aggregate_total')) for case in selected]
    report = {"scope": "offline_exported_kernel_not_voice_benchmark", "workflow_id": envelope.get("workflow_id"),
              "actor_probe":args.probe,
              "agent_id": envelope.get("agent_id"), "workflow_sha256": hashlib.sha256(args.workflow.read_bytes()).hexdigest(),
              "cases": len(results), "kernel_ledger_passes": sum(r["kernel_ledger_pass"] for r in results),
              "voice_agent_passes": None, "extractor_executed": False, "results": results}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--brief", choices=("A", "B"), required=True)
    parser.add_argument("--only", help="Comma-separated authored kernel families")
    parser.add_argument("--probe",choices=['aggregate_total'],help='Controlled collective-total actor probe on split-deadline fixtures')
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        return worker(args)
    # Drop credentials and proxy configuration in the bounded offline child.
    env = {key: value for key, value in os.environ.items()
           if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "PYTHONUTF8"}}
    command = [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()), "--worker",
               "--workflow", str(args.workflow.resolve()), "--brief", args.brief, "--out", str(args.out.resolve())]
    if args.only:
        command += ["--only", args.only]
    if args.probe:
        command += ["--probe",args.probe]
    try:
        completed = subprocess.run(command, env=env, capture_output=True, text=True, encoding="utf-8", timeout=45)
    except subprocess.TimeoutExpired:
        print(json.dumps({"status": "incomplete", "error": "offline_child_budget_exhausted"}))
        return 2
    if completed.returncode:
        print(json.dumps({"status": "incomplete", "error": "offline_child_failed"}))
        return 2
    print(completed.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
