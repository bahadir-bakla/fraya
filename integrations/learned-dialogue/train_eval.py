"""Bounded offline CPU fitting, calibration and untouched holdout evaluation."""
import argparse
import hashlib
import json
import math
import random
import time
from collections import Counter
from pathlib import Path

from inference import FORMAT, HEADS, LABELS, features, local_snapshot, predict, score, softmax, words

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREFIX = ROOT / "research/customer-benchmark/learned-dialogue-data"


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def integrity(records):
    """Reject shared groups, identical normalized text and augmented ancestors."""
    groups, fingerprints, by_id = {}, {}, {}
    for record in records:
        if record["id"] in by_id:
            raise ValueError("Duplicate record ID")
        by_id[record["id"]] = record
        if record["split"] not in {"train", "calibration", "holdout"}:
            raise ValueError("Unknown split")
        if not record["provenance"]["fictional"] or record["provenance"]["policy_oracle"]:
            raise ValueError("Fictional semantic-only data required")
        for dimension in ("semantic_template_group", "source_group", "scenario_family"):
            key = (dimension, record[dimension])
            if not record[dimension] or (key in groups and groups[key] != record["split"]):
                raise ValueError("Cross-split group leakage: " + str(key))
            groups[key] = record["split"]
        fingerprint = " ".join(words(record["utterance"]))
        if fingerprint in fingerprints:
            raise ValueError("Repeated normalized utterance")
        fingerprints[fingerprint] = record["split"]
    for record in records:
        seen, parent = {record["id"]}, record["augmentation_parent"]
        while parent:
            if parent not in by_id or parent in seen:
                raise ValueError("Missing/cyclic augmentation parent")
            seen.add(parent)
            ancestor = by_id[parent]
            if ancestor["split"] != record["split"]:
                raise ValueError("Augmentation ancestor crossed split")
            for key in ("semantic_template_group", "source_group", "scenario_family"):
                if ancestor[key] != record[key]:
                    raise ValueError("Augmentation group drift")
            parent = ancestor["augmentation_parent"]
    return {"passed": True, "records": len(records), "duplicate_normalized_text": 0,
            "cross_split_group_overlaps": 0, "augmentation_records": sum(r["augmentation_parent"] is not None for r in records),
            "group_counts": {dim: {split: len({r[dim] for r in records if r["split"] == split})
                                  for split in ("train", "calibration", "holdout")}
                             for dim in ("semantic_template_group", "source_group", "scenario_family")},
            "limitation": "Declared semantic families manually authored; no independent semantic-equivalence adjudication"}


def load_data():
    manifest = read_json(Path(str(PREFIX) + ".manifest.json"))
    for suffix, key in (("jsonl", "record_sha256"), ("oracle.json", "oracle_sha256"), ("sources.json", "sources_sha256")):
        if digest(Path(str(PREFIX) + "." + suffix).read_bytes()) != manifest[key]:
            raise ValueError("Frozen data/oracle/source hash mismatch: " + suffix)
    records = [json.loads(line) for line in Path(str(PREFIX) + ".jsonl").read_text(encoding="utf-8").splitlines()]
    oracle = read_json(Path(str(PREFIX) + ".oracle.json"))["labels"]
    if set(oracle) != {r["id"] for r in records}:
        raise ValueError("Oracle/record IDs differ")
    for record in records:
        if any(head in record for head in HEADS):
            raise ValueError("Labels must remain outside feature records")
        label = oracle[record["id"]]
        for head in HEADS:
            if label[head] not in LABELS[head]:
                raise ValueError("Invalid semantic label")
        if type(label["must_abstain"]) is not bool:
            raise ValueError("Invalid abstention oracle")
    check = integrity(records)
    if dict(Counter(r["split"] for r in records)) != manifest["split_counts"]:
        raise ValueError("Split count mismatch")
    return records, oracle, manifest, check


def fit(records, oracle, epochs=100, seed=2718):
    if any(r["split"] != "train" for r in records):
        raise ValueError("Fitting accepts training records only")
    model = {"format": FORMAT, "heads": {}, "word_vocabulary": sorted({w for r in records for w in words(r["utterance"])}),
             "calibration": {"fitted": False, "threshold": 1.1},
             "training": {"seed": seed, "epochs": epochs, "learning_rate": 0.7,
                          "regularization": "sparse active-coordinate L2=0.0002; not dense global L2",
                          "features": "L2-normalized word unigram/bigram and character trigram counts",
                          "loss": "sum of four independent multiclass cross-entropies"}}
    vectors = {r["id"]: features(r["utterance"]) for r in records}
    for name in HEADS:
        model["heads"][name] = {"labels": list(LABELS[name]), "bias": [0.0] * len(LABELS[name]),
                                "weights": [{} for _ in LABELS[name]], "temperature": 1.0}
    rng = random.Random(seed)
    order = list(records)
    losses = []
    for epoch in range(epochs):
        rng.shuffle(order)
        eta, loss = 0.7 / math.sqrt(1 + epoch / 10), 0.0
        for record in order:
            vector, target = vectors[record["id"]], oracle[record["id"]]
            for name in HEADS:
                head = model["heads"][name]
                gold = head["labels"].index(target[name])
                logits = [b + sum(w.get(k, 0.0) * v for k, v in vector.items()) for b, w in zip(head["bias"], head["weights"])]
                probs = softmax(logits)
                loss -= math.log(max(probs[gold], 1e-15))
                for index, weight in enumerate(head["weights"]):
                    error = probs[index] - int(index == gold)
                    head["bias"][index] -= eta * error
                    for key, value in vector.items():
                        old = weight.get(key, 0.0)
                        weight[key] = old - eta * (error * value + 0.0002 * old)
        losses.append(loss / (len(records) * len(HEADS)))
    return model, losses


def calibrate(model, records, oracle):
    if any(r["split"] != "calibration" for r in records):
        raise ValueError("Calibration accepts calibration records only")
    temperatures = {}
    for name in HEADS:
        choices = []
        for temperature in (0.5, 0.75, 1.0, 1.5, 2.0, 3.0):
            model["heads"][name]["temperature"] = temperature
            nll = sum(-math.log(max(score(model, r["utterance"])[1][name]["distribution"][oracle[r["id"]][name]], 1e-15)) for r in records) / len(records)
            choices.append((nll, temperature))
        nll, temperature = min(choices)
        model["heads"][name]["temperature"] = temperature
        temperatures[name] = {"temperature": temperature, "calibration_nll": nll}
    model["calibration"] = {"fitted": True, "threshold": 1.1, "temperatures": temperatures,
                            "rule": "maximize accepted calibration count with >=3 accepted and empirical joint error <=0.10; ties choose higher threshold",
                            "statistical_guarantee": False,
                            "reuse_limitation": "Same small calibration set fits temperature and selects threshold; calibration metrics are optimistic"}
    candidates = []
    sweep = []
    for threshold in (0.4, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.1):
        model["calibration"]["threshold"] = threshold
        accepted, errors = 0, 0
        for record in records:
            proposal = predict(local_snapshot(record["utterance"], record["id"]), model)
            if not proposal["abstain"]:
                accepted += 1
                errors += any(proposal["candidate"][h] != oracle[record["id"]][h] for h in HEADS)
        sweep.append({"threshold": threshold, "accepted": accepted, "joint_errors": errors})
        if accepted >= 3 and errors / accepted <= 0.10:
            candidates.append((accepted, threshold))
    model["calibration"]["threshold"] = max(candidates)[1] if candidates else 1.1
    model["calibration"]["sweep"] = sweep
    return model["calibration"]


def wilson_upper(errors, n):
    if not n:
        return None
    z, p = 1.96, errors / n
    return (p + z * z / (2 * n) + z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def evaluate(model, records, oracle):
    correct = Counter()
    exact, accepted, accepted_errors, uncertain, uncertain_abstained = 0, 0, 0, 0, 0
    rows, confusion, strata = [], Counter(), {}
    nll, brier = Counter(), Counter()
    for record in records:
        gold = oracle[record["id"]]
        raw, probabilities = score(model, record["utterance"])
        proposal = predict(local_snapshot(record["utterance"], record["id"]), model)
        for head in HEADS:
            correct[head] += raw[head] == gold[head]
            distribution = probabilities[head]["distribution"]
            nll[head] -= math.log(max(distribution[gold[head]], 1e-15))
            brier[head] += sum((p - int(label == gold[head])) ** 2 for label, p in distribution.items())
        exact += all(raw[h] == gold[h] for h in HEADS)
        confusion[(gold["primaryintent"], raw["primaryintent"])] += 1
        accepted += not proposal["abstain"]
        accepted_errors += not proposal["abstain"] and (gold["must_abstain"] or any(proposal["candidate"][h] != gold[h] for h in HEADS))
        uncertain += gold["must_abstain"]
        uncertain_abstained += gold["must_abstain"] and proposal["abstain"]
        bucket = strata.setdefault(gold["completion"], {"n": 0, "abstained": 0, "raw_joint_correct": 0})
        bucket["n"] += 1
        bucket["abstained"] += proposal["abstain"]
        bucket["raw_joint_correct"] += all(raw[h] == gold[h] for h in HEADS)
        rows.append({"id": record["id"], "raw_candidate": raw, "proposal_candidate": proposal["candidate"],
                     "oracle": gold, "abstain": proposal["abstain"], "reasons": proposal["reasons"],
                     "joint_score": proposal["confidence"]["joint_score"]})
    count = len(records)
    return {"n": count, "raw_head_accuracy": {h: correct[h] / count for h in HEADS},
            "raw_joint_exact_accuracy": exact / count, "accepted": accepted, "coverage": accepted / count,
            "accepted_joint_errors": accepted_errors, "accepted_joint_accuracy": 1 - accepted_errors / accepted if accepted else None,
            "accepted_error_wilson_95_upper": wilson_upper(accepted_errors, accepted),
            "uncertain_n": uncertain, "uncertain_abstained": uncertain_abstained,
            "uncertainty_abstention_recall": uncertain_abstained / uncertain if uncertain else None,
            "nll": {h: nll[h] / count for h in HEADS}, "multiclass_brier": {h: brier[h] / count for h in HEADS},
            "primary_confusion": [{"gold": a, "predicted": b, "count": n} for (a, b), n in sorted(confusion.items())],
            "completion_strata": strata, "rows": rows}


def validate_model(model):
    if model.get("format") != FORMAT or set(model["heads"]) != set(HEADS):
        raise ValueError("Invalid bundle format/heads")
    for name, head in model["heads"].items():
        if head["labels"] != list(LABELS[name]) or len(head["weights"]) != len(head["labels"]) or len(head["bias"]) != len(head["labels"]):
            raise ValueError("Invalid head dimensions/labels")
        values = head["bias"] + [v for w in head["weights"] for v in w.values()] + [head["temperature"]]
        if not all(type(v) in (int, float) and math.isfinite(v) for v in values) or head["temperature"] <= 0:
            raise ValueError("Invalid numerical parameters")
        if any(not isinstance(k, str) or not k.startswith(("w:", "b:", "c:")) for w in head["weights"] for k in w):
            raise ValueError("Invalid feature key")
    threshold = model["calibration"]["threshold"]
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1.1:
        raise ValueError("Invalid confidence threshold")
    return model


def load_model(path=HERE / "model.json"):
    return validate_model(read_json(path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.epochs <= 300:
        parser.error("epochs must be in 1..300")
    if any(p.exists() for p in (HERE / "model.json", ROOT / "analysis/night-learned-dialogue.train.json", ROOT / "analysis/night-learned-dialogue.eval.json")):
        parser.error("V1 artifacts already frozen. Use a separately versioned experiment; never overwrite or retune this holdout.")
    start = time.perf_counter()
    records, oracle, manifest, check = load_data()
    subsets = {split: [r for r in records if r["split"] == split] for split in ("train", "calibration", "holdout")}
    model, losses = fit(subsets["train"], oracle, args.epochs)
    fit_seconds = time.perf_counter() - start
    pre = evaluate(model, subsets["train"], oracle)
    calibration = calibrate(model, subsets["calibration"], oracle)
    model["data_binding"] = manifest
    validate_model(model)
    write_json(HERE / "model.json", model)
    restored = load_model()
    roundtrip = all(predict(local_snapshot(r["utterance"], r["id"]), model) == predict(local_snapshot(r["utterance"], r["id"]), restored) for r in records)
    train_metrics = {"phase": "training_only", "model": FORMAT, "training_records": len(subsets["train"]),
                     "fit_seconds": fit_seconds, "epoch_loss": losses, "pre_calibration_raw_metrics": pre,
                     "train_metrics_are_resubstitution": True, "data_binding": manifest}
    eval_metrics = {"phase": "post_fit_calibration_and_once_frozen_holdout", "split_integrity": check,
                    "calibration_configuration": calibration,
                    "calibration": evaluate(restored, subsets["calibration"], oracle),
                    "holdout": evaluate(restored, subsets["holdout"], oracle),
                    "persistence_roundtrip_exact": roundtrip,
                    "model_sha256": digest((HERE / "model.json").read_bytes()),
                    "model_bytes": (HERE / "model.json").stat().st_size,
                    "total_seconds": time.perf_counter() - start,
                    "scope": "Small English synthetic semantic classification only; no bank-policy, ASR, hidden-set, Freya-runtime or generalization success claim"}
    write_json(ROOT / "analysis/night-learned-dialogue.train.json", train_metrics)
    write_json(ROOT / "analysis/night-learned-dialogue.eval.json", eval_metrics)
    print(json.dumps({"fit_seconds": fit_seconds, "total_seconds": eval_metrics["total_seconds"],
                      "train_raw_joint": pre["raw_joint_exact_accuracy"], "threshold": calibration["threshold"],
                      "calibration": {k: v for k, v in eval_metrics["calibration"].items() if k in {"n", "raw_joint_exact_accuracy", "accepted", "accepted_joint_errors", "coverage", "uncertainty_abstention_recall"}},
                      "holdout": {k: v for k, v in eval_metrics["holdout"].items() if k in {"n", "raw_head_accuracy", "raw_joint_exact_accuracy", "accepted", "accepted_joint_errors", "coverage", "uncertainty_abstention_recall", "accepted_error_wilson_95_upper"}},
                      "roundtrip": roundtrip, "model_bytes": eval_metrics["model_bytes"]}, indent=2))


if __name__ == "__main__":
    main()
