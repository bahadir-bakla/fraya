"""Prepare source-bound exploratory CPU plan; fit ONLY after fresh parent grant."""
import argparse
import hashlib
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from day2_experimental_model import BINS, HIDDEN, MAX_NODES, VERSION, source_input

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRAIN = "integrations/learned-dialogue/v2-final-data/train.json"
MANIFEST = "integrations/learned-dialogue/v2-final-data/manifest.json"
PLAN = HERE / "day2_model.plan.json"
SEED = 20261011


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_new(path, value):
    with Path(path).open("x", encoding="utf8") as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")


def skeleton(record):
    text = record["input"]["utterance"]["text"].casefold()
    for t in sorted(record["input"].get("targets", []), key=lambda t: -len(t["label"])):
        text = re.sub(r"(?<!\w)" + re.escape(t["label"].casefold()) + r"(?!\w)", " target ", text)
    text = re.sub(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)\b", "calendar", text)
    text = re.sub(r"\d+(?:st|nd|rd|th)?", "number", text)
    return " ".join(re.findall(r"\w+", text))


def prepare_rows():
    raw = json.loads((ROOT / TRAIN).read_text(encoding="utf8"))["records"]
    parent = {r["example_id"]: r["example_id"] for r in raw}
    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        a, b = root(a), root(b)
        if a != b: parent[max(a, b)] = min(a, b)
    seen = {}
    for r in raw:
        keys = [("lineage", r["lineage_group_id"]), ("skeleton", skeleton(r))]
        for k in ("template_root", "scenario_root", "source_document_or_conversation_id"):
            if r["source"].get(k): keys.append((k, r["source"][k]))
        for key in keys:
            if key in seen: union(r["example_id"], seen[key])
            seen[key] = r["example_id"]
        for ancestor in r["source"].get("augmentation_parent_ids", []):
            if ancestor in parent: union(r["example_id"], ancestor)
    members = {}
    for r in raw: members.setdefault(root(r["example_id"]), []).append(r["example_id"])
    canonical = {k: "local-union-" + hashlib.sha256("\n".join(sorted(v)).encode()).hexdigest()[:20] for k, v in members.items()}
    groups = sorted(canonical.values(), key=lambda g: hashlib.sha256((str(SEED) + g).encode()).hexdigest())
    evaluation_groups = set(groups[:max(1, len(groups) // 4)])
    rows = []
    for r in raw:
        _, reasons = source_input(r["input"])
        labels = r["labels"]
        if labels["mask"].get("primary_intent") is not True: reasons.append("primary_observation_mask")
        if labels.get("primary_intent") in {None, "unknown"} or labels.get("ambiguity_set"): reasons.append("unknown_or_ambiguous_primary")
        if r["source"].get("fictional") is not True: reasons.append("not_fictional")
        if any(a not in parent for a in r["source"].get("augmentation_parent_ids", [])): reasons.append("unresolved_explicit_augmentation_parent")
        group = canonical[root(r["example_id"])]
        rows.append({"id": r["example_id"], "canonical_group": group,
                     "partition": "exploratory_eval" if group in evaluation_groups else "fit",
                     "experimental_observed_mask": not reasons,
                     "mask_reasons": reasons, "qualification_mask": False,
                     "original_primary_label": labels.get("primary_intent"),
                     "binary_label": int(labels.get("primary_intent") == "payment_proposal") if not reasons else None})
    return raw, rows, members


def prepare():
    if PLAN.exists(): raise ValueError("Plan already frozen; do not overwrite")
    raw, rows, members = prepare_rows()
    sources = {str((HERE / p).relative_to(ROOT)).replace("\\", "/"): sha(HERE / p)
               for p in ("day2_experimental_model.py", "day2_train.py", "day2_eval.py")}
    partitions = {}
    for split in ("fit", "exploratory_eval"):
        chosen = [r for r in rows if r["partition"] == split]
        observed = [r for r in chosen if r["experimental_observed_mask"]]
        partitions[split] = {"rows": len(chosen), "observed_rows": len(observed),
                             "class_rows": dict(Counter(r["binary_label"] for r in observed)),
                             "class_groups": {str(y): len({r["canonical_group"] for r in observed if r["binary_label"] == y}) for y in (0, 1)},
                             "groups": sorted({r["canonical_group"] for r in chosen})}
    assert not set(partitions["fit"]["groups"]) & set(partitions["exploratory_eval"]["groups"])
    from day2_eval import source_smokes
    smokes = source_smokes(raw)
    plan = {"schema_version": "day2.cpu_plan.v1", "status": "AWAITING_NEW_PARENT_HASH_BOUND_CPU_AUTHORIZATION",
            "source_sha256": sources, "input_sha256": {TRAIN: sha(ROOT / TRAIN), MANIFEST: sha(ROOT / MANIFEST)},
            "seed": SEED, "partitions": partitions, "rows_and_actual_masks": rows,
            "within_corpus_canonical_group_overlap": 0,
            "group_contract": "Union all rows, including masked aliases, by declared lineage/template/scenario/source-conversation, delexicalized exact utterance skeleton and explicit augmentation edges. All variants stay together. Local closure only; unresolved external/global ancestry stays unqualified.",
            "shared_author_not_independent": True, "global_ancestry_closed": False,
            "label_status": "Reused exposed V2 TRAIN author proposals, zero independent gold; only primary observed masks; no dates/components supervision; no old DEV/qualification",
            "head": "binary primary_is_payment_proposal; negative means only not-this-primary, never no-payment/refusal/permission",
            "architectures": ["sparse_logistic", "tiny_relational_gnn"],
            "graph_contract": "Raw punctuation clauses; question-context edges to user clauses; directed prior-clause speech-order edges; tanh node embedding and learned relation matrices, mean user readout. No parser predictions, annotation offsets, IDs or policy values.",
            "controls": ["sparse_text_only", "gnn_no_edges", "sparse_group_label_permutation"],
            "hyperparameters": {"bins": BINS, "hidden": HIDDEN, "max_nodes": MAX_NODES, "epochs": 220,
                                "adam_lr": 0.025, "l2": 0.001, "loss": "unweighted-class, mean over canonical groups then their observed rows"},
            "resource_cap": {"CPU_only": True, "max_fit_seconds_total": 120, "max_artifact_bytes_each": 500000, "GPU": False, "network": False},
            "inference_guard": "Always abstain/unqualified. All deployment masks false; no consent, bank tools, canonical amount/date or policy output.",
            "calibration": "None. Fixed raw 0.5 classification and descriptive fixed confidence 0.8 selective diagnostic; never deployment acceptance; no threshold tuning.",
            "admission_floor": {"unchanged": 20, "claimed_pass": False, "qualified_groups": 0,
                                "authorization_scope": "Separate parent-authorized exploratory fit only; no previous grant reuse or deployment admission"},
            "source_smokes": smokes,
            "runtime": {"executable": "C:/Users/9bakl/AppData/Local/Programs/Python/Python311/python.exe", "Python": "3.11.9", "numpy": "2.3.5", "other_ML_libraries_used": []},
            "freeze_anchor": {"analysis/night-learned-dialogue.v11-parser.freeze.json": sha(ROOT / "analysis/night-learned-dialogue.v11-parser.freeze.json")},
            "expected_outputs": ["day2_model.sparse.json", "day2_model.gnn.json", "day2_model.text_only.json", "day2_model.no_edges.json", "day2_model.shuffled.json", "day2_model.metrics.json"],
            "precommitted_caveats": ["Single authored tiny exposed corpus, non-IID, no independently reviewed gold; group unions are not global independence proof.", "Eval split comes from previously exposed TRAIN, exploratory engineering only; no hidden/OOD/qualification claim.", "No architecture is a GAN. This is a small actual message-passing neural model."]}
    save_new(PLAN, plan)
    report = {"status": plan["status"], "plan_path": str(PLAN.relative_to(ROOT)).replace("\\", "/"), "plan_sha256": sha(PLAN),
              "partitions": partitions, "source_sha256": sources, "input_sha256": plan["input_sha256"], "smokes": smokes,
              "fit_calls": 0, "weights_written": 0, "all_abstain": True, "requires_parent_authorization": True}
    save_new(ROOT / "analysis/day2-model-experiment.json", report)
    (ROOT / "analysis/day2-model-experiment.txt").write_text(json.dumps(report, indent=2) + "\nNo fit has occurred. New out-of-band parent authorization of the exact plan hash is required.\n", encoding="utf8")
    print(json.dumps(report, ensure_ascii=True))


def fit(approved_hash):
    # This argument must come from a NEW trusted parent message, never from a
    # plan self-hash, old grant, or authorization test double.
    if not approved_hash or approved_hash != sha(PLAN): raise ValueError("Exact new parent-approved plan SHA required")
    plan = json.loads(PLAN.read_text(encoding="utf8"))
    for path, h in {**plan["source_sha256"], **plan["input_sha256"], **plan["freeze_anchor"]}.items():
        if sha(ROOT / path) != h: raise ValueError("Pinned source/input changed: " + path)
    import numpy as np
    if np.__version__ != plan["runtime"]["numpy"]: raise ValueError("Unreviewed NumPy version")
    raw, rows, _ = prepare_rows()
    if rows != plan["rows_and_actual_masks"]: raise ValueError("Partition/mask drift")
    train = [(r, m) for r, m in zip(raw, rows) if m["partition"] == "fit" and m["experimental_observed_mask"]]
    if {m["binary_label"] for _, m in train} != {0, 1}: raise ValueError("Fit lacks a class")
    started = time.monotonic(); weights = {}
    config = [("sparse", "sparse_logistic", True, True, False), ("gnn", "tiny_relational_gnn", True, True, False),
              ("text_only", "sparse_logistic", False, True, False), ("no_edges", "tiny_relational_gnn", True, False, False),
              ("shuffled", "sparse_logistic", True, True, True)]
    for name, architecture, context, edges, shuffled in config:
        if time.monotonic() - started >= 120: raise RuntimeError("Total CPU fit budget exhausted")
        bundle, history = train_numpy(train, architecture, context, edges, shuffled, plan)
        bundle["plan_sha256"] = approved_hash
        path = HERE / ("day2_model." + name + ".json")
        save_new(path, bundle)
        if path.stat().st_size > 500000: raise ValueError("Bundle footprint exceeded")
        weights[name] = {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "bytes": path.stat().st_size, "training": history}
    from day2_eval import evaluate_all
    evaluate_all(raw, rows, weights, plan, approved_hash, time.monotonic() - started)


def train_numpy(train, architecture, context, edges, shuffled, plan):
    import numpy as np
    t = time.monotonic(); rng = np.random.default_rng(SEED)
    n = len(train); x = np.zeros((n, MAX_NODES, BINS), dtype=np.float64)
    q = np.zeros((n, MAX_NODES, MAX_NODES)); order = q.copy(); pool = np.zeros((n, MAX_NODES))
    linear = np.zeros((n, BINS)); labels = []; groups = []
    for i, (r, m) in enumerate(train):
        graph, errors = source_input(r["input"], context, edges)
        if errors: raise ValueError(errors)
        for j, node in enumerate(graph["nodes"]):
            for k, v in node.items(): x[i, j, k] = v
        for k, v in graph["linear"].items(): linear[i, k] = v
        for a, b, relation in graph["edges"]: (q if relation == "question_context" else order)[i, b, a] = 1
        for j in graph["user_nodes"]: pool[i, j] = 1 / len(graph["user_nodes"])
        labels.append(m["binary_label"]); groups.append(m["canonical_group"])
    y = np.array(labels, dtype=np.float64)
    counts = Counter(groups); sample_weight = np.array([1 / (len(counts) * counts[g]) for g in groups])
    changed = 0
    if shuffled:
        # Shuffle complete root label vectors only among identical length/mask
        # profiles. All variants of a group remain in one control/root/fold.
        buckets = {}
        for group in sorted(counts): buckets.setdefault(counts[group], []).append(group)
        for same_size in buckets.values():
            originals = [y[np.array(groups) == g].copy() for g in same_size]
            permutation = rng.permutation(len(same_size))
            for j, group in enumerate(same_size): y[np.array(groups) == group] = originals[permutation[j]]
        changed = int(np.sum(y != np.array(labels)))
    if architecture == "sparse_logistic":
        params = {"weights": np.zeros(BINS), "bias": np.array(0.0)}
    else:
        params = {"embedding": rng.normal(0, 0.12, (BINS, HIDDEN)), "embedding_bias": np.zeros(HIDDEN),
                  "self": np.eye(HIDDEN), "question_context": rng.normal(0, 0.08, (HIDDEN, HIDDEN)),
                  "speech_order": rng.normal(0, 0.08, (HIDDEN, HIDDEN)), "message_bias": np.zeros(HIDDEN),
                  "readout": rng.normal(0, 0.1, HIDDEN), "bias": np.array(0.0)}
    first = {k: v.copy() for k, v in params.items()}; m1 = {k: np.zeros_like(v) for k, v in params.items()}; m2 = {k: np.zeros_like(v) for k, v in params.items()}
    history = []
    for epoch in range(plan["hyperparameters"]["epochs"]):
        if time.monotonic() - t > 25: raise RuntimeError("Per-fit 25s CPU wall bound")
        if architecture == "sparse_logistic": logits = linear @ params["weights"] + params["bias"]
        else:
            h0 = np.tanh(x @ params["embedding"] + params["embedding_bias"])
            qh, oh = q @ h0, order @ h0
            h1 = np.tanh(h0 @ params["self"] + qh @ params["question_context"] + oh @ params["speech_order"] + params["message_bias"])
            pooled = np.einsum("bn,bnh->bh", pool, h1)
            logits = pooled @ params["readout"] + params["bias"]
        probabilities = 1 / (1 + np.exp(-np.clip(logits, -50, 50)))
        history.append(float(np.sum(sample_weight * (np.logaddexp(0, logits) - y * logits))))
        dz = (probabilities - y) * sample_weight
        if architecture == "sparse_logistic": grads = {"weights": linear.T @ dz, "bias": np.array(dz.sum())}
        else:
            dr = dz[:, None] * params["readout"]
            dh1 = dr[:, None, :] * pool[:, :, None] * (1 - h1 * h1)
            dh0 = dh1 @ params["self"].T + np.swapaxes(q, 1, 2) @ (dh1 @ params["question_context"].T) + np.swapaxes(order, 1, 2) @ (dh1 @ params["speech_order"].T)
            de = dh0 * (1 - h0 * h0)
            grads = {"readout": pooled.T @ dz, "bias": np.array(dz.sum()), "message_bias": dh1.sum(axis=(0, 1)),
                     "self": np.einsum("bni,bnj->ij", h0, dh1), "question_context": np.einsum("bni,bnj->ij", qh, dh1),
                     "speech_order": np.einsum("bni,bnj->ij", oh, dh1), "embedding": np.einsum("bni,bnj->ij", x, de), "embedding_bias": de.sum(axis=(0, 1))}
        for k in params:
            g = grads[k] + (0.001 * params[k] if k not in {"bias", "embedding_bias", "message_bias"} else 0)
            m1[k] = 0.9 * m1[k] + 0.1 * g; m2[k] = 0.999 * m2[k] + 0.001 * g * g
            params[k] -= 0.025 * (m1[k] / (1 - 0.9 ** (epoch + 1))) / (np.sqrt(m2[k] / (1 - 0.999 ** (epoch + 1))) + 1e-8)
    assert all(np.isfinite(v).all() for v in params.values())
    assert any(np.any(params[k] != first[k]) for k in params), "No actual learned update"
    bundle = {"version": VERSION, "architecture": architecture, "include_context": context, "include_edges": edges,
              "qualified": False, "calibrated": False, "parameters": {k: v.tolist() for k, v in params.items()}}
    return bundle, {"actual_fit_seconds": time.monotonic() - t, "epochs_executed": len(history), "initial_group_mean_BCE": history[0],
                    "last_preupdate_group_mean_BCE": history[-1], "epoch_BCE": history, "control_labels_changed": changed,
                    "training_rows": n, "training_groups": len(counts), "parameter_count": sum(v.size for v in params.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--prepare", action="store_true"); parser.add_argument("--fit", action="store_true")
    parser.add_argument("--approved-plan-sha"); args = parser.parse_args()
    if args.prepare and not args.fit: prepare()
    elif args.fit and not args.prepare: fit(args.approved_plan_sha)
    else: parser.error("Choose exactly one of --prepare/--fit")
