"""Original public ledger checks on automatically generated local repair arms.

Uses authored conditional extraction, not an LLM/voice/hosted benchmark. A is the
new generated arm; B remains the identical frozen control in both comparisons.
Source inputs, code and expected outcomes remain unchanged during replay.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def documented_condition(value, variables, wr):
    """Kit deterministic equals/greater_than/always, with optional legacy mode.

    The earlier driver required a legacy ``mode=exact`` even though the original
    workflow-format documentation also permits the bare deterministic form.
    Unknown operators still stop the replay instead of guessing a route.
    """
    if "conditions" in value:
        if value.get("logic") not in {"and", "or"}:
            raise wr.ReplayError("unsupported_condition_logic")
        predicates = [documented_condition(v, variables, wr) for v in value["conditions"]]
        return all(predicates) if value["logic"] == "and" else any(predicates)
    if value.get("mode", "exact") != "exact":
        raise wr.ReplayError("unsupported_transition_semantics")
    operator = value.get("operator")
    if operator == "always":
        return True
    if operator == "equals":
        return str(variables.get(value["variable"], "")) == str(value["operand"])
    if operator == "greater_than":
        return float(variables.get(value["variable"], 0)) > float(value["operand"])
    raise wr.ReplayError("unsupported_transition_semantics")


def contract_actor(base, arm):
    """Translate the same authored public speech to each declared A schema.

    No new answer, expected value or policy outcome enters this adapter. Opening
    and security outputs are derived from the original authored event and facts,
    using only the actual current schema descriptions of these new candidates.
    """
    class ContractActor(base):
        def next(self, variables):
            state = variables.get("state", {})
            if isinstance(state, str):
                state = json.loads(state)
            phase = state.get("phase", "recipient")
            result = super().next(variables)
            if self.case["brief"] != "A" or arm == "frozen":
                return result
            if phase == "recipient":
                act = result["event"].split(";", 1)[0].removeprefix("k=")
                return {"recipient_act": act, "raw": result["raw"], "admin": result["admin"]}
            if phase in {"dob", "phone"}:
                tags = dict(p.split("=", 1) for p in result["event"].split(";")[:-1])
                if tags.get("k") != "security" or tags.get("c") != "1" or "v" not in tags:
                    raise ValueError("unsupported_security_actor_mapping")
                fields = ({"security_answer_event": tags["v"]} if arm == "classic" else
                          {"security_act": "answer", "security_value": tags["v"]})
                return dict(fields, raw=result["raw"], admin=result["admin"])
            return result
    return ContractActor


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--classic-report", type=Path)
    p.add_argument("--v2-report", type=Path)
    p.add_argument("--shared-release", type=Path,
                   help="Reproduce from shared candidate and frozen A10/B14 without ignored raw runs")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    a = p.parse_args()
    if bool(a.shared_release) == bool(a.classic_report or a.v2_report):
        p.error("Supply shared release OR both paired local reports")
    if not a.shared_release and not (a.classic_report and a.v2_report):
        p.error("Both paired local reports required")
    if a.output.exists():
        raise ValueError("Do not overwrite comparison evidence")
    if not a.worker:
        environment = {k: v for k, v in os.environ.items() if k.upper() in
                       {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "USERNAME", "PYTHONUTF8"}}
        command = [sys.executable, "-X", "utf8", "-B", str(Path(__file__).resolve()),
                   "--worker", "--output", str(a.output.resolve())]
        if a.shared_release:
            command += ["--shared-release", str(a.shared_release.resolve())]
        else:
            command += ["--classic-report", str(a.classic_report.resolve()),
                        "--v2-report", str(a.v2_report.resolve())]
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True,
                                text=True, encoding="utf-8", timeout=90)
        print(result.stdout.strip())
        if result.returncode:
            print(result.stderr[-1800:])
        return result.returncode
    driver = load("comparison_public_driver", ROOT / "scripts/local_public_replay.py")
    driver.deny_network()
    base_actor = driver.Actor
    driver.exact_condition = documented_condition
    sys.path.insert(0, str(ROOT / "integrations/customer-datasets"))
    wr = load("comparison_workflow_replay", ROOT / "integrations/customer-datasets/workflow_replay.py")
    sys.path.insert(0, str(ROOT / "competition"))
    from validation import validate, validate_coverage
    score = load("comparison_original_scorer", driver.KIT / "tools/score.py").score_ledger
    public = json.loads((driver.KIT / "public-test-set.json").read_text(encoding="utf-8"))
    frozen = ROOT / "competition/releases/classic-baseline/b.review-template.json"
    if sha(frozen) != driver.PINS["B"][1]:
        raise ValueError("Frozen B pin mismatch")
    b_workflow = json.loads(frozen.read_text(encoding="utf-8"))["workflow"]
    paths = [Path(__file__).resolve(), frozen, driver.KIT / "public-test-set.json",
             driver.KIT / "tools/score.py", ROOT / "scripts/local_public_replay.py",
             ROOT / "integrations/customer-datasets/workflow_replay.py",
             ROOT / "research/field-cases/local_runner.py"]
    arms = {}
    if a.shared_release:
        release = a.shared_release.resolve()
        release_source = release / "release.json"
        meta = json.loads(release_source.read_text(encoding="utf-8"))
        if meta["status"] != "UNPUBLISHED_AUTOMATIC_LOCAL_CANDIDATE" or meta["hosted_evaluated"]:
            raise ValueError("Shared release scope mismatch")
        baseline = ROOT / "competition/releases/classic-baseline/a.review-template.json"
        if sha(baseline) != driver.PINS["A"][1]:
            raise ValueError("Frozen A pin mismatch")
        paths += [release_source, baseline]
        arms["classic"] = {"source": {"run_id": "frozen_A10_B14", "status": "FROZEN_CLASSICAL_BASELINE"},
                           "workflow": json.loads(baseline.read_text(encoding="utf-8"))["workflow"],
                           "diagnostic_only": False, "actor_contract": "frozen"}
        selected = [("v2", release_source)]
    else:
        paths += [a.classic_report, a.v2_report]
        selected = [("classic", a.classic_report), ("v2", a.v2_report)]
    for arm, source in selected:
        report = ({"published": False, "status": "COMPLETED_LOCAL_VALIDATION", "finetuned_model_ready": True,
                   "run_id": meta["source_run"], "artifact_sha256": meta["files_sha256"]}
                  if a.shared_release else json.loads(source.read_text(encoding="utf-8")))
        if report["published"] is not False:
            raise ValueError("Unpublished local generation required")
        if arm == "v2" and report["status"] != "COMPLETED_LOCAL_VALIDATION":
            raise ValueError("Completed V2 generation required")
        if arm == "v2" and not report["finetuned_model_ready"]:
            raise ValueError("V2 was not actually invoked")
        path = (release / "workflow.json" if a.shared_release else
                ROOT / "competition/runs" / report["run_id"] / "work/workflow.json")
        if report.get("artifact_sha256") and sha(path) != report["artifact_sha256"]["workflow.json"]:
            raise ValueError("Generated workflow changed")
        paths.append(path)
        workflow = json.loads(path.read_text(encoding="utf-8"))
        coverage_path = path.parent / "coverage.json"
        paths.append(coverage_path)
        errors = validate(workflow, wr.b.local.API) + validate_coverage(json.loads(coverage_path.read_text(encoding="utf-8")))
        if errors:
            raise ValueError("Local snapshot validation failed: " + arm + " " + json.dumps(errors))
        arms[arm] = {"source": report, "workflow": workflow,
                     "diagnostic_only": report["status"] != "COMPLETED_LOCAL_VALIDATION",
                     "actor_contract": arm}
    before = {x.resolve().relative_to(ROOT).as_posix(): sha(x) for x in paths}
    results = {}
    for arm, value in arms.items():
        driver.Actor = contract_actor(base_actor, value["actor_contract"])
        rows = []
        for repeat in range(1, 4):
            for case in public:
                workflow = value["workflow"] if case["brief"] == "A" else b_workflow
                row = driver.execute(workflow, driver.fixture(case, repeat), case, repeat, wr, score)
                row["workflow_version"] = None if case["brief"] == "A" else driver.PINS["B"][0]
                row["candidate_scope"] = ("stopped classic snapshot diagnostic" if value["diagnostic_only"] else "new unpublished A repair") if case["brief"] == "A" else "identical frozen B control"
                row["arm"] = arm
                rows.append(row)
        results[arm] = {"run_id": value["source"]["run_id"], "executions": len(rows),
                        "original_generation_status": value["source"]["status"],
                        "diagnostic_only": value["diagnostic_only"], "snapshot_validation_errors": [],
                        "conditional_kernel_ledger_passes": sum(r["conditional_kernel_ledger_pass"] for r in rows),
                        "completed_executions": sum(r["execution_status"] == "completed" for r in rows),
                        "A_passes": sum(r["conditional_kernel_ledger_pass"] for r in rows if r["brief"] == "A"),
                        "A_executions": 30, "B_frozen_control_passes": sum(r["conditional_kernel_ledger_pass"] for r in rows if r["brief"] == "B"),
                        "case_summary": [{"id": case["id"], "passes": sum(r["conditional_kernel_ledger_pass"] for r in rows if r["id"] == case["id"]),
                                         "errors": sorted({r["runner_error"] for r in rows if r["id"] == case["id"] and r["runner_error"]})}
                                        for case in public], "results": rows}
    if before != {x.resolve().relative_to(ROOT).as_posix(): sha(x) for x in paths}:
        raise ValueError("Replay sources changed")
    output = {"status": "COMPLETED_LOCAL_CONDITIONAL_COMPARISON", "source_sha256": before,
              "scope": ("Frozen A10 classical baseline vs shared V2-assisted A candidate, identical B14 control. " if a.shared_release else
                        "Stopped classic A source snapshot diagnostic and completed actual V2-assisted A repair, identical frozen B control. The failed classic generation remains FAILED; source validation and kernel scores never promote it to completed. ") +
                       "13 cases x3 per arm. Authored correct-contract events, not extraction/voice/judge or independent-repeat qualification. This is not a causal experiment.",
              "Freya_calls": 0, "extractor_executed": False, "conversation_judge_executed": False,
              "actor_adapter": "Same public script/facts and authored speech. Schema-only mapping to recipient_act and complete security_answer_event or security_act/security_value. Original expectations untouched.",
              "bank_authority": "original deterministic workflow with a local Bank; model proposals have no authority",
              "arms": results}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {n: v[n] for n in ("executions", "conditional_kernel_ledger_passes", "A_passes", "B_frozen_control_passes", "completed_executions")}
                      for k, v in results.items()}), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
