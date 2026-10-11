"""Observational controls and runtime measurements; never rewrite v1 model."""
import copy
import hashlib
import io
import json
import random
import sys
import time
import unittest
from collections import Counter
from pathlib import Path

from inference import HEADS, local_snapshot, predict, score, uncertainty_guard
from train_eval import HERE, ROOT, evaluate, fit, load_data, load_model, write_json


def main():
    records, oracle, manifest, checks = load_data()
    model = load_model()
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
              (HERE / "model.json", ROOT / "analysis/night-learned-dialogue.train.json", ROOT / "analysis/night-learned-dialogue.eval.json")}
    train = [r for r in records if r["split"] == "train"]
    held = [r for r in records if r["split"] == "holdout"]
    majority = {h: Counter(oracle[r["id"]][h] for r in train).most_common(1)[0][0] for h in HEADS}
    majority_metrics = {"raw_head_accuracy": {h: sum(majority[h] == oracle[r["id"]][h] for r in held) / len(held) for h in HEADS},
                        "raw_joint_exact_accuracy": sum(all(majority[h] == oracle[r["id"]][h] for h in HEADS) for r in held) / len(held)}
    guard_abstains = [bool(uncertainty_guard(r["utterance"])) for r in held]
    uncertain_count = sum(oracle[r["id"]]["must_abstain"] for r in held)
    guards_only = {"semantic_label_accuracy": None, "reason": "Guards have no intent classifier", "abstained": sum(guard_abstains),
                   "uncertainty_abstention_recall": sum(flag and oracle[r["id"]]["must_abstain"] for r, flag in zip(held, guard_abstains)) / uncertain_count,
                   "missed_uncertainty_ids": [r["id"] for r, flag in zip(held, guard_abstains) if oracle[r["id"]]["must_abstain"] and not flag]}
    learned_only_rows = []
    for r in held:
        raw, confidence = score(model, r["utterance"])
        accept = raw["completion"] == "complete" and raw["unresolvedcomponent"] == "none" and raw["primaryintent"] != "unknown" and min(v["max_score"] for v in confidence.values()) >= model["calibration"]["threshold"] and confidence["primaryintent"]["margin"] >= 0.12
        learned_only_rows.append({"id": r["id"], "accepted": accept,
                                  "error_if_accepted": accept and (oracle[r["id"]]["must_abstain"] or any(raw[h] != oracle[r["id"]][h] for h in HEADS))})
    shuffled_oracle = dict(oracle)
    values = [copy.deepcopy(oracle[r["id"]]) for r in train]
    random.Random(314159).shuffle(values)
    shuffled_oracle.update({r["id"]: label for r, label in zip(train, values)})
    start = time.perf_counter()
    shuffled, _ = fit(train, shuffled_oracle, epochs=100, seed=2718)
    # Keep original threshold/temperatures; no new calibration/holdout tuning.
    shuffled["calibration"] = copy.deepcopy(model["calibration"])
    for h in HEADS:
        shuffled["heads"][h]["temperature"] = model["heads"][h]["temperature"]
    shuffled_report = evaluate(shuffled, held, oracle)
    shuffled_seconds = time.perf_counter() - start
    latencies = []
    for i in range(220):
        r = held[i % len(held)]
        start = time.perf_counter_ns()
        predict(local_snapshot(r["utterance"], r["id"]), model)
        latencies.append((time.perf_counter_ns() - start) / 1e6)
    ordered = sorted(latencies)
    latency = {"calls": len(latencies), "p50_ms": ordered[len(ordered)//2], "p95_ms": ordered[int(len(ordered)*.95)],
               "p99_ms": ordered[int(len(ordered)*.99)], "maximum_ms": ordered[-1], "scope": "Warm local CPython only; not extraction, network, sandbox, routing or speech latency"}
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_smoke.py")
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    smoke = {"interpreter": sys.executable, "python_version": sys.version, "tests_run": result.testsRun,
             "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped),
             "passed": result.wasSuccessful(), "output": stream.getvalue()}
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in map(Path, before)}
    report = {"v1_artifacts_preserved": before == after, "frozen_hashes": before, "split_integrity": checks,
              "majority_from_train": majority_metrics, "guards_only": guards_only,
              "learned_only_same_threshold": {"accepted": sum(r["accepted"] for r in learned_only_rows), "errors": sum(r["error_if_accepted"] for r in learned_only_rows), "rows": learned_only_rows},
              "shuffled_train_labels_fixed_calibration": shuffled_report, "shuffled_fit_and_eval_seconds": shuffled_seconds,
              "no_context_baseline": "Original v1 is the text-only/no-context baseline; no context model trained yet",
              "latency": latency, "smoke": smoke,
              "interpretation": "Observational diagnostic comparison on the already inspected v1 holdout; not a new unseen or independently qualifying experiment"}
    write_json(ROOT / "analysis/night-learned-dialogue.smoke.json", report)
    print(json.dumps({"smoke": {k:v for k,v in smoke.items() if k != "output"}, "v1_preserved": report["v1_artifacts_preserved"],
                      "majority": majority_metrics, "guards_only": guards_only,
                      "learned_only": {"accepted": report["learned_only_same_threshold"]["accepted"], "errors": report["learned_only_same_threshold"]["errors"]},
                      "shuffled_raw_joint": shuffled_report["raw_joint_exact_accuracy"], "shuffled_accepted": shuffled_report["accepted"], "shuffled_errors": shuffled_report["accepted_joint_errors"], "latency": latency}, indent=2))
    if not result.wasSuccessful() or before != after:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
