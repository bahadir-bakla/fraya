"""Source-driven builder, bounded repair, and real platform evidence.

No practice-case expected answers enter workflow generation. The optional
practice cases are evaluated only after publishing a candidate.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from collections import deque, Counter

from .builder_policy import POLICY_SCHEMA, WORKFLOW_SCHEMA, CRITIC_SCHEMA, POLICY_GAP_SCHEMA, validate_policy, validate_coverage, source_ids
from .builder_prompts import policy_prompt, workflow_prompt, critic_prompt, policy_gap_prompt
from .builder_provider import CodexProvider
from .input_contract import inspect_inputs
from .tool_api import load_tool_api, validate_json


class BuildFailure(RuntimeError):
    pass


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class Evidence:
    def __init__(self, directory: Path, budget_seconds: int):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.started = time.monotonic()
        self.deadline = self.started + budget_seconds
        self.trace = {"started_at": utc(), "budget_seconds": budget_seconds, "status": "building", "events": [], "tests": []}
        self.scrub = lambda value: value
        self.write("trace.json", self.trace)

    def write(self, name: str, value):
        path = self.directory / name
        clean = self.scrub(value)
        path.write_text(json.dumps(clean, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return path

    def event(self, kind: str, **fields):
        item = {"at": utc(), "elapsed_seconds": round(time.monotonic() - self.started, 2), "kind": kind, **fields}
        self.trace["events"].append(self.scrub(item))
        self.write("trace.json", self.trace)
        print(f"[{item['elapsed_seconds']:7.1f}s] {kind}", flush=True)

    def remaining(self, reserve: float = 0) -> float:
        seconds = self.deadline - time.monotonic() - reserve
        if seconds < 1:
            raise BuildFailure("Builder time budget exhausted; artifacts and trace were preserved")
        return seconds

    def finish(self, status: str, **fields):
        self.trace.update(status=status, finished_at=utc(), seconds=round(time.monotonic()-self.started, 2), **fields)
        self.write("trace.json", self.trace)


def compare_saved(expected, actual, path="$", ignored=frozenset({"nodePositions", "agent_config"})) -> list[str]:
    """Detect stripping or rewriting any authored semantic field; server extras are fine."""
    issues = []
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [path + " changed type"]
        for key, value in expected.items():
            if path == "$" and key in ignored:
                continue
            if key not in actual:
                issues.append(path + "." + key + " was stripped")
            else:
                issues.extend(compare_saved(value, actual[key], path + "." + key, ignored))
    elif isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            issues.append(path + " list changed length/type")
        else:
            for index, value in enumerate(expected):
                issues.extend(compare_saved(value, actual[index], f"{path}[{index}]", ignored))
    elif expected != actual:
        issues.append(path + " changed value")
    return issues


def critic_errors(critic: dict, contract: dict, allow_source_gaps: bool = False) -> list[str]:
    errors = validate_json(CRITIC_SCHEMA, critic)
    if errors:
        return errors
    known = source_ids(contract)
    for item in critic["issues"] + critic["counterexamples"]:
        if not item["source_ids"] or set(item["source_ids"]) - known:
            errors.append("Critic reported missing or unknown source references")
    if (critic["verdict"] != "pass" and not (allow_source_gaps and critic["verdict"] == "blocked")) or any(i["severity"] == "error" for i in critic["issues"]):
        errors.append("Independent source critic requires revision: " + critic["verdict"])
    return errors


def layout_workflow(workflow: dict) -> None:
    """Editor layout from graph connectivity, including cycles, with no policy edits."""
    nodes = workflow.get("nodes", {})
    initial = workflow.get("initial_node")
    queue = deque([(initial, 0)])
    levels = {}
    while queue:
        name, level = queue.popleft()
        if name in levels or name not in nodes:
            continue
        levels[name] = level
        node = nodes[name]
        targets = [t.get("target_node") for t in node.get("transitions", [])]
        targets += [node.get("passthrough_default_transition"), node.get("max_turn_transition")]
        queue.extend((target, level+1) for target in targets if target in nodes and target not in levels)
    lanes = Counter()
    extra = max(levels.values(), default=0) + 1
    for name, node in list(nodes.items()) + list(workflow.get("global_nodes", {}).items()):
        level = levels.get(name, extra)
        node["position"] = {"x": level*370, "y": lanes[level]*230}
        lanes[level] += 1


class LiveBackend:
    def __init__(self, root: Path, kit: Path, evidence: Evidence):
        # Explicit known launcher, never scan for dotenv or auth stores.
        launcher = root / "scripts" / "freya_dpapi_server.py"
        if launcher.is_file():
            spec = importlib.util.spec_from_file_location("fraya_credential_launcher", launcher)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.inject_credentials()
        sys.path.insert(0, str(root / "skill-creator-skill-lift" / "integrations" / "freya-mcp"))
        from freya_mcp.bridge import Bridge, Config
        self.bridge = Bridge(Config.load(root, kit))
        self.evidence = evidence
        evidence.scrub = self.bridge.scrub
        self.tool_calls = 0

    def call(self, method: str, *args, **kwargs):
        remaining = self.evidence.remaining()
        import httpx
        self.bridge.http.timeout = httpx.Timeout(min(15, remaining), connect=min(5, remaining))
        self.tool_calls += 1
        self.evidence.event("platform_call_started", method=method)
        # Writing trace can itself stall. Re-check immediately before dispatch.
        remaining = self.evidence.remaining()
        self.bridge.http.timeout = httpx.Timeout(min(15, remaining), connect=min(5, remaining))
        result = getattr(self.bridge, method)(*args, **kwargs)
        self.evidence.event("platform_call_finished", method=method)
        return result

    def deploy(self, path: Path, slot: str, expected: dict) -> dict:
        validation = self.call("validate", str(path), name=slot + "-schema", remote=True)
        self.evidence.write("remote-validation.json", validation)
        deployed = self.call("save", slot, str(path), name=slot)
        self.evidence.write("deployment.json", deployed)
        row = self.call("get_workflow", deployed["workflow_id"])
        self.evidence.write("saved-workflow.json", row)
        issues = compare_saved(expected, row.get("workflow", {}))
        self.evidence.write("readback.json", {"issues": issues, "authored_fields_preserved": not issues})
        if issues:
            raise BuildFailure("Platform changed authored workflow fields: " + "; ".join(issues[:12]))
        config = row.get("workflow", {}).get("agent_config", {}).get("llmConfig", {})
        if config.get("provider") != "experimental-5" or config.get("model") != "experimental-5":
            raise BuildFailure("Saved phone model differs from the official competition model")
        self.evidence.trace["deployment"] = deployed
        return deployed

    def practice(self, deployed: dict, case_ids: list[str], style: str = "", repetitions: int = 1) -> list[dict]:
        if not case_ids:
            return []
        known = {c["id"] for c in self.bridge.cases()}
        if set(case_ids) - known or len(set(case_ids)) != len(case_ids):
            raise BuildFailure("Practice selection contains unknown or duplicate case IDs")
        all_rows = []
        for rep in range(repetitions):
            for offset in range(0, len(case_ids), 5):
                # Do not cancel or overlap another user's running simulation.
                while self.bridge.items(self.call("list_simulations", limit=100, status="running"), "simulations"):
                    self.evidence.remaining(reserve=100)
                    time.sleep(min(10, self.evidence.remaining(reserve=100)))
                # Reserve the minimum call window before creating any bank sessions/personas.
                self.evidence.remaining(reserve=135)
                prepared = self.call("prepare_practice", case_ids=case_ids[offset:offset+5], style=style)
                duration = int(min(420, self.evidence.remaining(reserve=75)))
                if duration < 60:
                    raise BuildFailure("Insufficient time for another practice simulation")
                started = self.call("start", deployed["agent_id"], f"builder {deployed['workflow_id']} rep{rep+1}",
                                    prepared["variables_by_persona"], max_seconds=duration, concurrency=5)
                sid = started["simulation_id"]
                batch = {"simulation_id": sid, "repetition": rep+1, "bindings": prepared["cases"], "deployment": deployed}
                self.evidence.trace["tests"].append(batch)
                self.evidence.event("simulation_started", **batch)
                while True:
                    state = self.call("status", sid)
                    if state["terminal"]:
                        break
                    time.sleep(min(10, self.evidence.remaining(reserve=45)))
                batch["status"] = state["simulation"].get("status")
                iterations = self.bridge.items(self.call("iterations", sid), "iterations")
                runs = []
                if iterations:
                    iid = iterations[-1]["id"]
                    batch["iteration_id"] = iid
                    page_offset = 0
                    while True:
                        page = self.call("iteration", sid, iid, limit=100, offset=page_offset)
                        part = self.bridge.items(page, "runs")
                        runs.extend(part)
                        if len(part) < 100:
                            break
                        page_offset += len(part)
                self.evidence.write(f"simulation-{sid}.json", {"state": state, "iterations": iterations, "runs": runs})
                by_persona = {r["personaId"]: r for r in runs}
                for binding in prepared["cases"]:
                    judge = by_persona.get(binding["persona_id"], {})
                    ledger = self.call("ledger", binding["customer_id"], case_id=binding["case_id"])
                    self.evidence.write(f"ledger-{binding['customer_id']}.json", ledger)
                    call_id = judge.get("callId")
                    if call_id:
                        self.evidence.write(f"call-{call_id}.json", self.call("call", call_id))
                    failed = list(ledger["ledger_score"]["failed"])
                    if judge.get("outcome") != "pass":
                        failed.append("conversation: " + str(judge.get("reason") or "no verdict"))
                    result = {**binding, "simulation_id": sid, "call_id": call_id, "repetition": rep+1,
                              "pass": not failed, "failed": failed,
                              "tools": [c["tool"] for c in ledger["ledger"].get("calls", [])]}
                    all_rows.append(result)
                batch["results"] = all_rows[-len(prepared["cases"]):]
                self.evidence.event("simulation_scored", passed=sum(r["pass"] for r in batch["results"]), total=len(batch["results"]))
        return all_rows

    def close(self):
        self.bridge.close()


def build_live(briefs: list[str], tool_api: str, out: str, *, root: Path, kit: Path,
               model: str = "gpt-6.1-sol", budget_seconds: int = 1800, slot: str = "codex-builder-rd",
               case_ids: list[str] | None = None, style: str = "", repetitions: int = 1,
               repairs: int = 2, compile_only: bool = False, policy_checkpoint: str = "", allow_source_gaps: bool = False,
               workflow_checkpoint: str = "", provider=None, backend_factory=LiveBackend) -> dict:
    if not 60 <= budget_seconds <= 1800 or not 0 <= repairs <= 4 or not 1 <= repetitions <= 3:
        raise ValueError("Budget must be 60..1800 seconds, repairs 0..4, repetitions 1..3")
    if allow_source_gaps and not case_ids:
        raise ValueError("Source-gap development mode requires explicit practice cases")
    evidence = Evidence(Path(out), budget_seconds)
    backend = None
    try:
        contract = inspect_inputs(briefs, tool_api)
        api = load_tool_api(tool_api)
        evidence.write("input-contract.json", contract)
        evidence.trace["inputs"] = [{"path": d["path"], "sha256": d["sha256"]} for d in contract["documents"]]
        evidence.trace["tool_api"] = contract["tool_api_source"]
        checkpoint_policy = None
        checkpoint_review = None
        checkpoint_generated = None
        if policy_checkpoint:
            checkpoint = Path(policy_checkpoint).resolve()
            prior_contract = json.loads((checkpoint.parent / "input-contract.json").read_text(encoding="utf-8"))
            prior_trace = json.loads((checkpoint.parent / "trace.json").read_text(encoding="utf-8"))
            if prior_trace["status"] == "building":
                raise BuildFailure("Cannot resume a checkpoint whose build is still active")
            signatures = lambda c: sorted((d["id"], d["sha256"]) for d in c["documents"])
            if signatures(contract) != signatures(prior_contract) or contract["tool_api_source"]["sha256"] != prior_contract["tool_api_source"]["sha256"]:
                raise BuildFailure("Policy checkpoint source/API hashes differ from current inputs")
            elapsed = (datetime.now(timezone.utc)-datetime.fromisoformat(prior_trace["started_at"])).total_seconds()
            if not 0 <= elapsed < budget_seconds:
                raise BuildFailure("Policy checkpoint is outside this build's time budget")
            evidence.started -= elapsed
            evidence.deadline -= elapsed
            evidence.trace["started_at"] = prior_trace["started_at"]
            evidence.trace["events"] = prior_trace["events"]
            evidence.trace["tests"] = prior_trace.get("tests", [])
            evidence.trace["checkpoint"] = {"path": str(checkpoint), "prior_status": prior_trace["status"],
                                            "prior_error": prior_trace.get("error", ""), "elapsed_seconds": elapsed}
            checkpoint_policy = json.loads(checkpoint.read_text(encoding="utf-8"))
            review_path = checkpoint.parent / "policy-gap-review.json"
            if review_path.is_file():
                checkpoint_review = json.loads(review_path.read_text(encoding="utf-8"))
            if workflow_checkpoint:
                candidate = Path(workflow_checkpoint).resolve()
                if candidate.parent != checkpoint.parent:
                    raise BuildFailure("Workflow and policy checkpoints must belong to the same run")
                checkpoint_generated = json.loads(candidate.read_text(encoding="utf-8"))
                if validate_json(WORKFLOW_SCHEMA, checkpoint_generated):
                    raise BuildFailure("Workflow checkpoint has invalid structure")
            evidence.event("policy_checkpoint_resumed", source_and_api_hashes_match=True)
        engine = provider or CodexProvider(evidence.directory / "model-calls", model, evidence.event)
        if not compile_only:
            backend = backend_factory(root, kit, evidence)
            evidence.event("platform_connected", health=backend.call("health", live=True))
        reserve = 480 if not compile_only and case_ids else 60
        policy = checkpoint_policy or engine.generate("policy", policy_prompt(contract), POLICY_SCHEMA, min(360, evidence.remaining(reserve)))
        evidence.write("policy.json", policy)
        # Structural provenance first; alleged prose ambiguities get a source-grounded review.
        structural_policy = {**policy, "ambiguities": []}
        issues = validate_policy(structural_policy, contract)
        if issues:
            raise BuildFailure("Policy compilation rejected: " + "; ".join(issues))
        gap_review = {}
        if policy["ambiguities"]:
            gap_review = checkpoint_review or engine.generate("policy-gap-review", policy_gap_prompt(contract, policy["ambiguities"]),
                                                              POLICY_GAP_SCHEMA, min(180, evidence.remaining(reserve)))
            evidence.write("policy-gap-review.json", gap_review)
            if validate_json(POLICY_GAP_SCHEMA, gap_review):
                raise BuildFailure("Policy gap review has invalid structure")
            rows = gap_review["assessments"]
            indices = [r["index"] for r in rows]
            references = source_ids(contract) | {d["id"] for d in contract["documents"]} | {"tool_contract"} | {
                "tool_contract.operations." + name for name in contract["tool_contract"]["operations"]}
            if sorted(indices) != list(range(len(policy["ambiguities"]))) or any(
                not r["source_ids"] or set(r["source_ids"])-references or not r["resolution"].strip() for r in rows):
                raise BuildFailure("Policy gap review lacks complete source-linked assessments")
            blocking = [r for r in rows if r["disposition"] == "blocking"]
            if blocking and not allow_source_gaps:
                raise BuildFailure("Unresolved binding policy ambiguity: " + "; ".join(r["resolution"] for r in blocking))
            policy = structural_policy
            evidence.write("reviewed-policy.json", policy)
            evidence.trace["experimental_source_gaps"] = blocking if allow_source_gaps else []
        from .freya_lint import lint_workflow
        contract = {**contract, "stage": "policy_compiled", "semantic_policy_compiled": True,
                    "precedence_status": "Standalone brief; no missing amendment is required" if len(contract["documents"]) == 1 else "Explicit source amendments are represented in compiled policy rules",
                    "readiness": {**contract["readiness"], "semantic_policy_compiled": True}}
        evidence.write("compiled-source-context.json", contract)
        feedback = {"source_gap_review": gap_review}
        previous_generated = checkpoint_generated
        if previous_generated:
            feedback["previous_workflow"] = json.loads(previous_generated["workflow_json"])
            feedback["checkpoint_review"] = {
                p.name: json.loads(p.read_text(encoding="utf-8"))
                for p in Path(workflow_checkpoint).parent.glob("*.json")
                if p.name.startswith(("lint-", "critic-", "practice-"))}
        result = None
        for attempt in range(repairs+1):
            evidence.event("candidate_started", candidate=attempt+1)
            if previous_generated and isinstance(feedback.get("previous_workflow"), dict):
                from .builder_repair import PATCH_SCHEMA, apply_repair, repair_prompt
                repair = engine.generate(f"repair-{attempt+1}", repair_prompt(contract, policy, kit, feedback),
                                         PATCH_SCHEMA, min(240, evidence.remaining(reserve)))
                evidence.write(f"repair-{attempt+1}.json", repair)
                try:
                    generated = apply_repair(previous_generated, repair)
                except (ValueError, KeyError, TypeError, IndexError) as exc:
                    feedback["patch_errors"] = type(exc).__name__ + ": " + str(exc)[:300]
                    evidence.event("repair_rejected", candidate=attempt+1, reason=feedback["patch_errors"])
                    continue
            else:
                generated = engine.generate(f"workflow-{attempt+1}", workflow_prompt(contract, policy, kit, feedback),
                                            WORKFLOW_SCHEMA, min(540, evidence.remaining(reserve)))
            evidence.write(f"candidate-{attempt+1}.json", generated)
            try:
                compact = json.loads(generated["workflow_json"])
            except (ValueError, KeyError, TypeError):
                feedback = {"local_errors": ["workflow_json must serialize a complete workflow object"], "source_gap_review": gap_review}
                previous_generated = None
                continue
            try:
                from .freya_compiler import compile_workflow
                workflow = compile_workflow(compact, api)
            except (ValueError, KeyError, TypeError) as exc:
                feedback = {"previous_workflow": compact,
                            "local_errors": [type(exc).__name__ + ": " + str(exc)[:500]], "source_gap_review": gap_review}
                previous_generated = generated
                continue
            if isinstance(workflow, dict) and isinstance(workflow.get("nodes"), dict):
                layout_workflow(workflow)
            path = evidence.write(f"workflow-{attempt+1}.json", workflow)
            ordinary = workflow.get("nodes", {}) if isinstance(workflow, dict) else {}
            global_nodes = workflow.get("global_nodes", {}) if isinstance(workflow, dict) else {}
            node_maps_valid = isinstance(ordinary, dict) and isinstance(global_nodes, dict)
            definitions = list(ordinary.values())+list(global_nodes.values()) if node_maps_valid else []
            evidence.event("workflow_emitted", candidate=attempt+1, node_count=len(workflow.get("nodes", {})),
                           global_node_count=len(workflow.get("global_nodes", {})),
                           tool_definitions=sum(len(n.get("tools", []))+len(n.get("pre_actions", []))
                                                for n in definitions if isinstance(n, dict))+len(workflow.get("tools", [])))
            local = lint_workflow(workflow, api)
            from .guarded_freya_adapter import validate_guard_wiring
            local += validate_guard_wiring(workflow)
            coverage = validate_coverage({**generated, "limitations": []} if allow_source_gaps else generated, contract, workflow) if node_maps_valid else ["Workflow node collections must be maps"]
            evidence.trace["emitter_limitations"] = generated["limitations"]
            feedback = {"previous_workflow": json.loads(generated["workflow_json"]), "expanded_workflow": workflow,
                        "lint": local, "coverage_errors": coverage, "source_gap_review": gap_review}
            previous_generated = generated
            evidence.write(f"lint-{attempt+1}.json", {"lint": local, "coverage": coverage})
            if coverage or any(i["severity"] == "error" for i in local):
                evidence.event("candidate_rejected_locally", candidate=attempt+1, errors=len(coverage)+sum(i["severity"]=="error" for i in local))
                continue
            critic = engine.generate(f"critic-{attempt+1}", critic_prompt(contract, workflow), CRITIC_SCHEMA,
                                     min(240, evidence.remaining(reserve)))
            evidence.write(f"critic-{attempt+1}.json", critic)
            feedback["independent_critic"] = critic
            if critic_errors(critic, contract, allow_source_gaps):
                evidence.event("candidate_rejected_by_critic", candidate=attempt+1)
                continue
            if compile_only:
                result = {"status": "compiled_unpublished", "workflow_path": str(path), "live_tested": False}
                break
            try:
                deployed = backend.deploy(path, slot, workflow)
            except Exception as exc:
                # Sanitized bridge errors only, never raw HTTP exception repr.
                from freya_mcp.bridge import BridgeError
                if isinstance(exc, BridgeError) and "validation:" in str(exc):
                    feedback["platform_schema_errors"] = str(exc)
                    evidence.event("candidate_rejected_by_platform", candidate=attempt+1, error=str(exc))
                    continue
                raise
            rows = backend.practice(deployed, case_ids or [], style, repetitions)
            evidence.write(f"practice-{attempt+1}.json", rows)
            export = backend.call("export", deployed["workflow_id"], filename=slot + ".workflow.json")
            envelope = json.loads(Path(export["path"]).read_text(encoding="utf-8"))
            evidence.write("platform-export.workflow.json", envelope)
            evidence.write("workflow.json", envelope["workflow"])
            result = {"status": "practice_passed" if rows and all(r["pass"] for r in rows) else "practice_failed" if rows else "published_untested",
                      "deployment": deployed, "workflow_path": str(evidence.directory / "workflow.json"),
                      "passed": sum(r["pass"] for r in rows), "total_trials": len(rows), "live_tested": bool(rows),
                      "export_secrets_redacted": export["secrets_redacted"], "final_ready": False}
            if not rows or all(r["pass"] for r in rows):
                break
            feedback["practice_failures"] = [r for r in rows if not r["pass"]]
            feedback["practice_note"] = "Fix general source policy/runtime behavior, never add case-ID/customer-specific exceptions."
            if evidence.deadline-time.monotonic() < reserve+240:
                break
        if result is None:
            raise BuildFailure("No candidate passed the source, platform and review gates within the repair budget")
        evidence.finish(result["status"], result=result, platform_tool_calls=backend.tool_calls if backend else 0)
        return result
    except Exception as exc:
        # Model and Bridge errors already sanitized; unexpected exceptions use class only.
        from .builder_provider import ProviderError
        safe = str(exc) if isinstance(exc, (BuildFailure, ProviderError, ValueError)) else type(exc).__name__
        if type(exc).__name__ == "BridgeError":
            safe = str(exc)
        evidence.finish("failed", error=safe, final_ready=False)
        raise BuildFailure(safe) from None
    finally:
        if backend:
            backend.close()
