"""Masked context-aware CPU training. Reads independent worker train/dev only.

Never reads confirmation, OOD qualification, v1 holdout, or calibration labels.
No hyperparameter/threshold sweep. Every produced head is unqualified.
"""
import argparse
import hashlib
import json
import math
import random
import time
from collections import Counter
from pathlib import Path

from build_data import encoded, freeze
from audit_v2 import audit_splits, verify_manifest
from context_v2 import (ADMIN_LABELS, BindingContext, COMPONENTS, FORMAT_V2, INTENTS_V2, INPUT_KEYS,
                       _check_snapshot, binding_v2, distribution_v2, binary_score_v2, feature_v2, predict_v2)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HEAD_LABELS = {"primary": INTENTS_V2, "component_completion": ("absent", "complete", "unfinished", "ambiguous"),
               "component_polarity": ("asserted", "negated", "conditional", "questioned", "quoted", "unknown"),
               "correction": ("none", "replacement", "retraction", "refinement", "unresolved"),
               "target_scope": ("single", "explicit_set", "all_returned", "current_question", "unresolved")}


def strict_json(blob):
    def pairs(items):
        output = {}
        for key, value in items:
            if key in output:
                raise ValueError("Duplicate JSON key")
            output[key] = value
        return output
    def bad_constant(value):
        raise ValueError("Nonfinite JSON constant: " + value)
    def finite_float(value):
        result = float(value)
        if not -float("inf") < result < float("inf"):
            raise ValueError("Nonfinite JSON number")
        return result
    return json.loads(blob, object_pairs_hook=pairs, parse_constant=bad_constant, parse_float=finite_float)


def observed(labels, key):
    value = labels.get(key)
    if isinstance(value, dict) and "observed" in value:
        return value.get("value"), value["observed"] is True
    masks = labels.get("masks", labels.get("mask", {}))
    return value, masks.get(key) is True and value is not None


def reliability(record):
    annotation = record.get("annotation", {})
    status = annotation.get("status", annotation.get("adjudication_status", "unreviewed"))
    if status == "disputed":
        return 0.0
    reviewers = annotation.get("reviewer_ids", [])
    if status == "adjudicated" and len(set(reviewers)) >= 2:
        return 1.0
    if status in {"single_reviewed", "reviewed"}:
        return .5
    return .2


def worker_labels(record):
    """Project worker-authored literal frames and explicit masks; never infer labels.

    Multi-clause scope is masked because this prototype has no clause/target head.
    Absent or discontinuous components remain masked by prepare_examples.
    The original worker artifacts are read-only and hashed separately.
    """
    labels = record["labels"]
    if "frame" not in labels:
        return labels
    masks = labels.get("mask", {})
    clauses = labels["frame"].get("clauses", [])
    clause_masks = {row["clause_id"]: row for row in masks.get("clauses", [])}
    output = {key: {"value": labels.get(key), "observed": masks.get(key) is True}
              for key in ("primary_intent", "secondary_intents")}
    output["correction"] = {"value": labels.get("correction_kind"), "observed": masks.get("correction") is True}
    output["target_scope"] = {"value": clauses[0]["scope"] if len(clauses) == 1 else None,
                              "observed": len(clauses) == 1 and masks.get("target_scope") is True
                              and clause_masks.get(clauses[0]["clause_id"], {}).get("target_scope") is True}
    output["components"] = []
    for clause in clauses:
        component_masks = clause_masks.get(clause["clause_id"], {}).get("components", {})
        for component in clause.get("components", []):
            mask = component_masks.get(component["name"], {})
            output["components"].append({"name": component["name"], "evidence": component.get("evidence", []) if mask.get("evidence") is True else [],
                                          **{key: {"value": component[key], "observed": mask.get(key) is True}
                                             for key in ("completion", "polarity")}})
    return output


def prepare_examples(records, expected_split):
    if expected_split not in {"train", "development", "dev", "diagnostic_only"}:
        raise ValueError("Only worker train/development allowed")
    examples, report, seen = [], {"records": 0, "head_samples": Counter(), "masked_missing": Counter(), "groups": set()}, set()
    for record in records:
        record_id = record["example_id"]
        if record_id in seen:
            raise ValueError("Duplicate example ID")
        seen.add(record_id)
        if record["split"] not in ({"development", "dev"} if expected_split in {"development", "dev"} else {expected_split}):
            raise ValueError("Qualification/calibration/wrong split supplied to v2 training loader")
        group = record["lineage_group_id"]
        if not isinstance(group, str) or not group:
            raise ValueError("Lineage group required")
        report["groups"].add(group)
        snapshot = record["input"]
        reason = _check_snapshot(snapshot)
        if reason:
            raise ValueError("Invalid worker snapshot " + record_id + ": " + reason)
        if snapshot["utterance"]["source"] != "authored_fixture" and not record.get("source", {}).get("fictional", False):
            raise ValueError("Only fictional supplied examples accepted")
        labels, weight = worker_labels(record), reliability(record)
        vector = feature_v2(snapshot)
        for key, head_name in (("primary_intent", "primary"), ("correction", "correction"), ("target_scope", "target_scope")):
            value, mask = observed(labels, key)
            if mask:
                if value not in HEAD_LABELS[head_name]:
                    raise ValueError("Unsupported label: " + head_name)
                examples.append({"id": record_id, "group": group, "head": head_name, "label": value, "features": vector,
                                 "snapshot": snapshot, "weight": weight, "candidate": None})
                report["head_samples"][head_name] += 1
            else:
                report["masked_missing"][head_name] += 1
        value, mask = observed(labels, "secondary_intents")
        if mask:
            if not isinstance(value, list) or len(set(value)) != len(value) or any(label not in INTENTS_V2 for label in value):
                raise ValueError("Secondary must be reviewed unique multilabel set")
            examples.append({"id": record_id, "group": group, "head": "secondary", "label": value, "features": vector,
                             "snapshot": snapshot, "weight": weight, "candidate": None})
            report["head_samples"]["secondary"] += 1
        else:
            report["masked_missing"]["secondary"] += 1
        for component in labels.get("components", []):
            name = component["name"]
            if name not in COMPONENTS:
                raise ValueError("Unsupported component")
            spans = component.get("evidence", [])
            # Absent components have no raw spans and are masked, never inferred absent from regex miss.
            if not spans:
                report["masked_missing"]["component_without_evidence"] += 1
                continue
            start, end = min(s["start"] for s in spans), max(s["end"] for s in spans)
            for span in spans:
                if span.get("turn_id", snapshot["turn_id"]) != snapshot["turn_id"] or type(span["start"]) is not int or type(span["end"]) is not int or not 0 <= span["start"] < span["end"] <= len(snapshot["utterance"]["text"]):
                    raise ValueError("Invalid exact raw component span")
            if len(spans) != 1:
                # Candidate-span v2 cannot claim discontinuous/collective relation competence.
                report["masked_missing"]["discontinuous_component"] += 1
                continue
            candidate = {"name": name, "start": start, "end": end}
            features = feature_v2(snapshot, candidate)
            for key, head_name in (("completion", "component_completion"), ("polarity", "component_polarity")):
                value, mask = observed(component, key)
                if not mask:
                    report["masked_missing"][head_name] += 1
                    continue
                if value not in HEAD_LABELS[head_name]:
                    raise ValueError("Invalid component head label")
                examples.append({"id": record_id, "group": group, "head": head_name, "label": value,
                                 "features": features, "snapshot": snapshot, "weight": weight, "candidate": candidate})
                report["head_samples"][head_name] += 1
        report["records"] += 1
    return examples, {"records": report["records"], "lineage_group_count": len(report["groups"]),
                      "lineage_groups": sorted(report["groups"]), "head_samples": dict(report["head_samples"]),
                      "masked_missing": dict(report["masked_missing"])}


def fit_v2(examples, epochs=80, seed=1729, include_context=True, max_features=384):
    if not examples:
        raise ValueError("No observed training labels")
    if not 1 <= epochs <= 200 or not 32 <= max_features <= 512:
        raise ValueError("Bounded training configuration required")
    data = []
    for example in examples:
        row = dict(example)
        row["features"] = feature_v2(row["snapshot"], row["candidate"], include_context)
        data.append(row)
    frequency = Counter(key for row in data for key in row["features"])
    context_keys = sorted(k for k in frequency if k.startswith(("ctx:", "span:component=")))
    selected = context_keys[:max_features]
    selected += [k for k, _ in sorted(frequency.items(), key=lambda item: (-item[1], item[0])) if k not in set(selected)][:max_features - len(selected)]
    vocabulary = sorted(selected)
    vocabulary_lookup = set(vocabulary)
    for row in data:
        row["features"] = {key: value for key, value in row["features"].items() if key in vocabulary_lookup}
    model = {"format": FORMAT_V2, "include_context": include_context, "vocabulary": vocabulary, "heads": {}, "secondary": {},
             "config": {"epochs": epochs, "seed": seed, "max_features": max_features, "learning_rate": .7,
                        "feature_selection": "Train sample frequency; context keys retained; no development selection",
                        "loss": "Per-head normalized masked multiclass CE and secondary binary CE; sparse active-coordinate L2=0.0002"},
             "calibration": {"fitted": False, "risk_selected": False, "confirmation_seen": False}, "qualification": {}}
    counts = Counter(row["head"] for row in data)
    label_counts = {}
    for name, labels in HEAD_LABELS.items():
        model["heads"][name] = {"labels": list(labels), "bias": [0.0] * len(labels), "weights": [{} for _ in labels]}
        label_counts[name] = dict(Counter(row["label"] for row in data if row["head"] == name))
        model["qualification"][name] = {"trained": bool(counts[name]), "calibrated": False, "qualified": False,
                                        "observed_samples": counts[name], "label_counts": label_counts[name]}
    secondary_labels = sorted(set(ADMIN_LABELS) | {label for row in data if row["head"] == "secondary" for label in row["label"] if label not in {"unknown", "other"}})
    for label in secondary_labels:
        model["secondary"][label] = {"bias": 0.0, "weights": {}}
    model["qualification"]["secondary"] = {"trained": bool(counts["secondary"]), "calibrated": False, "qualified": False, "observed_samples": counts["secondary"]}
    for name in ("clause_segmentation", "target_ranking", "offer_ranking", "consent", "span_detection", "recipient", "allocation"):
        model["qualification"][name] = {"trained": False, "calibrated": False, "qualified": False, "observed_samples": 0}
    model["component_support"] = {
        component: {name: {"observed_samples": sum(row["head"] == name and row["candidate"] is not None and row["candidate"]["name"] == component for row in data),
                           "label_counts": dict(Counter(row["label"] for row in data if row["head"] == name and row["candidate"] is not None and row["candidate"]["name"] == component)),
                           "qualified": False}
                    for name in ("component_completion", "component_polarity")}
        for component in COMPONENTS}
    order, rng, epoch_losses = list(data), random.Random(seed), []
    # Each observed head contributes equally per epoch despite unequal span counts.
    scale = len(data) / max(1, len([n for n, count in counts.items() if count]))
    for epoch in range(epochs):
        rng.shuffle(order)
        losses = Counter()
        eta = .7 / math.sqrt(1 + epoch / 10)
        for row in order:
            f = row["features"]
            step = eta * row["weight"] * scale / max(1, counts[row["head"]])
            if row["head"] == "secondary":
                for label, head in model["secondary"].items():
                    p = binary_score_v2(head, f)
                    y = int(label in row["label"])
                    losses["secondary"] -= row["weight"] * math.log(max(p if y else 1-p, 1e-15)) / max(len(model["secondary"]), 1)
                    error = p - y
                    head["bias"] -= step * error
                    for key, value in f.items():
                        old = head["weights"].get(key, 0.0)
                        head["weights"][key] = old - step * (error * value + .0002 * old)
            else:
                head = model["heads"][row["head"]]
                p = distribution_v2(head, f)
                losses[row["head"]] -= row["weight"] * math.log(max(p[row["label"]], 1e-15))
                for index, label in enumerate(head["labels"]):
                    error = p[label] - int(label == row["label"])
                    head["bias"][index] -= step * error
                    for key, value in f.items():
                        old = head["weights"][index].get(key, 0.0)
                        head["weights"][index][key] = old - step * (error * value + .0002 * old)
        epoch_losses.append({name: loss / max(counts[name], 1) for name, loss in losses.items()})
    return model, epoch_losses


def evaluate_v2(model, examples):
    counts, correct, rows = Counter(), Counter(), []
    for example in examples:
        f = feature_v2(example["snapshot"], example["candidate"], model["include_context"])
        if example["head"] == "secondary":
            predicted = sorted(label for label, head in model["secondary"].items() if binary_score_v2(head, f) >= .5)
            actual = sorted(label for label in example["label"] if label not in {"unknown", "other"})
            match = predicted == actual
        else:
            probs = distribution_v2(model["heads"][example["head"]], f)
            predicted = max(probs, key=probs.get)
            actual = example["label"]
            match = predicted == actual
        counts[example["head"]] += 1
        correct[example["head"]] += match
        rows.append({"id": example["id"], "lineage_group": example["group"], "head": example["head"], "predicted": predicted, "label": actual, "correct": match})
    by_label = {}
    for row in rows:
        key = row["head"] + ":" + str(row["label"])
        entry = by_label.setdefault(key, {"n": 0, "correct": 0})
        entry["n"] += 1
        entry["correct"] += int(row["correct"])
    return {"head_n": dict(counts), "raw_head_accuracy": {name: correct[name] / count for name, count in counts.items()},
            "per_label_counts": by_label,
            "rows": rows, "qualified_acceptance": 0, "scope": "Masked train/development diagnostic only; no calibration, risk or qualification labels read"}


def load_worker_records(path):
    raw = path.read_bytes()
    value = strict_json(raw)
    records = value if isinstance(value, list) else value.get("records", value.get("examples"))
    if not isinstance(records, list):
        raise ValueError("Worker file requires records/examples array")
    return records, hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, default=ROOT / "research/customer-benchmark/context-semantic-v2-train.json")
    parser.add_argument("--dev", type=Path, default=ROOT / "research/customer-benchmark/context-semantic-v2-dev.json")
    parser.add_argument("--epochs", type=int, default=80)
    args = parser.parse_args()
    output = HERE / "model_v2.json"
    if output.exists():
        parser.error("Versioned v2 model already frozen; create a new experiment instead of overwrite")
    start = time.perf_counter()
    records, train_hash = load_worker_records(args.train)
    dev_records, dev_hash = load_worker_records(args.dev)
    manifest_path = ROOT / "research/customer-benchmark/context-semantic-v2-manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    verify_manifest(strict_json(manifest_bytes), args.train.read_bytes(), args.dev.read_bytes())
    integrity = audit_splits(records, dev_records)
    train, train_report = prepare_examples(records, "train")
    dev, dev_report = prepare_examples(dev_records, "development")
    if set(train_report["lineage_groups"]) & set(dev_report["lineage_groups"]):
        raise ValueError("Train/development lineage overlap")
    model, losses = fit_v2(train, epochs=args.epochs)
    model["source_binding"] = {"train_sha256": train_hash, "development_sha256": dev_hash,
                               "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                               "qualification_labels_read": False, "independent_adjudication_not_inferred_from_worker_name": True}
    model_bytes = encoded(model)
    model_id = hashlib.sha256(model_bytes).hexdigest()
    bundle = {"model_id": model_id, "model": model}
    diagnostic = {"train_data": train_report, "development_data": dev_report, "model_id": model_id,
                  "train": evaluate_v2(model, train), "development": evaluate_v2(model, dev),
                  "fit_seconds": time.perf_counter() - start, "include_context": True, "epochs": args.epochs,
                  "source_binding": model["source_binding"], "calibration": "Not performed; no supplied fit/risk sets",
                  "qualification": "All false; development metrics never treated as fresh unseen qualification",
                  "cloud_data_gate": False, "split_integrity": integrity,
                  "label_projection": "Worker literals and explicit masks only; no frame scores/status used; absent/no-span and discontinuous components masked; multi-clause target scope masked"}
    if hashlib.sha256(args.train.read_bytes()).hexdigest() != train_hash or hashlib.sha256(args.dev.read_bytes()).hexdigest() != dev_hash or manifest_path.read_bytes() != manifest_bytes:
        raise ValueError("Worker artifacts changed during fit; no results frozen")
    freeze(output, model_bytes)
    freeze(ROOT / "analysis/night-learned-dialogue.v2.train.json", encoded({"epoch_head_losses": losses, "data": train_report, "model_id": model_id}))
    freeze(ROOT / "analysis/night-learned-dialogue.v2.diagnostic.json", encoded(diagnostic))
    print(json.dumps({k:v for k,v in diagnostic.items() if k not in {"train", "development"}}, indent=2))
    print(json.dumps({"train_head_accuracy": diagnostic["train"]["raw_head_accuracy"], "dev_head_accuracy": diagnostic["development"]["raw_head_accuracy"]}, indent=2))


if __name__ == "__main__":
    main()
