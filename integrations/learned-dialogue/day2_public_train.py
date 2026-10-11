"""Source-pinned publisher-TRAIN auxiliary experiment. No fit without new grant.

Field mappings are explicit CLI arguments to accept the collection worker's
final packet without inventing taxonomy labels, record ancestry or provenance.
"""
import argparse
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from day2_public_model import VERSION, WIDTH, HIDDEN, MAX_NODES, source_graph

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA_ROOT = (ROOT / "research/customer-benchmark/day2-training-data").resolve()
PLAN = HERE / "day2_public_plan.json"
SEED = 20261012


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf8") as f:
        json.dump(value, f, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")); f.write("\n")


def data_path(path):
    resolved = (ROOT / path).resolve()
    if not resolved.is_relative_to(DATA_ROOT): raise ValueError("Only the assigned public-data packet directory is allowed")
    if "test" in resolved.name.casefold() or "holdout" in resolved.name.casefold(): raise ValueError("Publisher TEST/holdout forbidden")
    return resolved


def pointer(value, path):
    for key in path.split(".") if path else []:
        if type(value) is not dict or key not in value: raise ValueError("Explicit missing field: " + path)
        value = value[key]
    return value


def packet_rows(path, records_field):
    p = data_path(path)
    if p.suffix == ".jsonl": return [json.loads(line) for line in p.read_text(encoding="utf8").splitlines() if line.strip()]
    value = json.loads(p.read_text(encoding="utf8"))
    rows = pointer(value, records_field)
    if type(rows) is not list: raise ValueError("Configured records field must be a list")
    return rows


def load(config):
    rows = packet_rows(config["packet"], config["records_field"])
    if config.get("evaluation_packet"):
        rows += packet_rows(config["evaluation_packet"], config["records_field"])
    required = ("id_field", "text_field", "label_field", "group_field", "publisher_split_field")
    parent = {}; processed = []; signatures = {}; publisher_order = {}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def join(a, b):
        a, b = find(a), find(b)
        if a != b: parent[max(a, b)] = min(a, b)
    for raw in rows:
        fields = {k: pointer(raw, config[k]) for k in required}
        record_id, text, label, group, split = [fields[k] for k in required]
        if any(type(v) is not str or not v for v in (record_id, text, label, group, split)): raise ValueError("Scalar publisher/source fields required")
        if split != config["publisher_train_value"]: raise ValueError("Only original publisher TRAIN is authorized")
        assigned = pointer(raw, config["prepared_split_field"]) if config.get("evaluation_packet") else None
        if assigned is not None and assigned not in {config["fit_split_value"], config["evaluation_split_value"]}:
            raise ValueError("Only worker-assigned fit/eval partitions may enter; calibration stays unread")
        if config.get("label_id_field"):
            label_id = pointer(raw, config["label_id_field"])
            if type(label_id) is not int or not 0 <= label_id < 77: raise ValueError("Publisher taxonomy ID required")
            if label_id in publisher_order and publisher_order[label_id] != label: raise ValueError("Publisher label ID/name inconsistency")
            publisher_order[label_id] = label
        if record_id in parent: raise ValueError("Duplicate source record ID")
        parent[record_id] = record_id
        skeleton = re.sub(r"\d+(?:st|nd|rd|th)?", "number", text.casefold())
        skeleton = " ".join(re.findall(r"\w+", skeleton))
        for key in (("worker_group", group), ("delex_source_skeleton", skeleton)):
            if key in signatures: join(record_id, signatures[key])
            signatures[key] = record_id
        mask = True
        if config.get("mask_field"):
            mask = pointer(raw, config["mask_field"])
            if type(mask) is not bool: raise ValueError("Actual observation mask must be literal bool")
        graph = source_graph(text)
        processed.append({"id": record_id, "text": text, "publisher_label": label, "worker_group": group,
                          "worker_assigned_split": assigned,
                          "observed_mask": mask and graph is not None,
                          "mask_reasons": ([] if mask else ["worker_observation_mask"]) + ([] if graph is not None else ["unsupported_source"]),
                          "qualified": False})
    members = {}
    for r in processed: members.setdefault(find(r["id"]), []).append(r["id"])
    groups = {k: "public-union-" + hashlib.sha256("\n".join(sorted(v)).encode()).hexdigest()[:24] for k, v in members.items()}
    labels = [publisher_order[i] for i in range(77)] if config.get("label_id_field") and len(publisher_order) == 77 else sorted({r["publisher_label"] for r in processed if r["observed_mask"]})
    if len(labels) != 77: raise ValueError("BANKING77 packet must expose exactly its 77 publisher intent names")
    for r in processed:
        r["canonical_group"] = groups[find(r["id"])]
        # Assignment is source-group-only. No model score/label selects a fold.
        if config.get("evaluation_packet"):
            r["partition"] = "fit" if r["worker_assigned_split"] == config["fit_split_value"] else "internal_publisher_TRAIN_eval"
        else:
            token = hashlib.sha256((str(SEED) + r["canonical_group"]).encode()).digest()
            r["partition"] = "internal_publisher_TRAIN_eval" if int.from_bytes(token[:4], "little") % 5 == 0 else "fit"
    split_groups = {}
    for r in processed:
        group = r["canonical_group"]
        if group in split_groups and split_groups[group] != r["partition"]:
            raise ValueError("Conservative source union crosses worker partitions; do not relabel/repartition")
        split_groups[group] = r["partition"]
    return processed, labels


def check_frozen():
    anchor = ROOT / "integrations/learned-dialogue/day2_model.freeze.json"
    if sha(anchor) != "9081a4c4e5b8fd0ed208fcc0c313700f576d266a0970f5fa4b38b5dd8b169b4d": raise ValueError("Frozen day2 anchor changed")
    previous = json.loads(anchor.read_text(encoding="utf8"))
    for path, expected in {**previous["historical_protected_sha256"], **previous["sha256"]}.items():
        if sha(ROOT / path) != expected: raise ValueError("Frozen bytes changed: " + path)
    return {str(anchor.relative_to(ROOT)).replace("\\", "/"): sha(anchor)}


def prepare(args):
    if PLAN.exists(): raise ValueError("Public plan already frozen")
    packet, manifest = data_path(args.packet), data_path(args.manifest)
    if sha(packet) != args.packet_sha or sha(manifest) != args.manifest_sha: raise ValueError("Worker handoff SHA mismatch")
    if args.evaluation_packet and sha(data_path(args.evaluation_packet)) != args.evaluation_sha: raise ValueError("Worker eval packet SHA mismatch")
    config = {k: getattr(args, k) for k in ("packet", "manifest", "records_field", "id_field", "text_field", "label_field", "label_id_field", "group_field", "publisher_split_field", "publisher_train_value", "mask_field", "evaluation_packet", "prepared_split_field", "fit_split_value", "evaluation_split_value")}
    license_record = json.loads(manifest.read_text(encoding="utf8"))
    # Full manifest is pinned and retained for review. Parent must verify the
    # actual origin/license/translation and grouping, not a guessed filename.
    if license_record.get("status") != "ready_for_auxiliary_source_intent_training" or license_record.get("source", {}).get("license") != "CC-BY-4.0":
        raise ValueError("Actual ready publisher-source/license manifest required")
    for artifact in ("BANKING77-LICENSE.txt", "NOTICE.txt", "taxonomy.json", "validation.json"):
        specification = license_record["outputs"][artifact]
        if sha(data_path(specification["path"])) != specification["sha256"]: raise ValueError("Worker source/license/validation artifact hash mismatch")
    rows, labels = load(config)
    partitions = {}
    for split in ("fit", "internal_publisher_TRAIN_eval"):
        chosen = [r for r in rows if r["partition"] == split and r["observed_mask"]]
        partitions[split] = {"observed_rows": len(chosen), "groups": len({r["canonical_group"] for r in chosen}),
                             "class_rows": dict(Counter(r["publisher_label"] for r in chosen))}
    if any(len(p["class_rows"]) != 77 for p in partitions.values()): raise ValueError("Fixed source-group split lacks a publisher class; do not score-tune/resplit")
    from day2_public_eval import source_tests
    tests = source_tests()
    inputs = {args.packet: sha(packet), args.manifest: sha(manifest)}
    if args.evaluation_packet: inputs[args.evaluation_packet] = sha(data_path(args.evaluation_packet))
    for artifact in ("BANKING77-LICENSE.txt", "NOTICE.txt", "taxonomy.json", "validation.json"):
        specification = license_record["outputs"][artifact]; inputs[specification["path"]] = specification["sha256"]
    plan = {"version": "day2.public_cpu_plan.v1", "status": "AWAITING_NEW_EXACT_HASH_PARENT_CPU_AUTHORIZATION", "config": config,
            "source_sha256": {str((HERE / p).relative_to(ROOT)).replace("\\", "/"): sha(HERE / p) for p in ("day2_public_model.py", "day2_public_train.py", "day2_public_eval.py")},
            "input_sha256": inputs, "worker_manifest_literal": license_record,
            "publisher_labels": labels, "partitions": partitions,
            "row_mask_partitions": [{k: v for k, v in r.items() if k != "text"} for r in rows],
            "known_group_overlap": 0, "group_definition": "Preserve worker-assigned train/eval groups; add exact delexicalized raw-source skeleton unions, including masked aliases; crossing assigned partitions fails closed. No independent/IID ancestry proof.",
            "original_publisher_split": "TRAIN only", "publisher_TEST_read": False, "worker_calibration_file_read": False,
            "objective": "77-way publisher-intent auxiliary cross-entropy; learned representation/routing only; no policy adaptation, collection consent, amounts, tools or permission labels",
            "models": ["sparse_softmax", "tiny_relational_gnn", "tiny_relational_gnn_no_edges"],
            "hyperparameters": {"seed": SEED, "width": WIDTH, "hidden": HIDDEN, "max_nodes": MAX_NODES, "epochs": 120, "adam_lr": 0.02, "l2": 0.0005,
                                "loss": "mean across within-corpus canonical groups then their observed rows; no class weights"},
            "resources": {"CPU_only": True, "fit_wall_max_seconds_total": 180, "per_fit_max_seconds": 55, "complete_bundle_byte_cap": 500000,
                          "NumPy": "2.3.5", "blas_threads": 1, "network": False, "GPU": False},
            "quantization": "Round exported coefficients to8 decimal places; report native full-precision vs stdlib exported score maxerror, decoder mismatches and persistence equality",
            "calibration": "None; fixed raw .8 confidence diagnostic only, no tuning on internal eval; deployed acceptance always zero",
            "frozen_anchor": check_frozen(), "source_tests": tests,
            "deployment": {"qualified": False, "acceptance": False, "bank_adaptation": "untrained_unreviewed", "admission_floor_20": "unchanged_closed"}}
    save(PLAN, plan)
    save(ROOT / "analysis/day2-public-model-experiment.json", {"status": plan["status"], "plan_sha256": sha(PLAN), "partitions": partitions,
                                                               "source_sha256": plan["source_sha256"], "input_sha256": plan["input_sha256"], "source_tests": tests, "fit_calls": 0})
    (ROOT / "analysis/day2-public-model-experiment.txt").write_text("Public data feeding actual executable CPU trainers is prepared; fit awaits NEW parent authorization.\nPlan SHA256:" + sha(PLAN) + "\n" + json.dumps(partitions, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"plan_sha256": sha(PLAN), "partitions": partitions, "source_tests": tests, "fit_calls": 0}))


def fit(approved):
    if not approved or sha(PLAN) != approved: raise ValueError("Fresh out-of-band exact public-plan grant required")
    plan = json.loads(PLAN.read_text(encoding="utf8"))
    for path, expected in {**plan["source_sha256"], **plan["input_sha256"], **plan["frozen_anchor"]}.items():
        if sha(ROOT / path) != expected: raise ValueError("Approved code/input hash drift")
    check_frozen()
    import numpy as np
    from threadpoolctl import threadpool_limits
    if np.__version__ != plan["resources"]["NumPy"]: raise ValueError("Unreviewed NumPy")
    rows, labels = load(plan["config"])
    if labels != plan["publisher_labels"] or [{k: v for k, v in r.items() if k != "text"} for r in rows] != plan["row_mask_partitions"]: raise ValueError("Source grouping/mask/label drift")
    selected = [r for r in rows if r["partition"] == "fit" and r["observed_mask"]]
    started = time.monotonic(); outputs = {}
    with threadpool_limits(limits=1):
        for name, architecture, edges in (("sparse", "sparse_softmax", True), ("gnn", "tiny_relational_gnn", True), ("no_edges", "tiny_relational_gnn", False)):
            if time.monotonic() - started >= 180: raise RuntimeError("Public CPU budget exceeded")
            model, history, native_parameters = train_arrays(selected, labels, architecture, edges, plan)
            model["approved_plan_sha256"] = approved
            path = HERE / ("day2_public_model." + name + ".json"); save(path, model)
            package_bytes = path.stat().st_size + (HERE / "day2_public_model.py").stat().st_size
            if package_bytes > 500000: raise ValueError("Complete runtime+weights footprint exceeded")
            outputs[name] = {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "bundle_bytes": path.stat().st_size,
                             "runtime_plus_bundle_bytes": package_bytes, "training": history, "native_parameters": native_parameters}
        from day2_public_eval import evaluate
        evaluate(rows, labels, outputs, plan, approved, time.monotonic() - started)


def train_arrays(rows, labels, architecture, edges, plan):
    import numpy as np
    started = time.monotonic(); rng = np.random.default_rng(SEED); n = len(rows); c = len(labels)
    x = np.zeros((n, MAX_NODES, WIDTH)); rootedge = np.zeros((n, MAX_NODES, MAX_NODES)); seqedge = rootedge.copy()
    linear = np.zeros((n, WIDTH)); pool = np.zeros((n, MAX_NODES)); y = np.array([labels.index(r["publisher_label"]) for r in rows])
    counts = Counter(r["canonical_group"] for r in rows); weight = np.array([1 / (len(counts) * counts[r["canonical_group"]]) for r in rows])
    for i, row in enumerate(rows):
        graph = source_graph(row["text"], edges)
        for j, node in enumerate(graph["nodes"]):
            for k, v in node.items(): x[i, j, k] = v
        for k, v in graph["linear"].items(): linear[i, k] = v
        for a, b, relation in graph["edges"]: (rootedge if relation == "turn_membership" else seqedge)[i, b, a] = 1
        for j in graph["user_nodes"]: pool[i, j] = 1 / len(graph["user_nodes"])
    if architecture == "sparse_softmax": p = {"weights": np.zeros((WIDTH, c)), "bias": np.zeros(c)}
    else:
        p = {"embedding": rng.normal(0, 0.1, (WIDTH, HIDDEN)), "embedding_bias": np.zeros(HIDDEN), "self": np.eye(HIDDEN),
             "turn_membership": rng.normal(0, 0.08, (HIDDEN, HIDDEN)), "source_order": rng.normal(0, 0.08, (HIDDEN, HIDDEN)),
             "message_bias": np.zeros(HIDDEN), "readout": rng.normal(0, 0.1, (HIDDEN, c)), "bias": np.zeros(c)}
    m1 = {k: np.zeros_like(v) for k, v in p.items()}; m2 = {k: np.zeros_like(v) for k, v in p.items()}; losses = []
    fit_start = time.monotonic()
    for epoch in range(plan["hyperparameters"]["epochs"]):
        if time.monotonic() - started > 55: raise RuntimeError("Per-model wall bound; preserve partial diagnostics, no automatic retry")
        if architecture == "sparse_softmax": logits = linear @ p["weights"] + p["bias"]
        else:
            h0 = np.tanh(x @ p["embedding"] + p["embedding_bias"]); rh, sh = rootedge @ h0, seqedge @ h0
            h1 = np.tanh(h0 @ p["self"] + rh @ p["turn_membership"] + sh @ p["source_order"] + p["message_bias"])
            pooled = np.einsum("bn,bnh->bh", pool, h1); logits = pooled @ p["readout"] + p["bias"]
        shifted = logits - logits.max(axis=1, keepdims=True); exp = np.exp(shifted); probabilities = exp / exp.sum(axis=1, keepdims=True)
        losses.append(float(np.sum(weight * -np.log(np.maximum(probabilities[np.arange(n), y], 1e-15)))))
        dz = probabilities.copy(); dz[np.arange(n), y] -= 1; dz *= weight[:, None]
        if architecture == "sparse_softmax": grad = {"weights": linear.T @ dz, "bias": dz.sum(axis=0)}
        else:
            dh1 = (dz @ p["readout"].T)[:, None, :] * pool[:, :, None] * (1 - h1 * h1)
            dh0 = dh1 @ p["self"].T + np.swapaxes(rootedge, 1, 2) @ (dh1 @ p["turn_membership"].T) + np.swapaxes(seqedge, 1, 2) @ (dh1 @ p["source_order"].T)
            de = dh0 * (1 - h0 * h0)
            grad = {"readout": pooled.T @ dz, "bias": dz.sum(axis=0), "message_bias": dh1.sum(axis=(0, 1)),
                    "self": np.einsum("bni,bnj->ij", h0, dh1), "turn_membership": np.einsum("bni,bnj->ij", rh, dh1), "source_order": np.einsum("bni,bnj->ij", sh, dh1),
                    "embedding": np.einsum("bni,bnj->ij", x, de), "embedding_bias": de.sum(axis=(0, 1))}
        for k in p:
            g = grad[k] + (0.0005 * p[k] if k not in {"bias", "message_bias", "embedding_bias"} else 0)
            m1[k] = 0.9 * m1[k] + 0.1 * g; m2[k] = 0.999 * m2[k] + 0.001 * g * g
            p[k] -= 0.02 * (m1[k] / (1 - 0.9 ** (epoch + 1))) / (np.sqrt(m2[k] / (1 - 0.999 ** (epoch + 1))) + 1e-8)
    assert all(np.isfinite(v).all() for v in p.values())
    model = {"version": VERSION, "architecture": architecture, "use_edges": edges, "publisher_labels": labels,
             "qualified": False, "calibrated": False, "bank_mapping": None,
             "parameters": {k: np.round(v, 8).tolist() for k, v in p.items()}}
    return model, {"epochs": len(losses), "optimizer_seconds": time.monotonic() - fit_start, "actual_preprocess_and_fit_seconds": time.monotonic() - started,
                   "observed_fit_rows": n, "canonical_fit_groups": len(counts), "coefficients": sum(v.size for v in p.values()),
                   "epoch_group_mean_CE": losses}, p


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--prepare", action="store_true"); ap.add_argument("--fit", action="store_true"); ap.add_argument("--approved-plan-sha")
    for flag in ("packet", "packet-sha", "manifest", "manifest-sha", "records-field", "id-field", "text-field", "label-field", "label-id-field", "group-field", "publisher-split-field", "mask-field", "evaluation-packet", "evaluation-sha", "prepared-split-field"): ap.add_argument("--" + flag)
    ap.add_argument("--fit-split-value", default="train"); ap.add_argument("--evaluation-split-value", default="eval")
    ap.add_argument("--publisher-train-value", default="train"); a = ap.parse_args()
    if a.prepare and not a.fit:
        if any(getattr(a, k) is None for k in ("packet", "packet_sha", "manifest", "manifest_sha", "records_field", "id_field", "text_field", "label_field", "group_field", "publisher_split_field")): ap.error("Explicit source field mapping and worker packet/manifest hashes required")
        prepare(a)
    elif a.fit and not a.prepare: fit(a.approved_plan_sha)
    else: ap.error("Exactly one of --prepare/--fit")
