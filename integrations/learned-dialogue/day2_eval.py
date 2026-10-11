"""Source-only readiness tests and post-authorized-fit exploratory metrics."""
import copy
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from day2_experimental_model import source_input, raw_score, predict, sigmoid, VERSION


def source_smokes(raw):
    r = next(r for r in raw if source_input(r["input"])[0] is not None)
    s = copy.deepcopy(r["input"]); graph, _ = source_input(s)
    altered = copy.deepcopy(s); altered["annotation"] = {"oracle": "canary"}; altered["turn_id"] = "new-id"; altered["utterance"]["source_turn_id"] = "new-id"
    checks = {"source_graph_has_typed_edges": bool(graph["edges"]), "source_graph_json_roundtrip": source_input(json.loads(json.dumps(s))) == source_input(s),
              "IDs_and_oracle_extras_not_features": source_input(altered) == source_input(s),
              "context_ablation_changes_actual_input": source_input(s, False)[0] != graph,
              "edge_ablation_removes_all_edges": not source_input(s, True, False)[0]["edges"]}
    for name, mutate in [("structured_phase", lambda x: x.update(phase={"canary": "private"})),
                         ("structured_role", lambda x: x["question"].update(role=["canary"])),
                         ("incomplete_transport", lambda x: x["utterance"].update(complete_transport=False)),
                         ("untrusted_raw", lambda x: x["utterance"].update(source="extracted_copy")),
                         ("security_phase", lambda x: x.update(phase="security")),
                         ("empty_source", lambda x: x["utterance"].update(text="")),
                         ("binding_mismatch", lambda x: x["utterance"].update(source_turn_id="old"))]:
        changed = copy.deepcopy(s); mutate(changed); checks[name + "_masks"] = source_input(changed)[0] is None
    assert all(checks.values()), checks
    return {"checks": checks, "executed": len(checks), "passed": sum(checks.values()), "fit_calls": 0}


def metric(rows):
    if not rows: return {"n": 0}
    c = Counter(); losses = []; bygroup = {}
    for r in rows:
        y, p = r["label"], r["score"]; predicted = p >= 0.5
        c["correct"] += predicted == y; c["tp"] += predicted and y == 1; c["fp"] += predicted and y == 0
        c["fn"] += not predicted and y == 1; c["tn"] += not predicted and y == 0
        selective = max(p, 1 - p) >= 0.8
        c["selective"] += selective; c["selective_correct"] += selective and predicted == y
        loss = -(__import__("math").log(max(p if y else 1 - p, 1e-15)))
        losses.append(loss); bygroup.setdefault(r["group"], []).append((predicted == y, loss))
    n = len(rows)
    return {"n": n, "groups": len(bygroup), "class_rows": dict(Counter(r["label"] for r in rows)), "accuracy": c["correct"] / n,
            "positive_precision": c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else None,
            "positive_recall": c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else None,
            "confusion": {k: c[k] for k in ("tp", "fp", "tn", "fn")}, "row_BCE": sum(losses) / n,
            "group_mean_accuracy": sum(sum(v[0] for v in a) / len(a) for a in bygroup.values()) / len(bygroup),
            "group_mean_BCE": sum(sum(v[1] for v in a) / len(a) for a in bygroup.values()) / len(bygroup),
            "raw_confidence_0_8_coverage": c["selective"] / n,
            "raw_confidence_0_8_accuracy": c["selective_correct"] / c["selective"] if c["selective"] else None,
            "deployment_coverage": 0.0, "deployment_abstention_rate": 1.0,
            "scores_are_calibrated": False}


def numpy_score(snapshot, bundle):
    import numpy as np
    from day2_experimental_model import BINS
    graph, reasons = source_input(snapshot, bundle["include_context"], bundle["include_edges"])
    if graph is None: return None
    p = {k: np.asarray(v, dtype=float) for k, v in bundle["parameters"].items()}
    if bundle["architecture"] == "sparse_logistic":
        return sigmoid(float(p["bias"] + sum(p["weights"][i] * v for i, v in graph["linear"].items())))
    x = np.zeros((len(graph["nodes"]), BINS)); q = np.zeros((len(x), len(x))); order = q.copy()
    for i, node in enumerate(graph["nodes"]):
        for k, v in node.items(): x[i, k] = v
    for a, b, relation in graph["edges"]: (q if relation == "question_context" else order)[b, a] = 1
    h0 = np.tanh(x @ p["embedding"] + p["embedding_bias"])
    h1 = np.tanh(h0 @ p["self"] + (q @ h0) @ p["question_context"] + (order @ h0) @ p["speech_order"] + p["message_bias"])
    return sigmoid(float(h1[graph["user_nodes"]].mean(axis=0) @ p["readout"] + p["bias"]))


def evaluate_all(raw, masks, weights, plan, approved_hash, fit_seconds):
    root = Path(__file__).resolve().parents[2]; metrics = {}; parity = 0; max_error = 0.0; all_abstain = True
    for name, info in weights.items():
        path = root / info["path"]; original = json.loads(path.read_text(encoding="utf8")); restored = json.loads(json.dumps(original))
        rows = {"fit": [], "exploratory_eval": []}
        for r, mask in zip(raw, masks):
            p, reasons = raw_score(r["input"], restored)
            native = numpy_score(r["input"], original)
            if p is not None:
                error = abs(p - native); max_error = max(max_error, error); assert error < 1e-10; parity += 1
            assert raw_score(r["input"], original) == raw_score(r["input"], restored)
            proposal = predict(r["input"], restored); all_abstain &= proposal["status"] == "abstain" and proposal["qualified"] is False
            assert set(proposal) == {"version", "binding", "status", "qualified", "candidate", "uncalibrated_binary_score", "authority", "training_admission", "reasons"}
            if mask["experimental_observed_mask"]:
                assert p is not None
                rows[mask["partition"]].append({"id": r["example_id"], "group": mask["canonical_group"], "label": mask["binary_label"], "score": p})
        suitable = next(r["input"] for r, m in zip(raw, masks) if m["experimental_observed_mask"])
        start = time.perf_counter()
        for _ in range(100): raw_score(suitable, restored)
        metrics[name] = {**info, "fit_resubstitution": metric(rows["fit"]), "exposed_TRAIN_derived_group_eval": metric(rows["exploratory_eval"]),
                         "raw_prediction_rows": rows, "single_turn_CPU_latency_ms_mean_100": (time.perf_counter() - start) * 10}
    assert all_abstain
    from day2_train import save_new, sha
    results = {"schema_version": "day2.actual_cpu_experiment.v1", "status": "EXPERIMENTAL_ACTUALLY_FITTED_ALL_ABSTAIN",
               "approved_plan_sha256": approved_hash, "source_sha256": plan["source_sha256"], "input_sha256": plan["input_sha256"],
               "partitions": plan["partitions"], "within_corpus_group_overlap": 0, "canonical_global_closure": False,
               "floor_20_deployment_admission": "UNCHANGED_CLOSED", "qualified_groups": 0,
               "models": metrics, "actual_total_fit_and_model_save_seconds": fit_seconds,
               "native_numpy_to_stdlib_JSON_parity": {"comparisons": parity, "maximum_absolute_score_error": max_error, "tolerance": 1e-10},
               "source_smokes": plan["source_smokes"], "all_abstain": all_abstain,
               "calibration": "No calibration set or calibrated probabilities; fixed 0.5/0.8 diagnostics only; no threshold tuned on eval.",
               "data_source_license": "Existing single-author fictional V2 TRAIN; LicenseRef-User-Authorized-Synthetic-RD. No new downloads, banking-policy truth, customer uploads or public dataset benchmark.",
               "caveats": plan["precommitted_caveats"], "DEV_reads": 0, "old_grants_reused": False, "GPU_USD": 0}
    save_new(root / "integrations/learned-dialogue/day2_model.metrics.json", results)
    (root / "analysis/day2-model-experiment.json").write_text(json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf8")
    text = "Actual CPU fits completed; all models remain unqualified proposal-only/all-abstain.\nPlan SHA256: " + approved_hash + "\n"
    for name, info in metrics.items():
        m = info["exposed_TRAIN_derived_group_eval"]
        text += "%s: fit %.3fs; eval %d rows/%d groups; accuracy %.4f, positive precision %s, raw .8 coverage %.4f; deployment coverage 0; bundle %d bytes.\n" % (name, info["training"]["actual_fit_seconds"], m["n"], m["groups"], m["accuracy"], m["positive_precision"], m["raw_confidence_0_8_coverage"], info["bytes"])
    text += "Native/export parity %d comparisons; max error %.3g. No calibration/qualification, DEV/GPU/network/tool calls.\n" % (parity, max_error)
    text += "Evaluation is a local conservative root-union partition of reused exposed TRAIN, single-author non-IID; global ancestry unresolved. No hidden/generalization/safety success claim. The fixed 20-class deployment floor remains closed.\n"
    (root / "analysis/day2-model-experiment.txt").write_text(text, encoding="utf8")
    print(json.dumps({"models": {n: {"fit_seconds": v["training"]["actual_fit_seconds"], "eval": v["exposed_TRAIN_derived_group_eval"], "bytes": v["bytes"]} for n, v in metrics.items()}, "parity": parity, "max_error": max_error, "all_abstain": True}))
