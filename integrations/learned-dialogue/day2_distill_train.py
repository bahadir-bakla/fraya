"""Prepare exact pins; after parent grant run one watchdog-bounded TRAIN pair."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from safetensors.numpy import load_file, save_file
from threadpoolctl import threadpool_limits
from day2_distill_data import ROOT, PINS, load_train, sha, identity, encoded, write_new, check_pins
from day2_distill_runtime import features
from day2_distill_model import init, Adam, objective, SEED
from day2_distill_eval import metrics, parity

HERE = Path(__file__).parent
PLAN = HERE / "day2_distill_plan.json"
LOGITS = HERE / "day2_distill_teacher_train_logits.safetensors"
INDEX = HERE / "day2_distill_teacher_train_index.json"
REPORT = ROOT / "analysis/day2-distill-experiment.json"
MARKER = ROOT / "analysis/day2-distill-execution-once.json"
SOURCES = [HERE / ("day2_distill_" + n + ".py") for n in ("runtime", "data", "model", "eval", "test", "train")]


def versions():
    return {n: importlib.metadata.version(n) for n in ("numpy", "safetensors", "threadpoolctl")}


def rel(path):
    return Path(path).relative_to(ROOT).as_posix()


def historical():
    path = HERE / "day2_multisource_freeze.json"
    if sha(path) != "86094cd5eaef0e8df206b41bcebe13a0d431e9b888ae42942e5cc6997d185be3":
        raise ValueError("Historical freeze changed")
    f = json.loads(path.read_text(encoding="utf-8"))
    pins = {rel(path): sha(path)}
    for key in ("historical_sha256", "input_sha256", "source_sha256", "artifacts_sha256"):
        pins.update(f[key])
    for record in f["models"].values():
        pins[record["model_path"]] = record["model_sha256"]
        pins[record["native_state_path"]] = record["native_state_sha256"]
    check_pins(pins)
    return pins


def probes(y):
    first = [int(np.flatnonzero(y == k)[0]) for k in range(77)]
    other = np.random.default_rng(SEED + 1).choice(len(y), 77, replace=False).tolist()
    return sorted(set(first + other))


def prepare():
    if any(p.exists() for p in (PLAN, LOGITS, INDEX)):
        raise ValueError("Write-once preparation exists; do not regenerate")
    start = time.monotonic()
    old = historical()
    with threadpool_limits(limits=2):
        rows, labels, z = load_train()
        from day2_distill_test import run
        tests = run(rows, labels, z)
    order = identity(rows)
    save_file({"raw_train_logits": z}, str(LOGITS), metadata={"split": "train", "input_sha256": PINS[next(iter(PINS))],
              "ordered_identity_sha256": order, "teacher_head_sha256": PINS["integrations/learned-dialogue/day2_pretrained_head.json"], "calibration_applied": "false"})
    write_new(INDEX, {"split": "train", "ordered_identity_sha256": order,
              "records": [{"record_id": r["record_id"], "group_id": r["group_id"], "text_sha256": hashlib.sha256(r["text"].encode()).hexdigest(), "source_label_id": r["source_label_id"]} for r in rows]})
    group = Counter(r["group_id"] for r in rows)
    y = np.array([r["source_label_id"] for r in rows])
    masks = {"publisher_intent_known": len(rows), "unknown_publisher_intent": 0, "bank_authority": 0,
             "deployment_qualified": 0, "ancestry_qualification": "not asserted; existing construction groups only"}
    pins = dict(PINS); pins.update({rel(LOGITS): sha(LOGITS), rel(INDEX): sha(INDEX),
               "analysis/day2-multisource-remedy-design.json": sha(ROOT / "analysis/day2-multisource-remedy-design.json")})
    plan = {"status": "READY_FOR_PARENT_GRANT", "created_utc": datetime.now(timezone.utc).isoformat(),
       "source_sha256": {rel(p): sha(p) for p in SOURCES}, "input_sha256": pins, "historical_sha256": old,
       "python_executable": sys.executable, "versions": versions(), "training": {"rows": 7943, "classes": 77,
       "groups": len(group), "class_counts": np.bincount(y, minlength=77).tolist(), "ordered_identity_sha256": order,
       "partitions": "existing TRAIN only; no new split or CAL/EVAL optimizer rows", "masks": masks,
       "cache_provenance": "Exact immutable input/cache/teacher-trainer pins + safetensors metadata. Original pinned trainer features() encodes ordered load_split rows without reordering. Legacy embedding cache has no per-row IDs; new index binds that documented order, not an independent regenerated encoder witness."},
       "architecture": {"features": "text-only-sha256-signed-1024-v1", "width": 1024, "hidden": 32, "labels": labels, "parameters": 35341},
       "optimizer": {"seed": SEED, "max_epochs": 40, "batch": 256, "Adam_lr": .003, "Adam_betas": [.9, .999], "Adam_eps": 1e-8,
       "same_initialization_and_batches": True, "L2": ".5*.01*mean(all nonbias parameters squared)", "hard": "unscaled group-mean CE + L2",
       "distill": ".5 group-mean CE + .5*2^2 group-mean KL(softmax(raw_teacher/2)||softmax(student/2)) + L2"},
       "budget": {"wall_seconds": 360, "pin_cache_seconds": 30, "each_arm_seconds": 140, "diagnostics_seconds": 50, "threads": 2, "retries": 0, "GPU": False},
       "freeze_contract": "TRAIN-only final states, runtime, evaluator, labels and plan freeze before any later CAL/EVAL diagnostic. Partial pair incomparable unless same completed epochs; no best heldout selection.",
       "export": {"max_model_plus_runtime_bytes_each": 500000, "format": "base64 little-endian float32, stdlib decoder", "TRAIN_probe_indices": probes(y)},
       "scope": "Openly unqualified exposed publisher-source intent auxiliary. No bank policy, permission, identity, ledger authority; all runtime proposals abstain until separate calibration and source qualification. Existing banking admission floor unchanged.",
       "tests": tests, "prepare_seconds": time.monotonic() - start,
       "execution": "One --fit --approved-plan-sha matching this file's externally reviewed digest; parent supplies grant. No prior grant accepted."}
    write_new(PLAN, plan)
    report = {"status": plan["status"], "plan_sha256": sha(PLAN), "plan_path": rel(PLAN), "source_sha256": plan["source_sha256"],
              "input_sha256": pins, "historical_pins_verified": len(old), "rows": len(rows), "groups": len(group),
              "teacher_logit_shape": list(z.shape), "teacher_top1_TRAIN_accuracy": float((z.argmax(1) == y).mean()),
              "masks": masks, "tests": tests, "optimizer_steps": 0, "new_fitted_weights": 0, "CAL_EVAL_rows_loaded": 0,
              "command": '"' + sys.executable + '" -B integrations/learned-dialogue/day2_distill_train.py --fit --approved-plan-sha ' + sha(PLAN)}
    write_new(ROOT / "analysis/day2-distill-plan.json", report)
    (ROOT / "analysis/day2-distill-plan.txt").write_text("READY_FOR_PARENT_GRANT\nPlan SHA256: " + sha(PLAN) + "\n" + report["command"] +
        "\n7943 TRAIN-only raw quantized-teacher logits; no CAL temperature/threshold used. Two fresh matched students, 40 epochs maximum, CPU2, watchdog360s.\n" +
        str(tests["checks_passed"]) + " source/cache/gradient/export checks; no optimizer steps. Both freeze before later diagnostic CAL/EVAL. No bank authority/qualification.\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True), flush=True)


def verify_plan(digest):
    if sha(PLAN) != digest:
        raise ValueError("External approved plan hash mismatch")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for key in ("source_sha256", "input_sha256", "historical_sha256"):
        check_pins(plan[key])
    if versions() != plan["versions"] or sys.executable != plan["python_executable"]:
        raise ValueError("Execution environment differs from frozen plan")
    return plan


def fit_worker(digest):
    started = time.monotonic(); plan = verify_plan(digest)
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    if marker["approved_plan_sha256"] != digest:
        raise ValueError("Missing one-run execution marker")
    with threadpool_limits(limits=2):
        rows, labels, recalculated = load_train()
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        if identity(rows) != index["ordered_identity_sha256"] or identity(rows) != plan["training"]["ordered_identity_sha256"]:
            raise ValueError("Cached TRAIN order mismatch")
        teacher = load_file(str(LOGITS))["raw_train_logits"]
        if not np.array_equal(teacher, recalculated):
            raise ValueError("Pinned teacher logits differ from raw recomputation")
        x = np.zeros((7943, 1024), np.float32)
        for i, r in enumerate(rows):
            for j, v in features(r["text"]).items(): x[i, j] = v
        y = np.asarray([r["source_label_id"] for r in rows], np.int64)
        groups = Counter(r["group_id"] for r in rows)
        weights = np.asarray([len(rows) / (len(groups) * groups[r["group_id"]]) for r in rows], np.float32)
        if time.monotonic() - started > 30:
            raise TimeoutError("Pin/cache preparation exceeded30s; no fits")
        result = {"approved_plan_sha256": digest, "TRAIN_rows": len(rows), "TRAIN_groups": len(groups), "models": {},
                  "CAL_EVAL_rows_loaded": 0, "bank_acceptance": 0, "qualified": False, "teacher_calibration_used": False}
        modelpaths = []
        for arm in ("hard", "distill"):
            p = init(); opt = Adam(p); rng = np.random.default_rng(SEED + 2)
            arm_start = time.monotonic(); epochs = 0; seen = 0; history = []
            initial = metrics(p, x, y, teacher, weights)
            probe = np.array(plan["export"]["TRAIN_probe_indices"])
            stages = {"initialized": objective(p, x[probe], y[probe], teacher[probe], weights[probe], arm)[2]}
            last_complete = {k: v.copy() for k, v in p.items()}
            interrupted = False
            for epoch in range(40):
                order = rng.permutation(len(y)); losses = []
                for offset in range(0, len(y), 256):
                    if time.monotonic() - arm_start >= 140 or time.monotonic() - started >= 310:
                        interrupted = True; break
                    ix = order[offset:offset + 256]
                    loss, grads, _ = objective(p, x[ix], y[ix], teacher[ix], weights[ix], arm)
                    opt.update(p, grads); seen += len(ix); losses.append(loss)
                if interrupted:
                    p = last_complete; break
                epochs += 1; last_complete = {k: v.copy() for k, v in p.items()}
                history.append({"epoch": epochs, "mean_batch_objective": float(np.mean(losses))})
                if epochs == 20: stages["mid_epoch20"] = objective(p, x[probe], y[probe], teacher[probe], weights[probe], arm)[2]
                if epochs in (1, 20, 40):
                    print(json.dumps({"stage": "TRAIN", "arm": arm, "epoch": epochs, "loss": history[-1]["mean_batch_objective"]}), flush=True)
            fit_seconds = time.monotonic() - arm_start
            final = metrics(p, x, y, teacher, weights)
            stages["final"] = objective(p, x[probe], y[probe], teacher[probe], weights[probe], arm)[2]
            blob, parityreport = parity(p, rows, x, labels, plan["export"]["TRAIN_probe_indices"], arm)
            modelpath = HERE / ("day2_distill_model." + arm + ".json")
            statepath = HERE / ("day2_distill_state." + arm + ".safetensors")
            if modelpath.exists() or statepath.exists(): raise ValueError("Output exists; no overwrite")
            if len(blob) + (HERE / "day2_distill_runtime.py").stat().st_size > 500000:
                raise ValueError("Export footprint exceeded")
            with modelpath.open("xb") as f: f.write(blob)
            save_file(p, str(statepath), metadata={"arm": arm, "plan_sha256": digest, "TRAIN_only": "true"})
            modelpaths += [modelpath, statepath]
            result["models"][arm] = {"completed_epochs": epochs, "partial": interrupted, "processed_rows_including_discarded_partial_epoch": seen,
                "fit_seconds": fit_seconds, "initial_TRAIN": initial, "final_TRAIN": final, "loss_trajectory": history,
                "gradient_stages": stages, "export_parity": parityreport, "model_plus_runtime_bytes": len(blob) + (HERE / "day2_distill_runtime.py").stat().st_size}
        result["matched_completed_epochs"] = result["models"]["hard"]["completed_epochs"] == result["models"]["distill"]["completed_epochs"]
        result["comparison_status"] = "matched_TRAIN_diagnostic_only" if result["matched_completed_epochs"] else "partial_pair_incomparable"
        result["wall_seconds"] = time.monotonic() - started
        result["status"] = "completed" if all(v["completed_epochs"] == 40 for v in result["models"].values()) else "partial"
        result["heldout_distillation_benefit"] = "unmeasured; no CAL/EVAL reads or selection"
        check_pins(plan["historical_sha256"])
        freeze = {"status": "FROZEN_BEFORE_LATER_CAL_EVAL", "approved_plan_sha256": digest, "source_sha256": plan["source_sha256"],
                  "input_sha256": plan["input_sha256"], "models_sha256": {rel(p): sha(p) for p in modelpaths},
                  "epochs": {k: v["completed_epochs"] for k, v in result["models"].items()}, "qualified": False}
        freeze_path = HERE / "day2_distill_freeze.json"; write_new(freeze_path, freeze)
        result["freeze_sha256"] = sha(freeze_path)
        write_new(REPORT, result)
        (ROOT / "analysis/day2-distill-experiment.txt").write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=True), flush=True)


def launch(digest):
    verify_plan(digest)
    write_new(MARKER, {"approved_plan_sha256": digest, "status": "one_execution_started", "utc": datetime.now(timezone.utc).isoformat()})
    started = time.monotonic()
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", "--approved-plan-sha", digest]
    try:
        proc = subprocess.run(command, cwd=str(ROOT), timeout=360, check=False)
        status = {"exit_code": proc.returncode, "wall_seconds": time.monotonic() - started, "automatic_retries": 0}
    except subprocess.TimeoutExpired:
        status = {"status": "watchdog_timeout_child_killed_and_waited", "wall_seconds": time.monotonic() - started, "automatic_retries": 0}
    write_new(ROOT / "analysis/day2-distill-watchdog.json", status)
    if status.get("exit_code") != 0:
        if not REPORT.exists(): write_new(REPORT, {"status": "failed_or_timeout", "approved_plan_sha256": digest, "watchdog": status, "no_retry": True})
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--prepare", action="store_true"); stage.add_argument("--fit", action="store_true"); stage.add_argument("--worker", action="store_true")
    parser.add_argument("--approved-plan-sha")
    args = parser.parse_args()
    if args.prepare: prepare()
    elif not args.approved_plan_sha: parser.error("External reviewed plan SHA required")
    elif args.worker: fit_worker(args.approved_plan_sha)
    else: launch(args.approved_plan_sha)
