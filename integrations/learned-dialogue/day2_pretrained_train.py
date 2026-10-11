"""Pinned public frozen-encoder baseline. --prepare never fits a classifier.

--run requires the reviewed plan SHA and an explicit later human grant. All
classifier fitting uses TRAIN only; CAL controls temperature/abstention only;
head/calibration/code/source hashes freeze before the single internal EVAL pass.
No checkpoint with a BANKING77-trained head, pickle, remote code or GPU is used.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
import urllib.request
import warnings

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "research/customer-benchmark/day2-training-data"
CACHE = ROOT / "local-runs/customer-benchmark-day2-pretrained"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MODEL = "sentence-transformers/all-MiniLM-L6-v2"
ENCODER = CACHE / "encoder" / REVISION
PUBLIC_CACHE = Path(r"C:/Users/9bakl/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots") / REVISION
PLAN = ROOT / "analysis/day2-pretrained-baseline-plan.json"
REPORT = ROOT / "analysis/day2-pretrained-baseline.json"
HEAD = Path(__file__).with_name("day2_pretrained_head.json")
FREEZE = Path(__file__).with_name("day2_pretrained_freeze.json")
RUNTIME = Path(__file__).with_name("day2_pretrained_runtime.py")
ALLOWED = ["README.md", "config.json", "config_sentence_transformers.json", "model.safetensors", "modules.json", "sentence_bert_config.json", "special_tokens_map.json", "tokenizer.json", "tokenizer_config.json", "vocab.txt", "1_Pooling/config.json"]
DATA_PINS = {
    "manifest.json": "e5c4da1d528da021aea8a1131b169ff000c8106b0955a35928405a1d55f65fb0",
    "train.jsonl": "cbe4f19f99e10065fb9c19c33c82b5e17fa76685c497a1f99d1c072e96692406",
    "calibration.jsonl": "cdaf6e6045e7fb13118bee7f4c3b07d2df5214b9ea3a46d5fbca4e22cf18870d",
    "eval.jsonl": "3c178ba644a4f5db7d58dedb3f4ca19009c4008a7958b3afdccbe2a84cf714db",
    "taxonomy.json": "338a9dae6fea33fa3f4a921d751633aa344f0f7f6a4386f3f6e38caedcc4c128",
}
OOD_PROBES = [
    "What is the weather forecast for Paris tomorrow?", "How do I bake a chocolate cake?",
    "Explain the difference between a planet and a star.", "Write a Python function that sorts a list.",
    "Who won the football match last night?", "How do I water my tomato plants?",
    "Please recommend a mystery novel.", "Translate good morning into Japanese.",
    "How do I change the oil in my car?", "What are the symptoms of influenza?",
    "Can you solve this algebra equation for me?", "Tell me the opening hours of the museum.",
    "Borcumu yarın ödeyeceğim.", "Taksit için ailemden izin almam gerekiyor.",
    "Ödeme sözü vermiyorum.", "Borcu ödediğimi sistemden doğrulayabilir misin?",
]
KNOWN_LIMITS = [
    "Two additional contraction-alias pairs cross the existing splits; no repartition/relabeling.",
    "Numeric redaction loses ages, amounts, durations and 3D security wording; secret regex erases some ordinary PIN/passcode status clauses including eval row 01708.",
    "Publisher labels are single-intent single-utterance labels with ambiguity, composite concerns and some answer-like rows; no all-paraphrase/IID/conversation-gold claim.",
    "Internal EVAL derives from publisher TRAIN. Publisher TEST is already exposed and is not read by this trainer.",
    "English source-intent benchmark; no safe bank policy/permission/ledger/debt-commitment/multiturn/Turkish/blind-OOD validation.",
    "OOD probes are predeclared authored diagnostics, not publisher, independent or blind OOD gold; no threshold selection on them.",
    "General MiniLM pretraining exposure cannot be ruled out exhaustively. No BANKING77-trained checkpoint head is reused.",
    "Full encoder is approximately 91 MB: offline teacher/reference only; not a Freya live bank tool or deployed compact model.",
]


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha(path):
    return sha_bytes(Path(path).read_bytes())


def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_json(path, obj):
    Path(path).write_bytes(encoded(obj))


def runtime():
    spec = importlib.util.spec_from_file_location("day2_pretrained_runtime_local", RUNTIME)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def versions():
    return {name: importlib.metadata.version(name) for name in ["torch", "transformers", "sentence-transformers", "scikit-learn", "safetensors", "numpy", "scipy", "threadpoolctl"]}


def verify_inputs():
    for name, expected in DATA_PINS.items():
        assert sha(PACKET / name) == expected, "Frozen input changed: " + name
    taxonomy = json.loads((PACKET / "taxonomy.json").read_text())
    labels = [r["source_label"] for r in taxonomy["labels"]]
    assert len(labels) == 77
    return labels


def load_split(split, labels):
    rr = [json.loads(line) for line in (PACKET / (split + ".jsonl")).read_text(encoding="utf-8").splitlines()]
    assert len(rr) == {"train": 7943, "calibration": 993, "eval": 993}[split]
    for r in rr:
        assert r["split"] == split and r["publisher_split"] == "train"
        assert labels[r["source_label_id"]] == r["source_label"]
        assert r["bank_policy_target"] is None and r["ledger_target"] is None
    return rr


def prepare():
    assert not PLAN.exists(), "Pre-fit plan already exists; do not overwrite it"
    labels = verify_inputs()
    # Explicit public metadata call: no credential, cookies, auth or env proxy discovery.
    url = f"https://huggingface.co/api/models/{MODEL}/revision/{REVISION}?blobs=true"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(url, headers={"User-Agent": "day2-public-pretrained-audit/1"}), timeout=15) as response:
        metadata_bytes = response.read(2_000_001)
    assert len(metadata_bytes) <= 2_000_000
    metadata = json.loads(metadata_bytes)
    assert metadata["sha"] == REVISION and metadata["cardData"]["license"] == "apache-2.0"
    siblings = {r["rfilename"]: r for r in metadata["siblings"]}
    records, total = {}, 0
    for name in ALLOWED:
        original = PUBLIC_CACHE / name
        assert original.is_file(), "Required pinned public cache file missing: " + name
        b = original.read_bytes()
        official = siblings[name]
        assert len(b) == official["size"]
        if "lfs" in official:
            assert sha_bytes(b) == official["lfs"]["sha256"]
        else:
            # Verify publisher content-object ID; no Git command/repository access.
            assert hashlib.sha1(b"blob " + str(len(b)).encode() + b"\0" + b).hexdigest() == official["blobId"]
        total += len(b)
        assert total < 200_000_000
        target = ENCODER / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert sha(target) == sha_bytes(b)
        else:
            target.write_bytes(b)
        records[name] = {"bytes": len(b), "sha256": sha_bytes(b), "publisher_blob_id": official["blobId"], "official_url": f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{name}"}
    assert 'local-runs/customer-benchmark*/' in (ROOT / ".gitignore").read_text()
    write_json(CACHE / "publisher-metadata.json", metadata)
    rt = runtime()
    encoder = rt.FrozenEncoder(ENCODER)
    smoke = encoder.encode(["Where is my card?", "I did not make this payment."])
    assert smoke.shape == (2, 384)
    model_record = {"model_id": MODEL, "revision": REVISION, "license": "Apache-2.0", "license_evidence": "Pinned official model-card metadata and README.md", "local_directory": ENCODER.relative_to(ROOT).as_posix(), "files": records, "total_encoder_files_bytes": total, "network_model_weight_bytes": 0, "network_metadata_bytes": len(metadata_bytes), "download_budget_bytes": 200_000_000, "provenance": "Already cached exact publisher revision; every allowlisted file verified against fresh public official revision metadata", "trust_remote_code": False, "token": False, "use_safetensors": True, "local_files_only_inference": True}
    plan = {
        "status": "READY_WAITING_FOR_EXPLICIT_PARENT_FIT_GRANT",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_hashes": {Path(__file__).relative_to(ROOT).as_posix(): sha(__file__), RUNTIME.relative_to(ROOT).as_posix(): sha(RUNTIME)},
        "input_hashes": DATA_PINS, "source": model_record, "versions": versions(), "python": sys.version,
        "encoder": {"width": 384, "frozen": True, "pooling": "attention-mask mean then L2 normalization", "max_wordpieces": 256, "batch_size": 32, "threads": 2, "device": "cpu", "no_gradient_updates": True},
        "classifier": {"implementation": "sklearn.linear_model.LogisticRegression", "C": 1.0, "solver": "lbfgs", "max_iter": 400, "tol": 1e-6, "fit_intercept": True, "class_weight": None, "random_state": 20261011, "target": "original publisher source_label_id", "training_rows": 7943, "candidate_fits": 1, "cal_select_C": False},
        "calibration": {"rows": 993, "temperature": "bounded scalar minimization of CAL NLL over T in [0.05,20], maxiter=60", "threshold": "fixed grid 0..1 in steps 0.01; maximize CAL coverage subject to empirical accepted precision>=0.95 and >=100 accepted; otherwise abstain all", "no_classifier_weight_optimization": True, "calibration_estimates_are_in_sample_not_guarantees": True},
        "export": {"format": "plain UTF-8 JSON, per-class symmetric int16 weights + float scales/intercepts", "maximum_head_bytes": 500_000, "cal_parity_gate": "max logit absolute difference<=0.005 and 100% predicted-label parity on all CAL rows before freeze", "temperature_threshold_in_head": True, "runtime": RUNTIME.relative_to(ROOT).as_posix()},
        "evaluation": {"rows": 993, "passes": 1, "read_labels_after_head_freeze_only": True, "metrics": ["macro_f1", "accuracy", "per_intent_recall", "confusion_matrix", "accepted_precision", "coverage", "export_parity"], "no_eval_selection": True, "eval_output_created_exclusively": True},
        "ood": {"queries": OOD_PROBES, "query_sha256": sha_bytes(encoded(OOD_PROBES)), "role": "authored nonblind diagnostic only", "no_selection": True},
        "wall_time_limit_run_seconds": 900, "grant_required": "Later explicit human parent grant naming or approving this exact plan SHA; initial request is not treated as fit grant", "scope_and_limits": KNOWN_LIMITS,
        "smoke_embedding_only": {"rows": 2, "shape": list(smoke.shape), "classifier_fits": 0},
    }
    write_json(PLAN, plan)
    plan_hash = sha(PLAN)
    lines = ["READY: exact public pretrained MiniLM encoder verified and CPU embedding smoke passed. No classifier fit performed.", "Plan SHA256: " + plan_hash, "Fixed C=1 multinomial logistic regression on 7943 TRAIN rows; frozen 384-wide encoder, CPU 2 threads.", "993 CAL only: temperature by NLL, confidence threshold maximizing coverage at empirical 95% precision with >=100 accepted.", "Freeze int16 JSON head, temperature, threshold and code/source/input hashes before the one 993-row internal EVAL pass.", "No BANKING77-trained pretrained head; no test reads, GPU, credentials, remote code, pickle/joblib, external inference or deployment.", "Model weights are already cached at exact official revision; 0 model-weight download bytes, " + str(total) + " local encoder bytes under existing ignored local-runs rule.", "All original corpus hashes locked. Known contraction leakage/redaction/label ambiguity disclosed. OOD probes are predeclared authored diagnostics only.", "Explicit later parent fit grant required. Exact trainer/runtime SHA256 values and all model/config/tokenizer/input hashes are in JSON."]
    (ROOT / "analysis/day2-pretrained-baseline-plan.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": plan["status"], "plan_sha256": plan_hash, "code_hashes": plan["code_hashes"], "encoder_bytes": total, "network_model_weight_bytes": 0}, indent=2), flush=True)


def selective(prob, y, threshold):
    import numpy as np
    accepted = prob.max(1) >= threshold
    pred = prob.argmax(1)
    count = int(accepted.sum())
    return {"threshold": float(threshold), "accepted": count, "rows": len(y), "coverage": float(accepted.mean()), "accepted_precision": float((pred[accepted] == y[accepted]).mean()) if count else None}


def metric(prob, y, threshold, labels):
    from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
    pred = prob.argmax(1)
    out = {"rows": len(y), "macro_f1": float(f1_score(y, pred, labels=list(range(77)), average="macro", zero_division=0)), "accuracy": float(accuracy_score(y, pred)), "per_intent_recall": dict(zip(labels, map(float, recall_score(y, pred, labels=list(range(77)), average=None, zero_division=0)))), "confusion_matrix": confusion_matrix(y, pred, labels=list(range(77))).tolist(), "abstention": selective(prob, y, threshold)}
    return out


def run(args):
    assert args.grant and args.plan_sha256, "Explicit reviewed-plan grant required"
    assert sha(PLAN) == args.plan_sha256, "Reviewed plan changed"
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    for path, expected in plan["code_hashes"].items():
        assert sha(ROOT / path) == expected, "Reviewed code changed"
    assert versions() == plan["versions"], "Reviewed library versions changed"
    assert not HEAD.exists() and not FREEZE.exists() and not REPORT.exists(), "Experiment output exists; no re-fit/eval overwrite permitted"
    write_json(ROOT / "analysis/day2-pretrained-baseline-grant.json", {"plan_sha256": args.plan_sha256, "human_grant_text": args.grant, "recorded_at_utc": datetime.now(timezone.utc).isoformat()})
    started = time.monotonic()
    deadline = started + plan["wall_time_limit_run_seconds"]
    labels = verify_inputs()
    for name, rec in plan["source"]["files"].items():
        assert sha(ENCODER / name) == rec["sha256"], "Pinned encoder changed"
    rt = runtime()
    import numpy as np
    from scipy.optimize import minimize_scalar
    from scipy.special import logsumexp
    from sklearn.linear_model import LogisticRegression
    from sklearn.exceptions import ConvergenceWarning
    from threadpoolctl import threadpool_limits
    from safetensors.numpy import save_file
    encoder = rt.FrozenEncoder(ENCODER)
    feature_records = {}

    def features(split, rr):
        x = encoder.encode([r["text"] for r in rr], deadline=deadline, progress=True)
        path = CACHE / (split + "-embeddings.safetensors")
        save_file({"embeddings": x}, str(path), metadata={"split": split, "input_sha256": DATA_PINS[split + ".jsonl"], "encoder_revision": REVISION})
        feature_records[split] = {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(path), "shape": list(x.shape)}
        return x

    train = load_split("train", labels)
    cal = load_split("calibration", labels)
    xtrain = features("train", train)
    xcal = features("calibration", cal)
    ytrain = np.asarray([r["source_label_id"] for r in train], dtype=np.int64)
    ycal = np.asarray([r["source_label_id"] for r in cal], dtype=np.int64)
    clf = LogisticRegression(C=1.0, solver="lbfgs", max_iter=400, tol=1e-6, fit_intercept=True, class_weight=None, random_state=20261011)
    if time.monotonic() >= deadline:
        raise TimeoutError("Time budget exhausted before classifier fit")
    fit_started = time.monotonic()
    with threadpool_limits(limits=2), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        clf.fit(xtrain, ytrain)
    fit_seconds = time.monotonic() - fit_started
    fit_warnings = [str(w.message) for w in caught]
    assert np.array_equal(clf.classes_, np.arange(77))
    scales = np.maximum(np.max(np.abs(clf.coef_), axis=1) / 32767, 1e-15)
    quantized = np.rint(clf.coef_ / scales[:, None]).clip(-32767, 32767).astype(np.int16)
    head = {"schema_version": 1, "task": "banking77_publisher_support_intent_auxiliary", "labels": labels, "encoder": plan["source"], "embedding_width": 384, "weights_qint16": quantized.tolist(), "weight_scales": scales.tolist(), "intercept": clf.intercept_.tolist(), "temperature": 1.0, "threshold": 1.000001, "bank_policy_target": None, "ledger_target": None, "usage": "offline_teacher_reference_only", "reviewed_plan_sha256": args.plan_sha256}
    reference_cal_logits = clf.decision_function(xcal)
    cal_logits = rt.head_logits(head, xcal)
    cal_parity = {"rows": len(cal), "max_abs_logit_error": float(np.abs(reference_cal_logits - cal_logits).max()), "predicted_label_parity": float((reference_cal_logits.argmax(1) == cal_logits.argmax(1)).mean())}
    assert cal_parity["max_abs_logit_error"] <= 0.005 and cal_parity["predicted_label_parity"] == 1.0, "Predeclared JSON export parity gate failed"

    def nll(log_t):
        scaled = cal_logits / np.exp(log_t)
        return float((logsumexp(scaled, axis=1) - scaled[np.arange(len(ycal)), ycal]).mean())

    temp = minimize_scalar(nll, bounds=(np.log(.05), np.log(20.0)), method="bounded", options={"maxiter": 60, "xatol": 1e-5})
    assert temp.success
    head["temperature"] = float(np.exp(temp.x))
    cal_prob = rt.probabilities(cal_logits, head["temperature"])
    threshold_records = [selective(cal_prob, ycal, t) for t in np.linspace(0, 1, 101)]
    feasible = [r for r in threshold_records if r["accepted"] >= 100 and r["accepted_precision"] >= .95]
    if feasible:
        chosen = max(feasible, key=lambda r: (r["coverage"], -r["threshold"]))
        head["threshold"] = chosen["threshold"]
    cal_metrics = metric(cal_prob, ycal, head["threshold"], labels)
    cal_metrics.update({"temperature": head["temperature"], "nll_before_temperature": nll(0.0), "nll_after_temperature": nll(temp.x), "threshold_selection": "CAL only, empirical precision >= .95 and >=100 accepted, maximize coverage", "threshold_grid": threshold_records, "estimate_warning": "Temperature and threshold were fitted on this CAL; reported CAL precision/coverage are in-sample selection estimates, not guarantees or independent evaluation"})
    assert len(encoded(head)) <= 500_000
    write_json(HEAD, head)
    # Reload serialized JSON before eval: parity protects the usable export.
    head = json.loads(HEAD.read_text())
    freeze = {"status": "FROZEN_BEFORE_FIRST_EVAL_LABEL_READ", "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "plan_sha256": args.plan_sha256, "head_sha256": sha(HEAD), "head_bytes": HEAD.stat().st_size, "code_hashes": plan["code_hashes"], "input_hashes": DATA_PINS, "encoder_files": plan["source"]["files"], "temperature": head["temperature"], "threshold": head["threshold"], "cal_export_parity": cal_parity, "classifier_fits": 1, "fit_seconds": fit_seconds, "fit_iterations": clf.n_iter_.tolist(), "fit_warnings": fit_warnings}
    write_json(FREEZE, freeze)
    print(json.dumps({"stage": "FROZEN_BEFORE_EVAL", "head_bytes": freeze["head_bytes"], "fit_seconds": fit_seconds, "cal_macro_f1": cal_metrics["macro_f1"], "cal_abstention": cal_metrics["abstention"]}), flush=True)
    marker = ROOT / "analysis/day2-pretrained-baseline-eval-once.json"
    with marker.open("x", encoding="utf-8") as f:
        json.dump({"freeze_sha256": sha(FREEZE), "head_sha256": sha(HEAD), "status": "single_eval_pass_started", "at_utc": datetime.now(timezone.utc).isoformat()}, f)
    evaluation = load_split("eval", labels)
    xeval = features("eval", evaluation)
    yeval = np.asarray([r["source_label_id"] for r in evaluation], dtype=np.int64)
    eval_logits = rt.head_logits(head, xeval)
    eval_prob = rt.probabilities(eval_logits, head["temperature"])
    eval_metrics = metric(eval_prob, yeval, head["threshold"], labels)
    reference_eval_logits = clf.decision_function(xeval)
    eval_parity = {"rows": len(evaluation), "max_abs_logit_error": float(np.abs(reference_eval_logits - eval_logits).max()), "predicted_label_parity": float((reference_eval_logits.argmax(1) == eval_logits.argmax(1)).mean()), "no_selection_on_result": True}
    ood_features = encoder.encode(OOD_PROBES, deadline=deadline)
    ood_prob = rt.probabilities(rt.head_logits(head, ood_features), head["temperature"])
    ood_conf = ood_prob.max(1)
    ood = {"role": "predeclared authored nonblind diagnostics; not bank safety gold", "rows": len(OOD_PROBES), "abstained": int((ood_conf < head["threshold"]).sum()), "abstention_rate": float((ood_conf < head["threshold"]).mean()), "no_threshold_selection": True, "queries": [{"text": text, "predicted_source_label": labels[int(prob.argmax())], "confidence": float(prob.max()), "abstain": bool(prob.max() < head["threshold"])} for text, prob in zip(OOD_PROBES, ood_prob)]}
    assert sha(HEAD) == freeze["head_sha256"] and verify_inputs() == labels
    result = {"status": "completed_real_frozen_pretrained_encoder_plus_trained_head", "plan_sha256": args.plan_sha256, "grant": args.grant, "source": plan["source"], "code_hashes": plan["code_hashes"], "input_hashes": DATA_PINS, "versions": plan["versions"], "encoder_gradient_updates": 0, "classifier_fits": 1, "eval_passes": 1, "selection_data": "TRAIN classifier weights; CAL temperature/threshold; no EVAL/OOD selection", "feature_cache": feature_records, "freeze": freeze, "freeze_sha256": sha(FREEZE), "calibration": cal_metrics, "internal_eval": eval_metrics, "export_parity": {"calibration": cal_parity, "eval": eval_parity}, "ood_diagnostic": ood, "wall_seconds": time.monotonic() - started, "limits": KNOWN_LIMITS}
    write_json(REPORT, result)
    lines = ["Completed actual CPU frozen MiniLM + TRAIN-only 77-way C=1 logistic head.", "Plan SHA256: " + args.plan_sha256, "Head: " + HEAD.relative_to(ROOT).as_posix() + " bytes=" + str(freeze["head_bytes"]) + " sha256=" + freeze["head_sha256"], "Single internal EVAL: macro F1=" + str(eval_metrics["macro_f1"]) + "; accuracy=" + str(eval_metrics["accuracy"]), "CAL empirical selected precision/coverage: " + json.dumps(cal_metrics["abstention"]), "Frozen EVAL accepted precision/coverage: " + json.dumps(eval_metrics["abstention"]), "OOD authored diagnostic abstention: " + str(ood["abstained"]) + "/" + str(ood["rows"]) + "; not blind OOD/bank safety evidence.", "JSON export parity: " + json.dumps(result["export_parity"]), "CPU wall seconds: " + str(result["wall_seconds"]), "No deployments, bank permissions, ledger facts or live Freya inference. Encoder weights remain in ignored local cache."] + KNOWN_LIMITS
    (ROOT / "analysis/day2-pretrained-baseline.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "eval_macro_f1": eval_metrics["macro_f1"], "eval_accuracy": eval_metrics["accuracy"], "cal_abstention": cal_metrics["abstention"], "eval_abstention": eval_metrics["abstention"], "ood_abstention": ood["abstention_rate"], "export_parity": result["export_parity"], "wall_seconds": result["wall_seconds"]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    stage = parser.add_mutually_exclusive_group(required=True)
    stage.add_argument("--prepare", action="store_true")
    stage.add_argument("--run", action="store_true")
    parser.add_argument("--grant")
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    else:
        run(args)
