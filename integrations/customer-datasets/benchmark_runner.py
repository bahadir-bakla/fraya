"""Plan hosted PUB regressions; execution always needs an explicit variant selection.

No workflow is created, changed or published. Actor construction and ledger/trace/
judge scoring belong to benchmark_adapter. Evidence is stored locally, never used
as a substitute for a real simulation. The default is a keyless, read-only plan.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from types import ModuleType, SimpleNamespace
import urllib.error
import urllib.parse
import urllib.request
import uuid
from read_only_retry import open_with_read_only_retry

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PACK = ROOT / "research/customer-benchmark/hosted-cases.json"
DEFAULT_OUTPUT = ROOT / "local-runs/customer-benchmark"
AGENT_MODEL = {"provider": "experimental-5", "model": "experimental-5"}
CALL_VARIABLES = {"customer_id", "first_name", "last_name", "title", "now"}
INACTIVE = {"completed", "failed", "canceled", "cancelled"}
TERMINAL = {"completed", "failed", "paused"}
WORKSPACE_PAGE_SIZE = 25
RUNNER_SOURCE_PIN=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest()


class RunnerError(Exception):
    """Only fixed, non-sensitive error codes reach persisted logs or stdout."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def resource_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", value):
        raise RunnerError("invalid_resource_id")
    return value


class Budget:
    def __init__(self, seconds=1200, clock=time.monotonic, sleep=time.sleep):
        if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
            raise RunnerError("invalid_budget")
        self.clock, self.sleep = clock, sleep
        self.deadline = clock() + seconds

    def remaining(self):
        left = self.deadline - self.clock()
        if left <= 0:
            raise RunnerError("total_budget_exhausted")
        return left

    def wait(self):
        self.sleep(min(10, self.remaining()))
        self.remaining()


class OfficialClient:
    """Use isolated copies of the supplied clients with deadline-capped sockets.

    Isolation avoids the supplied global workspace cache crossing origins/keys.
    In particular this never calls freya.run_simulation's unbounded wait loop.
    """
    def __init__(self, kit, budget):
        self.budget = budget
        self.freya = self._load(Path(kit) / "freya.py")
        self.bank_client = self._load(Path(kit) / "tools/score.py")
        self.AGENT_LLM = self.freya.AGENT_LLM
        self.SIM_LLM = self.freya.SIM_LLM
        self.URL, self.HOST = self.freya.URL, self.bank_client.HOST

    def _load(self, path):
        module = ModuleType("_benchmark_client_" + uuid.uuid4().hex)
        module.__file__ = str(path)
        exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), module.__dict__)

        def urlopen(request, timeout=30):
            try:
                return open_with_read_only_retry(request, opener=urllib.request.urlopen,
                                                 budget=self.budget, timeout=timeout)
            except urllib.error.HTTPError as error:
                # Do not let the supplied client's JSON decoder hide a plain
                # transport outage, or expose an error body containing secrets.
                raise RunnerError('http_response_error_'+str(error.code)) from None

        # Replace this private module's urllib reference, not process-global urllib.
        module.urllib = SimpleNamespace(
            request=SimpleNamespace(Request=urllib.request.Request, urlopen=urlopen),
            error=urllib.error, parse=urllib.parse)
        return module

    def workspace_id(self):
        return self.freya.workspace_id()

    def api(self, method, path, body=None, **params):
        return self.freya.api(method, path, body, **params)

    def bank(self, path, body=None):
        return self.bank_client.http(path, body)


def scrub(value, secrets=()):
    """Retain observed evidence, redact credentials including JSON system events."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            sensitive = normalized in {"headers", "header", "authorization", "xteamkey", "token"} or any(
                word in normalized for word in ("apikey", "password", "credential", "accesstoken", "refreshtoken", "secret"))
            result[key] = "[REDACTED]" if sensitive else scrub(item, secrets)
        return result
    if isinstance(value, list):
        return [scrub(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        if value.lstrip().startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                pass
            else:
                return json.dumps(scrub(parsed, secrets), ensure_ascii=False)
        return value
    return value


def write_json(path, value, secrets):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(scrub(value, secrets), ensure_ascii=False,
                                    indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def select_rows(rows, adapter, brief=None, only=None):
    try:
        adapter.validate_hosted(rows)
    except Exception:
        raise RunnerError("invalid_hosted_pack") from None
    indexed = {row["variant_id"]: row for row in rows}
    if len(indexed) != len(rows):
        raise RunnerError("duplicate_variant_id")
    if only is not None:
        chosen = only.split(",") if isinstance(only, str) else list(only)
        if not chosen or any(not isinstance(v, str) or not v or v != v.strip() for v in chosen):
            raise RunnerError("invalid_variant_selection")
        if len(chosen) != len(set(chosen)):
            raise RunnerError("duplicate_variant_selection")
        if any(v not in indexed for v in chosen):
            raise RunnerError("unknown_variant_selection")
        selected = [indexed[v] for v in chosen]
        if brief and any(row["brief"] != brief for row in selected):
            raise RunnerError("variant_brief_mismatch")
    else:
        selected = [row for row in rows if not brief or row["brief"] == brief]
    if not selected:
        raise RunnerError("empty_variant_selection")
    return copy.deepcopy(selected)


def settings(reps, batch_size):
    if type(reps) is not int or reps < 3:
        raise RunnerError("at_least_three_repetitions_required")
    if type(batch_size) is not int or not 1 <= batch_size <= 5:
        raise RunnerError("batch_size_must_be_one_to_five")


def evaluation_scope(rows):
    return rows[0].get("evaluation_scope", "hosted_public_regression_only_not_hidden_case_coverage")


def plan(rows, adapter, *, brief=None, only=None, reps=3, batch_size=5, parallel_reps=False):
    settings(reps, batch_size)
    selected = select_rows(rows, adapter, brief, only)
    return {"mode": "plan", "execution_status": "not_executed", "network_calls": 0,
            "scope": evaluation_scope(selected),
            "variants": [{k: row[k] for k in ("id", "variant_id", "brief", "style", "delivery_profile")} for row in selected],
            "repetitions": reps, "all_repetitions_must_pass": True,
            "sessions_required": len(selected) * reps,
            "batches_required": math.ceil(len(selected) * reps / batch_size) if parallel_reps else math.ceil(len(selected) / batch_size) * reps,
            "max_personas_per_batch": batch_size, "total_budget_seconds": 1200,
            "execution_requires": ["--execute", "--agent-id", "--brief", "--only variant_ids",
                                   "verified source/pack hashes", "idle workspace", "credentials"]}


def items(response, key):
    value = response
    if isinstance(response, dict):
        value = response.get(key, response.get("items"))
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise RunnerError("malformed_list_response")
    return value


def receipt_matches(observed, bank):
    if isinstance(bank,dict):
        return isinstance(observed,dict) and all(key in observed and receipt_matches(observed[key],value) for key,value in bank.items())
    if isinstance(bank,list):
        return isinstance(observed,list) and len(observed)==len(bank) and all(receipt_matches(a,v) for a,v in zip(observed,bank))
    if isinstance(bank,bool) or isinstance(observed,bool):
        return type(observed) is bool and type(bank) is bool and observed==bank
    if isinstance(bank,(int,float)):
        return isinstance(observed,(int,float)) and observed==bank
    return type(observed) is type(bank) and observed==bank


def reconcile_call(call, ledger, job, agent_id, workspace_id, api):
    """Join observed HTTP start/complete events to actual bank calls, in order."""
    if call.get('assistantId',call.get('agentId'))!=agent_id or call.get('workspaceId')!=workspace_id:
        raise RunnerError('call_binding_mismatch')
    for key in ('customerVariables','variables'):
        if isinstance(call.get(key),dict) and 'customer_id' in call[key] and call[key]['customer_id']!=job['customer_id']:
            raise RunnerError('call_session_binding_mismatch')
    operations={server['url'].rstrip('/')+path: (method.upper(),operation.get('operationId',path.lstrip('/')))
                for server in api['servers'] for path,methods in api['paths'].items()
                for method,operation in methods.items() if method=='post'}
    pairs=[];pending=None;assistant_seen=False
    for message in call['messages']:
        if message.get('role')=='assistant' and str(message.get('message',message.get('content',''))).strip():assistant_seen=True
        if message.get('role')!='system':continue
        try:ev=json.loads(message.get('message',''))
        except (TypeError,ValueError):continue
        if not isinstance(ev,dict) or ev.get('function')!='api_call':continue
        if ev.get('event')=='function_call_start':
            args=ev.get('args',{})
            operation=operations.get(args.get('url'))
            if pending or not operation or args.get('method','').upper()!=operation[0] or not isinstance(args.get('body'),dict):
                raise RunnerError('unbound_call_http_evidence')
            body=copy.deepcopy(args['body'])
            if body.pop('customer_id',None)!=job['customer_id']:
                raise RunnerError('call_session_binding_mismatch')
            pending=(operation[1],body)
        elif ev.get('event')=='function_call_complete':
            if pending is None or not isinstance(ev.get('result',{}).get('data'),dict):
                raise RunnerError('unpaired_call_http_evidence')
            pairs.append({'tool':pending[0],'args':pending[1],'result':ev['result']['data']})
            pending=None
    if pending or not assistant_seen or len(pairs)!=len(ledger.get('calls',[])):
        raise RunnerError('call_ledger_evidence_mismatch')
    for observed,bank_call in zip(pairs,ledger['calls']):
        args=copy.deepcopy(bank_call.get('args',bank_call.get('arguments',{})));args.pop('customer_id',None)
        if observed['tool']!=bank_call.get('tool') or observed['args']!=args or not receipt_matches(observed['result'],bank_call.get('result')):
            raise RunnerError('call_ledger_evidence_mismatch')
    return {'call_session_binding':'observed_http_customer_id','bank_calls_reconciled':len(pairs),
            'assistant_id':call.get('assistantId',call.get('agentId')),
            'workflow_id':call.get('assistantWorkflowId'),'published_version_id':call.get('entityVersionId'),
            'published_version_number':call.get('entityVersionNumber')}


def origin(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RunnerError("invalid_api_origin")
    return parsed.scheme + "://" + parsed.netloc


def summarize(selected, jobs, reps, status):
    final = []
    for row in selected:
        observed = [job for job in jobs if job["variant_id"] == row["variant_id"] and job.get("result")]
        passes = sum(job["result"].get("pass") is True for job in observed)
        final.append({"id": row["id"], "variant_id": row["variant_id"],
                      "completed_repetitions": len(observed), "passes": passes, "required_repetitions": reps,
                      "failure_observed":any(job['result'].get('pass') is False for job in observed),
                      "pending_repetitions":max(0,reps-len(observed)),
                      "pass": len(observed) == reps and passes == reps and reps >= 3})
    return {"execution_status": status, "scope": evaluation_scope(selected),
            "passed": sum(row["pass"] for row in final), "total": len(final), "final": final,
            "pass": status == "completed" and bool(final) and all(row["pass"] for row in final)}


def execute(rows, adapter, *, agent_id, brief, only, reps=3, batch_size=5,
            budget_seconds=1200, output_root=DEFAULT_OUTPUT, pack_path=DEFAULT_PACK,
            client=None, clock=time.monotonic, sleep=time.sleep, secrets=(),fail_fast=False,parallel_reps=False):
    """Explicit execution entry point; use a fake client/clock in offline tests."""
    if brief not in {"A", "B"} or not only or not agent_id:
        raise RunnerError("execution_requires_agent_brief_and_variants")
    resource_id(agent_id)
    settings(reps, batch_size)
    selected = select_rows(rows, adapter, brief, only)
    api_schema=json.loads((adapter.KIT/'tools/openapi.json').read_text(encoding='utf-8'))
    budget = Budget(budget_seconds, clock, sleep)
    frozen_pack_hash = digest(rows)
    pack_path = Path(pack_path) if pack_path is not None else None
    verification_fingerprint = None

    def verify():
        nonlocal verification_fingerprint
        try:
            if hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=RUNNER_SOURCE_PIN:
                raise ValueError('runner source changed after import')
            verified_manifest = adapter.verify_pack()
            fingerprint = digest(verified_manifest)
            if verification_fingerprint is not None and fingerprint != verification_fingerprint:
                raise ValueError("verified source manifest changed during run")
            verification_fingerprint = fingerprint
            if pack_path and digest(json.loads(pack_path.read_text(encoding="utf-8"))) != frozen_pack_hash:
                raise ValueError("pack changed after selection")
            adapter.validate_hosted(selected)
        except Exception:
            raise RunnerError("pack_integrity_failed") from None
        budget.remaining()
        return verified_manifest

    verified_manifest = verify()  # No client/output creation before verification.
    client = client or OfficialClient(adapter.KIT, budget)
    if client.AGENT_LLM != AGENT_MODEL:
        raise RunnerError("official_agent_model_required")
    api_origin, bank_origin = origin(client.URL), origin(client.HOST)
    secrets = tuple(secrets) + tuple(os.environ.get(k, "") for k in ("FREYA_API_KEY", "FREYA_BANK_TEAM_KEY"))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    # Runtime artifacts only. This also protects an explicitly chosen output root.
    ignore = output_root / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")
    run_dir = output_root / run_id
    run_dir.mkdir()
    jobs = [{"id": row["id"], "variant_id": row["variant_id"], "rep": rep,
             "row_sha256": digest(row), "state": "planned"}
            for rep in range(1, reps + 1) for row in selected]
    manifest = {"run_id": run_id, "started_at": datetime.now(timezone.utc).isoformat(),
                "runner_source_sha256":RUNNER_SOURCE_PIN,"diagnostic_fail_fast":bool(fail_fast),"parallel_repetitions":bool(parallel_reps),
                "agent_id": agent_id, "brief": brief, "api_origin": api_origin, "bank_origin": bank_origin,
                "pack_sha256": frozen_pack_hash, "reps": reps, "batch_size": batch_size,
                "verified_pack_manifest": copy.deepcopy(verified_manifest),
                "total_budget_seconds": budget_seconds, "model_overrides": {
                    "agent": copy.deepcopy(client.AGENT_LLM), "simulator_judge": copy.deepcopy(client.SIM_LLM)},
                "status": "preflight", "jobs": jobs, "batches": [], "persona_cache_used": False}
    seen_customers, seen_personas, seen_calls = set(), set(), set()
    selected_by_variant = {row["variant_id"]: row for row in selected}

    def persist():
        write_json(run_dir / "manifest.json", manifest, secrets)
        write_json(run_dir / "results.json", summarize(selected, jobs, reps, manifest["status"]), secrets)

    def request(method, path, body=None, *, bank=False, **params):
        budget.remaining()
        if method != "GET":
            verify()  # Fail closed if sources/outputs change during a run, too.
        try:
            response = client.bank(path, body) if bank else client.api(method, path, body, **params)
        except RunnerError:
            raise
        except Exception:
            if budget.clock() >= budget.deadline:
                raise RunnerError("total_budget_exhausted") from None
            raise RunnerError("request_failed") from None
        budget.remaining()
        if isinstance(response, dict) and (response.get("success") is False or response.get("error")):
            raise RunnerError("api_reported_failure")
        return response

    def idle():
        offset, seen = 0, set()
        while True:
            page = request("GET", "/api/v2/simulations", workspaceId=manifest["workspace_id"], limit=WORKSPACE_PAGE_SIZE, offset=offset)
            simulations = items(page, "simulations")
            for simulation in simulations:
                sid = resource_id(simulation.get("id"))
                if sid in seen:
                    raise RunnerError("incomplete_workspace_listing")
                seen.add(sid)
                if simulation.get("workspaceId", manifest["workspace_id"]) != manifest["workspace_id"]:
                    raise RunnerError("workspace_binding_mismatch")
                # Pending/queued/running/draft/paused/unknown states all block.
                if simulation.get("status") not in INACTIVE:
                    raise RunnerError("workspace_not_idle")
            if len(simulations) < WORKSPACE_PAGE_SIZE:
                if isinstance(page, dict) and (page.get("hasMore") is True or
                        isinstance(page.get("total"), int) and page["total"] > len(seen)):
                    raise RunnerError("incomplete_workspace_listing")
                return
            offset += WORKSPACE_PAGE_SIZE

    persist()
    try:
        budget.remaining()
        try:
            manifest["workspace_id"] = resource_id(client.workspace_id())
        except Exception:
            raise RunnerError("workspace_lookup_failed") from None
        budget.remaining()
        for rep in ([None] if parallel_reps else range(1, reps + 1)):
            rep_jobs = jobs if parallel_reps else [job for job in jobs if job["rep"] == rep]
            for start in range(0, len(rep_jobs), batch_size):
                batch_jobs = rep_jobs[start:start + batch_size]
                idle()  # Before any session/persona allocation.
                number = len(manifest["batches"]) + 1
                batch = {"batch": number, "rep": rep, "repetitions":sorted({job['rep'] for job in batch_jobs}), "state": "allocating",
                         "variants": [job["variant_id"] for job in batch_jobs]}
                manifest["batches"].append(batch)
                manifest["status"] = "running"
                persist()
                variables_map = {}
                for job in batch_jobs:
                    row = selected_by_variant[job["variant_id"]]
                    job["state"] = "session_start_attempted"
                    persist()
                    session = request("POST", "/v1/practice/sessions", {"case": row["id"]}, bank=True)
                    variables = session.get("variables") if isinstance(session, dict) else None
                    if not isinstance(variables, dict) or set(variables) != CALL_VARIABLES:
                        raise RunnerError("malformed_session_variables")
                    cid = resource_id(variables["customer_id"])
                    if cid in seen_customers:
                        raise RunnerError("duplicate_customer_id")
                    if any(variables[key] != row["variables"].get(key) for key in CALL_VARIABLES - {"customer_id"}):
                        raise RunnerError("session_fixture_mismatch")
                    seen_customers.add(cid)
                    job.update(customer_id=cid, session_variables=copy.deepcopy(variables), state="session_created")
                    persist()
                    spec = copy.deepcopy(adapter.persona_for(row))
                    if set(spec) - {"name", "prompt", "successCriteria", "tags"} or any(
                            not isinstance(spec.get(k), str) or not spec[k] for k in ("name", "prompt", "successCriteria")):
                        raise RunnerError("malformed_persona_spec")
                    spec["name"] += f" [rep {job['rep']}; {run_id}]"
                    job.update(persona_sha256=digest(spec), state="persona_start_attempted")
                    persist()
                    made = items(request("POST", "/api/v2/personas", {"personas": [spec]}), "personas")
                    if len(made) != 1:
                        raise RunnerError("persona_cardinality_mismatch")
                    pid = resource_id(made[0].get("id"))
                    if pid in seen_personas:
                        raise RunnerError("duplicate_persona_id")
                    seen_personas.add(pid)
                    job.update(persona_id=pid, state="allocated")
                    variables_map[pid] = copy.deepcopy(variables)
                    write_json(run_dir / "personas" / (pid + ".json"), spec, secrets)
                    persist()
                idle()  # Race check; the server also enforces its one-active cap.
                body = {"agentId": agent_id, "name": f"customer benchmark {run_id} batch {number}",
                        "mode": "chat", "selectedPersonaIds": list(variables_map),
                        "customerVariablesMap": variables_map, "maxConcurrentCalls": len(batch_jobs),
                        "runsPerPersona": 1, "maxRetries": 0, "maxCallDurationSeconds": 420,
                        "assistantLlmOverride": copy.deepcopy(client.AGENT_LLM),
                        "routingLlmOverride": copy.deepcopy(client.AGENT_LLM),
                        "extractionLlmOverride": copy.deepcopy(client.AGENT_LLM),
                        "personaLlmOverride": copy.deepcopy(client.SIM_LLM),
                        "analysisLlmOverride": copy.deepcopy(client.SIM_LLM)}
                batch["state"] = "start_outcome_unknown"
                persist()  # Durable marker BEFORE a possibly uncertain mutation.
                created = request("POST", "/api/v2/simulations", body)
                simulation = created.get("simulation", created) if isinstance(created, dict) else {}
                sid = resource_id(simulation.get("id"))
                batch.update(simulation_id=sid, state="polling")
                for job in batch_jobs:
                    job.update(simulation_id=sid, state="simulation_started")
                write_json(run_dir / "batches" / f"{number:04d}-start.json", created, secrets)
                persist()
                while True:
                    polled = request("GET", "/api/v2/simulations/" + sid)
                    simulation = polled.get("simulation", polled) if isinstance(polled, dict) else {}
                    if simulation.get("id", sid) != sid:
                        raise RunnerError("simulation_binding_mismatch")
                    batch["simulation_status"] = simulation.get("status")
                    write_json(run_dir / "batches" / f"{number:04d}-status.json", polled, secrets)
                    persist()
                    if simulation.get("status") in TERMINAL:
                        break
                    budget.wait()
                if simulation["status"] != "completed":
                    raise RunnerError("simulation_not_completed")
                iterations = items(request("GET", f"/api/v2/simulations/{sid}/iterations"), "iterations")
                if len(iterations) != 1:
                    raise RunnerError("iteration_cardinality_mismatch")
                iid = resource_id(iterations[0].get("id"))
                batch["iteration_id"] = iid
                iteration = request("GET", f"/api/v2/simulations/{sid}/iterations/{iid}", limit=100, offset=0)
                write_json(run_dir / "batches" / f"{number:04d}-iteration.json", iteration, secrets)
                runs = items(iteration, "runs")
                if not isinstance(iteration, dict) or type(iteration.get("runsTotal")) is not int or iteration["runsTotal"] != len(batch_jobs) or len(runs) != len(batch_jobs):
                    raise RunnerError("run_cardinality_mismatch")
                judge_by_persona = {}
                for judge in runs:
                    pid = judge.get("personaId")
                    if pid not in variables_map or pid in judge_by_persona:
                        raise RunnerError("judge_persona_binding_mismatch")
                    call_id = resource_id(judge.get("callId"))
                    if call_id in seen_calls:
                        raise RunnerError("duplicate_call_id")
                    seen_calls.add(call_id)
                    judge_by_persona[pid] = judge
                for job in batch_jobs:
                    judge = judge_by_persona[job["persona_id"]]
                    job.update(iteration_id=iid, call_id=judge["callId"], state="collecting_evidence")
                    persist()
                    ledger = request("GET", "/v1/practice/ledger/" + job["customer_id"], bank=True)
                    if not isinstance(ledger, dict) or ledger.get("customer_id", job["customer_id"]) != job["customer_id"]:
                        raise RunnerError("ledger_session_binding_mismatch")
                    row = selected_by_variant[job["variant_id"]]
                    if ledger.get("case", row["id"]) != row["id"] or ledger.get("case_id", row["id"]) != row["id"] or ledger.get("now", row["variables"]["now"]) != row["variables"]["now"]:
                        raise RunnerError("ledger_fixture_binding_mismatch")
                    call_response = request("GET", "/api/v2/call/" + job["call_id"])
                    call = call_response.get("call", call_response) if isinstance(call_response, dict) else None
                    if not isinstance(call, dict) or not isinstance(call.get("messages"), list) or not call["messages"]:
                        raise RunnerError("missing_call_evidence")
                    if call.get("id", job["call_id"]) != job["call_id"] or call.get("personaId", job["persona_id"]) != job["persona_id"]:
                        raise RunnerError("call_binding_mismatch")
                    if any(call.get(key, value) != value for key, value in {
                            "agentId": agent_id, "simulationId": sid, "iterationId": iid}.items()):
                        raise RunnerError("call_binding_mismatch")
                    evidence_path = Path("evidence") / f"{jobs.index(job) + 1:04d}.json"
                    write_json(run_dir / evidence_path, {"binding": copy.deepcopy(job), "ledger": ledger,
                                                         "judge": judge, "call": call}, secrets)
                    job['provenance']=reconcile_call(call,ledger,job,agent_id,manifest['workspace_id'],api_schema)
                    provenance=job['provenance']
                    version={key:provenance[key] for key in ('workflow_id','published_version_id','published_version_number')}
                    if any(value is None for value in version.values()):
                        raise RunnerError('missing_published_version_provenance')
                    if 'tested_version' in manifest and manifest['tested_version']!=version:
                        raise RunnerError('published_version_changed_during_run')
                    manifest['tested_version']=version
                    case = copy.deepcopy(selected_by_variant[job["variant_id"]])
                    case["_session_customer_id"] = job["customer_id"]
                    result = adapter.score(case, ledger, judge)
                    if not isinstance(result, dict) or type(result.get("pass")) is not bool:
                        raise RunnerError("malformed_score_result")
                    # A judge can never be promoted from queued/fail/missing to pass.
                    if judge.get("outcome") != "pass":
                        result["pass"] = False
                    job.update(result=result, evidence=evidence_path.as_posix(), state="scored")
                    persist()
                batch["state"] = "scored"
                persist()
                if fail_fast and any(job['result']['pass'] is False for job in batch_jobs):
                    raise RunnerError('diagnostic_stopped_on_failure')
        manifest["status"] = "completed"
    except RunnerError as error:
        manifest["error_code"] = str(error)
        manifest["status"] = 'stopped_on_failure' if str(error)=='diagnostic_stopped_on_failure' else "timeout" if str(error) == "total_budget_exhausted" else "incomplete"
    except Exception:
        # Error bodies, environment values and arbitrary adapter exception text
        # are deliberately withheld. Allocated resources are never canceled.
        manifest.update(status="incomplete", error_code="execution_failed")
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    persist()
    result = summarize(selected, jobs, reps, manifest["status"])
    result.update(run_dir=str(run_dir), error_code=manifest.get("error_code"))
    return result


def main(argv=None, *, adapter=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--agent-id")
    parser.add_argument("--brief", choices=["A", "B"])
    parser.add_argument("--only", help="Exact comma-separated variant_ids; no implicit execution of the whole pack")
    parser.add_argument("--cases", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--budget-seconds", type=float, default=1200)
    parser.add_argument('--fail-fast',action='store_true',help='Diagnostic run: stop after collecting a failing batch; unobserved repetitions remain unverified')
    parser.add_argument('--parallel-reps',action='store_true',help='Pack independent repeats into the same <=5-call batch; each retains a fresh bank session and persona')
    args = parser.parse_args(argv)
    try:
        if args.execute and (not args.agent_id or not args.brief or not args.only):
            raise RunnerError("execution_requires_agent_brief_and_variants")
        adapter = adapter or importlib.import_module("benchmark_adapter")
        rows = json.loads(args.cases.read_text(encoding="utf-8"))
        result = plan(rows, adapter, brief=args.brief, only=args.only, reps=args.reps, batch_size=args.batch_size,parallel_reps=args.parallel_reps)
        result["total_budget_seconds"] = args.budget_seconds
        if args.execute:
            if client is None and (not os.environ.get("FREYA_API_KEY") or len(os.environ.get("FREYA_BANK_TEAM_KEY", "")) < 16):
                raise RunnerError("required_credentials_missing")
            result = execute(rows, adapter, agent_id=args.agent_id, brief=args.brief, only=args.only,
                             reps=args.reps, batch_size=args.batch_size, budget_seconds=args.budget_seconds,
                             output_root=args.out, pack_path=args.cases, client=client,fail_fast=args.fail_fast,parallel_reps=args.parallel_reps)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return int(args.execute and not result["pass"])
    except RunnerError as error:
        print(json.dumps({"execution_status": "not_completed", "error_code": str(error)}))
        return 2
    except Exception:
        print(json.dumps({"execution_status": "not_completed", "error_code": "configuration_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
