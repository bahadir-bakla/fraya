"""One parent-source-bound CPU experiment: fresh MiniLM task head + two students."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import numpy as np
from safetensors.numpy import load_file, save_file
from threadpoolctl import threadpool_limits
from repayment_data import ROOT, HERE, PACKET, sha, verify, write_new, encoded, load_rows, arrays, snapshot
from repayment_preflight import PLAN, versions, get_encoder
from repayment_runtime import observed_text, features
from repayment_model import SEED, init_student, init_teacher, Adam, support, objective, forward, sigmoid
from repayment_eval import score, calibrate, student_blob, export_parity, slices

REPORT = ROOT / "analysis/repayment-model-experiment.json"
MARKER = ROOT / "analysis/repayment-model-execution-once.json"


def rel(path): return Path(path).relative_to(ROOT).as_posix()


def checked_plan(digest):
    if sha(PLAN) != digest: raise ValueError("External exact plan digest mismatch")
    p = json.loads(PLAN.read_text(encoding="utf-8"))
    for key in ("source_sha256", "input_sha256", "historical_sha256"): verify(p[key])
    if versions() != p["versions"] or sys.executable != p["python_executable"]: raise ValueError("Runtime versions changed")
    return p


def fit(p, x, y, m, gw, q, trained, epochs, arm, deadline, teacher=None):
    den = (m * gw[:, None] * np.where(y > .5, q, 1.)).sum(0); den[~trained] = 0
    kl_den = (m * gw[:, None]).sum(0); kl_den[~trained] = 0
    opt = Adam(p, .01 if "E" not in p else .003); rng = np.random.default_rng(SEED + 2)
    started = time.monotonic(); history = []
    initial = objective(p, x, y, m, gw, q, den, arm, teacher, kl_den)[2]
    stages = {"initial": initial}; processed = 0
    for epoch in range(epochs):
        order = rng.permutation(len(y)); losses = []
        for off in range(0, len(y), 32):
            if time.monotonic() >= deadline: raise TimeoutError("Bounded CPU fit timed out; no retry/eval")
            ix = order[off:off + 32]; ratio = len(ix) / len(y)
            loss, grads, stats = objective(p, x[ix], y[ix], m[ix], gw[ix], q, den * ratio, arm,
                                None if teacher is None else teacher[ix], kl_den * ratio)
            norm = np.sqrt(sum(float((v.astype(np.float64) ** 2).sum()) for v in grads.values()))
            if norm > 1: grads = {k: v / norm for k, v in grads.items()}
            opt.update(p, grads); processed += len(ix); losses.append(loss)
        if epoch in (0, epochs // 2 - 1, epochs - 1):
            loss, _, stats = objective(p, x, y, m, gw, q, den, arm, teacher, kl_den)
            history.append({"completed_epochs": epoch + 1, "full_objective": loss, **stats})
            print(json.dumps({"stage": "FIT", "arm": "teacher" if "E" not in p else arm, "epoch": epoch + 1, "loss": loss}), flush=True)
    z, _ = forward(p, x)
    return {"completed_epochs": epochs, "processed_rows": processed, "fit_seconds": time.monotonic() - started,
            "loss_trajectory": history, "initial_gradient": initial, "final_TRAIN": score(sigmoid(z), y, m, LABELS)}


def detailed(z, y, m, rows, labels, cal):
    raw = sigmoid(z); prob = sigmoid(z / np.asarray(cal["temperature"])); threshold = np.asarray(cal["threshold"])
    result = {"raw": score(raw, y, m, labels), "calibrated_selective": score(prob, y, m, labels, threshold),
              "per_canonical_group": {}, "diagnostic_slices": slices(prob, y, m, labels, rows, threshold)}
    known = m.astype(bool)
    result["raw_BCE_known"] = float(((np.logaddexp(0, z) - y * z) * m).sum() / max(1, m.sum()))
    result["raw_multilabel_exact_match_rows"] = float((((raw >= .5) == (y > .5)) | ~known).all(1).mean())
    for group in sorted(set(r["group_id"] for r in rows)):
        ix = np.array([r["group_id"] == group for r in rows]); result["per_canonical_group"][group] = score(prob[ix], y[ix], m[ix], labels, threshold)
    # Descriptive observable lexical/multiact subsets, never used for model selection.
    tags = {"lexical_negation": np.array([any(w in r["input"]["current_utterance"]["text"].casefold().split() for w in ("no", "not", "never", "don't")) for r in rows]),
            "multiple_annotated_acts": (y * m).sum(1) > 1,
            "reported_third_party": y[:, labels.index("reported_third_party")] > .5,
            "uncertain": y[:, labels.index("uncertain")] > .5}
    result["slices_descriptive_not_runtime_features"] = {tag: score(prob[ix], y[ix], m[ix], labels, threshold) for tag, ix in tags.items() if ix.any()}
    return result


def worker(digest):
    global LABELS
    started = time.monotonic(); plan = checked_plan(digest); LABELS = plan["labels"]
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    if marker["approved_plan_sha256"] != digest: raise ValueError("Missing one-run marker")
    deadline = started + 850
    with threadpool_limits(limits=2):
        train = load_rows(ROOT / plan["files"]["train"], "train", LABELS)
        x, y, m, gw = arrays(train, LABELS); pos, neg, q, trained = support(y, m, gw)
        emb = load_file(str(HERE / "repayment_cache.train.safetensors"))["embeddings"]
        if emb.shape != (len(train), 384) or not np.isfinite(emb).all(): raise ValueError("TRAIN encoder cache mismatch")
        teacher = init_teacher(len(LABELS))
        result = {"approved_plan_sha256": digest, "labels": LABELS, "TRAIN_rows": len(train), "TRAIN_groups": len(set(r["group_id"] for r in train)),
              "models": {}, "qualified": False, "bank_authority": False, "GPU_USD": 0, "SGD_source_only_reference": plan["SGD_source_only_reference"]}
        result["models"]["teacher"] = fit(teacher, emb, y, m, gw, q, trained, 200, "hard", min(deadline, time.monotonic() + 120))
        raw_teacher, _ = forward(teacher, emb)
        targetpath = HERE / "repayment_teacher_raw_train.safetensors"
        save_file({"raw_logits": raw_teacher.astype(np.float32)}, str(targetpath), metadata={"TRAIN_input_sha256": sha(ROOT / plan["files"]["train"]), "calibration_applied": "false"})
        models = {"teacher": teacher}; blobs = {}; pins = {}
        for arm in ("hard", "distill"):
            p = init_student(len(LABELS)); models[arm] = p
            result["models"][arm] = fit(p, x, y, m, gw, q, trained, 400, arm, min(deadline, time.monotonic() + 180), raw_teacher)
            blob = student_blob(p, LABELS, arm); blobs[arm] = blob
            z, parity = export_parity(p, blob, train, x)
            result["models"][arm]["TRAIN_export_parity"] = parity
            modelpath = HERE / ("repayment_model." + arm + ".json")
            if len(blob) + (HERE / "repayment_runtime.py").stat().st_size > 500000: raise ValueError("Portable size limit exceeded")
            with modelpath.open("xb") as f: f.write(blob)
            pins[rel(modelpath)] = sha(modelpath)
            result["models"][arm]["model_plus_runtime_bytes"] = len(blob) + (HERE / "repayment_runtime.py").stat().st_size
        for name, p in models.items():
            path = HERE / ("repayment_state." + name + ".safetensors")
            if path.exists(): raise ValueError("Existing fit outputs: no retry/overwrite")
            save_file(p, str(path), metadata={"task": "repayment_semantic_proposal", "plan_sha256": digest, "bank_authority": "false"}); pins[rel(path)] = sha(path)
        pins[rel(targetpath)] = sha(targetpath)
        weightsfreeze = HERE / "repayment_weights.freeze.json"
        write_new(weightsfreeze, {"status": "FROZEN_BEFORE_CAL_TARGET_READ", "models_sha256": pins, "source_sha256": plan["source_sha256"], "plan_sha256": digest})
        # CAL targets enter calibration/scoring only after all fitted models freeze.
        calrows = load_rows(ROOT / plan["files"]["calibration"], "calibration", LABELS)
        cx, cy, cm, _ = arrays(calrows, LABELS); encoder = get_encoder(ROOT / plan["encoder"]["directory"])
        texts = [observed_text(snapshot(r)) for r in calrows]
        if any(len(encoder.tokenizer(t, truncation=False)["input_ids"]) > 256 for t in texts): raise ValueError("CAL encoder truncation unsupported")
        ce = encoder.encode(texts, deadline=deadline)
        fit_ix = np.array([i for i,r in enumerate(calrows) if r["family_id"].split("-")[0] in ("C01", "C03", "C07")])
        select_ix = np.array([i for i,r in enumerate(calrows) if r["family_id"].split("-")[0] in ("C02", "C06", "C08")])
        if set(fit_ix) & set(select_ix) or len(fit_ix) + len(select_ix) != len(calrows): raise ValueError("CAL role coverage/overlap")
        if {calrows[i]["group_id"] for i in fit_ix} & {calrows[i]["group_id"] for i in select_ix}: raise ValueError("CAL canonical role leakage")
        calibrators = {}; calibrationpins = dict(pins)
        for name, p in models.items():
            z, _ = forward(p, ce if name == "teacher" else cx)
            if name != "teacher": z, parity = export_parity(p, blobs[name], calrows, cx); result["models"][name]["CAL_export_parity"] = parity
            calibrators[name] = calibrate(z, cy, cm, trained, fit_ix, select_ix)
            path = HERE / ("repayment_calibrator." + name + ".json"); write_new(path, calibrators[name]); calibrationpins[rel(path)] = sha(path)
            result["models"][name]["CAL"] = detailed(z, cy, cm, calrows, LABELS, calibrators[name])
        freeze = HERE / "repayment_freeze.json"
        write_new(freeze, {"status": "FROZEN_BEFORE_ONCE_HELDOUT", "plan_sha256": digest, "source_sha256": plan["source_sha256"],
              "input_sha256": plan["input_sha256"], "artifacts_sha256": calibrationpins, "bank_authority": False, "qualified": False})
        write_new(ROOT / "analysis/repayment-model-heldout-once.json", {"freeze_sha256": sha(freeze), "passes": 1})
        heldout = load_rows(ROOT / plan["files"]["eval"], "eval", LABELS)
        hx, hy, hm, _ = arrays(heldout, LABELS); ht = [observed_text(snapshot(r)) for r in heldout]
        if any(len(encoder.tokenizer(t, truncation=False)["input_ids"]) > 256 for t in ht): raise ValueError("HELDOUT encoder truncation unsupported")
        he = encoder.encode(ht, deadline=deadline)
        noctx = [{"input": {"current_utterance": r["input"]["current_utterance"], "previous_utterances": []}} for r in heldout]
        ne = encoder.encode([observed_text(snapshot(r)) for r in noctx], deadline=deadline)
        nx = np.zeros_like(hx)
        for i, row in enumerate(noctx):
            for j,v in features(snapshot(row)).items(): nx[i,j] = v
        predictions = {}
        for name, p in models.items():
            z, _ = forward(p, he if name == "teacher" else hx)
            if name != "teacher": z, parity = export_parity(p, blobs[name], heldout, hx, calibrators[name]); result["models"][name]["HELDOUT_export_parity"] = parity
            result["models"][name]["HELDOUT"] = detailed(z, hy, hm, heldout, LABELS, calibrators[name]); predictions[name] = z >= 0
            nz, _ = forward(p, ne if name == "teacher" else nx)
            result["models"][name]["HELDOUT_no_context_diagnostic"] = detailed(nz, hy, hm, heldout, LABELS, calibrators[name])
        result["hard_vs_distill_raw_disagree_elements"] = int((predictions["hard"] != predictions["distill"]).sum())
        result["source_OOD"] = "Unsupported: 6 authored heldout roots only; no independent OOD/ASR/Freya or bank safety labels"
        result["scope"] = plan["scope"]; result["freeze_sha256"] = sha(freeze); result["wall_seconds"] = time.monotonic() - started
        result["status"] = "COMPLETED_ACTUAL_THREE_FITS_AND_ONCE_AUTHORED_HELDOUT"
        verify(plan["historical_sha256"]); verify(plan["source_sha256"]); verify(plan["input_sha256"]); verify(calibrationpins)
        write_new(REPORT, result)
        (ROOT / "analysis/repayment-model-experiment.txt").write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": result["status"], "wall_seconds": result["wall_seconds"], "heldout_raw_macroF1": {n: v["HELDOUT"]["raw"]["macro_F1_known_heads"] for n,v in result["models"].items()}}), flush=True)


def launch(digest):
    checked_plan(digest); write_new(MARKER, {"approved_plan_sha256": digest, "basis": "standing human CPU authorization; exact-source parent execution", "automatic_retries": 0})
    started = time.monotonic()
    try:
        p = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--worker", "--approved-plan-sha", digest], cwd=str(ROOT), timeout=900)
        status = {"exit_code": p.returncode, "wall_seconds": time.monotonic() - started, "retries": 0}
    except subprocess.TimeoutExpired: status = {"status": "child_killed_and_waited_timeout", "wall_seconds": time.monotonic() - started, "retries": 0}
    write_new(ROOT / "analysis/repayment-model-watchdog.json", status)
    if status.get("exit_code") != 0:
        if not REPORT.exists(): write_new(REPORT, {"status": "FAILED_NO_RETRY", "watchdog": status, "plan_sha256": digest})
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true"); group.add_argument("--worker", action="store_true")
    parser.add_argument("--approved-plan-sha", required=True); args = parser.parse_args()
    if args.worker: worker(args.approved_plan_sha)
    else: launch(args.approved_plan_sha)
