"""Actual publisher-taxonomy metrics, never policy/permission evaluation."""
import json
import hashlib
import math
import time
from collections import Counter
from pathlib import Path
from day2_public_model_v2 import VERSION, WIDTH, source_graph, score, predict


def source_tests():
    text = "My fictional card charge of 123 was reversed yesterday. Why is the amount still shown?"
    g = source_graph(text); tokens = text.split()
    covered = " ".join(text[a:b] for a, b in g["spans"]).split()
    tests = {"all_source_tokens_covered": tokens == covered, "actual_order_and_membership_edges": {e[2] for e in g["edges"]} == {"source_order", "turn_membership"},
             "all_edges_removed_in_ablation": not source_graph(text, False)["edges"], "input_immutable": text == "My fictional card charge of 123 was reversed yesterday. Why is the amount still shown?",
             "empty_masks": source_graph("") is None, "structured_masks": source_graph({"private": "canary"}) is None,
             "oversized_masks": source_graph("x" * 2049) is None,
             "digits_delexicalized": source_graph(text.replace("123", "987"))["linear"] == g["linear"]}
    long = " ".join("word%d" % i for i in range(90)); lg = source_graph(long)
    tests["long_source_retained"] = " ".join(long[a:b] for a, b in lg["spans"]).split() == long.split()
    assert all(tests.values()), tests
    return {"executed": len(tests), "passed": sum(tests.values()), "checks": tests, "fit_calls": 0}


def native_scores(text, model, params):
    import numpy as np
    g = source_graph(text, model["use_edges"]); n = len(g["nodes"]); c = len(model["publisher_labels"])
    if model["architecture"] == "sparse_softmax":
        logits = params["bias"] + sum(params["weights"][i] * v for i, v in g["linear"].items())
    else:
        x = np.zeros((n, WIDTH)); root = np.zeros((n, n)); seq = root.copy()
        for j, node in enumerate(g["nodes"]):
            for k, v in node.items(): x[j, k] = v
        for a, b, relation in g["edges"]: (root if relation == "turn_membership" else seq)[b, a] = 1
        h0 = np.tanh(x @ params["embedding"] + params["embedding_bias"])
        h1 = np.tanh(h0 @ params["self"] + (root @ h0) @ params["turn_membership"] + (seq @ h0) @ params["source_order"] + params["message_bias"])
        logits = h1[g["user_nodes"]].mean(axis=0) @ params["readout"] + params["bias"]
    logits = logits / model.get("calibration", {}).get("temperature",1.0); logits = logits - logits.max(); e = np.exp(logits); return (e / e.sum()).tolist()


def metrics(rows, labels, threshold=1.1):
    n = len(rows); correct = selective = selective_correct = selected = selected_correct = 0; bygroup = {}; tp = Counter(); fp = Counter(); fn = Counter(); ce = 0.0
    for r in rows:
        y, p = r["label_index"], r["probabilities"]; predicted = max(range(len(p)), key=lambda i: p[i]); ok = predicted == y
        correct += ok; loss = -math.log(max(p[y], 1e-15)); ce += loss
        bygroup.setdefault(r["group"], []).append((ok, loss)); tp[y] += ok; fp[predicted] += not ok; fn[y] += not ok
        high = max(p) >= 0.8; selective += high; selective_correct += high and ok
        admitted = max(p) >= threshold; selected += admitted; selected_correct += admitted and ok
    return {"observed_rows": n, "groups": len(bygroup), "accuracy": correct / n,
            "macro_precision": sum(tp[i] / (tp[i] + fp[i]) if tp[i] + fp[i] else 0 for i in range(len(labels))) / len(labels),
            "macro_recall": sum(tp[i] / (tp[i] + fn[i]) if tp[i] + fn[i] else 0 for i in range(len(labels))) / len(labels),
            "row_CE": ce / n, "group_mean_CE": sum(sum(a[1] for a in v) / len(v) for v in bygroup.values()) / len(bygroup),
            "group_mean_accuracy": sum(sum(a[0] for a in v) / len(v) for v in bygroup.values()) / len(bygroup),
            "raw_fixed_0_8_score_coverage": selective / n, "raw_fixed_0_8_accuracy": selective_correct / selective if selective else None,
            "CAL_selected_source_threshold":threshold,"source_intent_proposed":selected,"source_intent_proposal_coverage":selected/n,
            "source_intent_proposal_precision":selected_correct/selected if selected else None,"source_intent_abstention_rate":1-selected/n,
            "deployment_coverage": 0.0, "deployment_abstention": 1.0}


def temperature_probabilities(probabilities, temperature):
    logits = [math.log(max(p,1e-300))/temperature for p in probabilities]
    peak = max(logits); exps = [math.exp(v-peak) for v in logits]; total = sum(exps)
    return [p/total for p in exps]


def calibrate(rows, model, plan):
    """CAL-only scalar calibration; no TRAIN optimizer/EVAL access here."""
    import numpy as np
    p = {k:np.asarray(v,dtype=float) for k,v in model["parameters"].items()}
    if model["architecture"]=="sparse_softmax":p["weights"]=p["weights_q"]*p["weight_scale"]
    fitrows, thresholdrows = [], []
    for row in rows:
        if row["partition"]!="calibration" or not row["observed_mask"]:continue
        value={"id":row["id"],"group":row["canonical_group"],"gold":model["publisher_labels"].index(row["publisher_label"]),"probabilities":native_scores(row["text"],model,p)}
        (fitrows if int(hashlib.sha256(row["canonical_group"].encode()).hexdigest()[:8],16)%2==0 else thresholdrows).append(value)
    assert fitrows and thresholdrows
    assert not {r["group"] for r in fitrows}&{r["group"] for r in thresholdrows}
    grid=[]
    for t in plan["calibration"]["temperature_grid"]:
        loss=sum(-math.log(max(temperature_probabilities(r["probabilities"],t)[r["gold"]],1e-300)) for r in fitrows)/len(fitrows)
        grid.append({"temperature":t,"CAL_fit_CE":loss})
    temperature=min(grid,key=lambda x:(x["CAL_fit_CE"],x["temperature"]))["temperature"]
    scores=[(max(temperature_probabilities(r["probabilities"],temperature)),max(range(77),key=lambda j:r["probabilities"][j])==r["gold"]) for r in thresholdrows]
    sweep=[]; acceptable=[]
    for threshold in plan["calibration"]["threshold_grid"]:
        chosen=[ok for confidence,ok in scores if confidence>=threshold]; precision=sum(chosen)/len(chosen) if chosen else None
        sweep.append({"threshold":threshold,"proposed":len(chosen),"precision":precision,"coverage":len(chosen)/len(scores)})
        if len(chosen)>=30 and precision>=.90:acceptable.append((len(chosen),threshold))
    threshold=max(acceptable)[1] if acceptable else 1.1
    return {"fitted":True,"temperature":temperature,"threshold":threshold,"CAL_temperature_rows":len(fitrows),"CAL_threshold_rows":len(thresholdrows),
            "CAL_group_overlap":0,"temperature_grid_results":grid,"threshold_select_results":sweep,
            "statistical_safety_guarantee":False,"weights_changed":False,"EVAL_used":False,
            "limitation":"Threshold selected adaptively on CAL-select; its empirical precision is optimistic. EVAL measures the frozen choice, no bank-policy qualification."}


def evaluate(rows, labels, outputs, plan, approved_hash, fit_wall_seconds):
    root = Path(__file__).resolve().parents[2]; reports = {}; max_error = 0.0; decoder_errors = parity = 0
    for name, info in outputs.items():
        model = json.loads((root / info["path"]).read_text(encoding="utf8")); native = info.pop("native_parameters")
        splits = {"fit": [], "calibration": [], "internal_publisher_TRAIN_eval": []}; source_tests(); start = time.monotonic()
        # Score every observed row with vectorized NumPy one record at a time;
        # actual stdlib export/parity on a predeclared stable 256-row sample.
        sample = sorted([r for r in rows if r["observed_mask"]], key=lambda r: r["id"])[:256]
        sampled_ids = {r["id"] for r in sample}
        import numpy as np
        exported_native = {k: np.asarray(v, dtype=float) for k, v in model["parameters"].items()}
        if model["architecture"]=="sparse_softmax":
            exported_native["weights"] = exported_native["weights_q"] * exported_native["weight_scale"]
        for r in rows:
            if not r["observed_mask"]: continue
            probabilities = native_scores(r["text"], model, exported_native)
            if r["id"] in sampled_ids:
                exported = score(r["text"], model); full = native_scores(r["text"], model, native)
                error = max(abs(a - b) for a, b in zip(exported, full)); max_error = max(max_error, error)
                decoder_errors += max(range(len(full)), key=lambda i: full[i]) != max(range(len(exported)), key=lambda i: exported[i])
                assert max(abs(a - b) for a, b in zip(exported, probabilities)) < 1e-10
                assert error < .001; assert predict(r["text"], model)["acceptance"] is False; parity += 1
            splits[r["partition"]].append({"id": r["id"], "group": r["canonical_group"], "label_index": labels.index(r["publisher_label"]), "probabilities": probabilities})
        candidate = sample[0]["text"]; t = time.perf_counter()
        for _ in range(100): score(candidate, model)
        threshold=model["calibration"]["threshold"]
        reports[name] = {**info, "fit_resubstitution": metrics(splits["fit"], labels,threshold), "CAL_descriptive": metrics(splits["calibration"],labels,threshold), "calibration":model["calibration"], "internal_publisher_TRAIN_eval": metrics(splits["internal_publisher_TRAIN_eval"], labels,threshold),
                         "stdlib_single_record_latency_ms_mean_100": (time.perf_counter() - t) * 10, "eval_wall_seconds": time.monotonic() - start}
    from day2_public_train_v2 import save, check_frozen, sha
    check_frozen()
    report = {"version": "day2.public_actual_experiment.v1", "status": "ACTUALLY_FITTED_PUBLIC_AUXILIARY_ONLY_ALL_ABSTAIN", "approved_plan_sha256": approved_hash,
              "source_sha256": plan["source_sha256"], "input_sha256": plan["input_sha256"], "models": reports,
              "fit_and_model_save_seconds_total": fit_wall_seconds, "partitions": plan["partitions"], "group_overlap": 0,
              "native_full_precision_export_parity": {"sample_records_per_model": 256, "comparisons": parity, "max_score_error": max_error,
                                                      "decoder_mismatches": int(decoder_errors), "quantization_tolerance": .001},
              "publisher_taxonomy": labels, "publisher_TEST_read": False, "calibration": plan["calibration"],
              "deployment": {"qualified": False, "acceptance": 0, "abstention": 1.0, "bank_mapping": None, "floor_20": "unchanged_closed"},
              "no_bank_policy_correctness_claim": True, "GPU_USD": 0, "worker_source_manifest": plan["worker_manifest_literal"],
              "limits": ["Publisher TRAIN split only, internally partitioned by conservative within-packet groups; common publisher/non-IID and residual unseen template linkage remain limitations.",
                         "Publisher test was previously exposed and is neither read nor called fresh qualification. No temperature/threshold selected on evaluation.",
                         "77 publisher intents pretrain source representation/routing only. Any policy adaptation needs separate reviewed fictional data and another grant."]}
    save(root / "integrations/learned-dialogue/day2_public_metrics_v2.json", report)
    out = root / "analysis/day2-public-model-experiment-v2.json"; out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf8")
    text = "Actual public publisher-TRAIN auxiliary fits, allabstain/no bank mapping.\nPlan SHA256:" + approved_hash + "\n"
    for name, r in reports.items():
        m = r["internal_publisher_TRAIN_eval"]
        text += "%s: %.3fs preprocessing+fit, eval%drows/%dgroups, accuracy%.4f, groupCE%.4f; runtime+weights%dbytes.\n" % (name, r["training"]["actual_preprocess_and_fit_seconds"], m["observed_rows"], m["groups"], m["accuracy"], m["group_mean_CE"], r["runtime_plus_bundle_bytes"])
    text += "CAL-only temperature/threshold; EVAL after weight+calibrator freeze. No publisherTEST, qualified bank accuracy, GPU/network or tool authority.\n"
    (root / "analysis/day2-public-model-experiment-v2.txt").write_text(text, encoding="utf8")
    freeze = {"version": "day2.public_actual_freeze.v1", "approved_plan_sha256": approved_hash, "source_sha256": plan["source_sha256"], "input_sha256": plan["input_sha256"],
              "artifacts_sha256": {str(p.relative_to(root)).replace("\\", "/"): sha(p) for p in [out, root / "analysis/day2-public-model-experiment-v2.txt", root / "integrations/learned-dialogue/day2_public_metrics_v2.json"]},
              "models_sha256": {r["path"]: r["sha256"] for r in reports.values()}, "qualified": False, "acceptance": False}
    save(root / "integrations/learned-dialogue/day2_public_freeze_v2.json", freeze)
    print(json.dumps({"models": reports, "native_export_max_error": max_error, "all_abstain": True}))
