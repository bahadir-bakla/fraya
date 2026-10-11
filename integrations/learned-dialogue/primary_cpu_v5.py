"""Fresh CPU sparse binary pilot. Fitting requires external v4 admission.

No torch, model reuse, network, cloud or permission decisions. Fixed TRAIN-only
five-fold controls are development diagnostics, never qualification.
"""
import hashlib
import json
import math
import random
import re
import time
from collections import Counter, defaultdict

import narrow_review_v4_1 as admission
from alignment_v5 import replay_surface_admission

VERSION = "primary_sparse.v5.0.cap1024.epochs80.groupmean"
MODES = ("context_text", "text_only", "context_only", "fragment_only", "constant", "group_shuffled")
CAP, EPOCHS, L2 = 1024, 80, .0002


def features(snapshot, mode="context_text"):
    """Exactly the same feature contract in table, training and pure scoring."""
    a = replay_surface_admission(snapshot)
    if not a["verified_current_source"] or not a["nonsecurity_value_free"] or not a["framing_complete"]:
        return {"eligible": False, "reason": "source_or_privacy_mask", "features": {}}
    text = snapshot["utterance"]["text"]
    if len(text) > 512:
        return {"eligible": False, "reason": "whole_primary_scope_exceeds_512", "features": {}}
    values = {}
    if mode not in ("context_only", "constant"):
        if mode == "fragment_only":
            text = text[-48:]
        words = re.findall(r"[a-z]+(?:['’][a-z]+)?|<number>|\.{3}|…", re.sub(r"\d+", "<number>", text.lower()))
        for w in words:
            values["w:" + w] = 1.
        for x, y in zip(words, words[1:]):
            values["b:" + x + "_" + y] = 1.
        normalized = " ".join(words)
        for n in (3, 4):
            for i in range(min(512, max(0, len(normalized) - n + 1))):
                values["c" + str(n) + ":" + normalized[i:i+n]] = 1.
    if mode not in ("text_only", "fragment_only", "constant"):
        for key, value in (("phase", snapshot.get("phase")), ("question", snapshot.get("question", {}).get("role"))):
            if value in {"payment", "callback", "readback", "recipient", "support", "date", "amount", "offer", "none"}:
                values["context:" + key + "=" + value] = 1.
        # Target identities/revisions and canonical values are deliberately absent.
        pending = snapshot.get("pending", [])
        for ordinal, target in enumerate(snapshot.get("question", {}).get("target_indices", [])):
            entry = next((p for p in pending if p.get("target_index") == target), {})
            for kind in ("amount", "date"):
                state = entry.get("components", {}).get(kind, {}).get("status")
                if state in {"absent", "complete", "unfinished", "ambiguous"}:
                    values[f"context:question_target_slot{ordinal}:{kind}={state}"] = 1.
    norm = sum(v*v for v in values.values()) ** .5 or 1.
    return {"eligible": True, "reason": None, "features": {k:v/norm for k,v in values.items()}}


def sigmoid(z):
    return 1 / (1 + math.exp(-max(-40., min(40., z))))


def group_weights(rows):
    counts = Counter(r["group"] for r in rows)
    return [1. / len(counts) / counts[r["group"]] for r in rows]


def fit(rows, mode="context_text", deadline=None):
    """Group-mean, unweighted CE. No class weights, threshold sweeps or reuse."""
    if not rows:
        raise ValueError("no_eligible_rows")
    extracted = [features(r["snapshot"], mode) for r in rows]
    if any(not f["eligible"] for f in extracted):
        raise ValueError("masked_row_passed_to_fit")
    counts = Counter(k for f in extracted for k in f["features"])
    vocabulary = sorted(counts, key=lambda k:(-counts[k], k))[:CAP]
    allowed = set(vocabulary)
    xs = [{k:v for k,v in f["features"].items() if k in allowed} for f in extracted]
    coefficients = dict.fromkeys(vocabulary, 0.)
    bias, weights = 0., group_weights(rows)
    for _ in range(EPOCHS):
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("parent_cpu_wall_limit")
        grad = {k:L2*v for k,v in coefficients.items()}
        gb = 0.
        for row, x, weight in zip(rows, xs, weights):
            residual = (sigmoid(bias + sum(coefficients[k]*v for k,v in x.items())) - row["y"]) * weight
            gb += residual
            for k,v in x.items():
                grad[k] += residual * v
        bias -= .8 * gb
        for k in coefficients:
            coefficients[k] -= .8 * grad[k]
    return {"schema_version": VERSION, "mode": mode, "vocabulary": vocabulary,
            "weights": coefficients, "bias": bias, "qualified": False, "decision": "abstain",
            "label_semantics": "primary is payment proposal only; binary zero grants no other inference"}


def predict(snapshot, bundle):
    if bundle.get("schema_version") != VERSION:
        raise ValueError("feature_version_mismatch")
    f = features(snapshot, bundle["mode"])
    if not f["eligible"]:
        return {"raw_score": None, "probability_uncalibrated": None, "decision": "abstain", "qualified": False}
    z = bundle["bias"] + sum(v*f["features"].get(k, 0.) for k,v in bundle["weights"].items())
    if not math.isfinite(z):
        raise ValueError("nonfinite_bundle")
    return {"raw_score": z, "probability_uncalibrated": sigmoid(z), "binary_diagnostic": int(z >= 0),
            "decision": "abstain", "qualified": False}


def fold(group):
    return int(hashlib.sha256(("predeclared-v5:" + group).encode()).hexdigest(), 16) % 5


def shuffle_group_targets(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["group"]].append(row["y"])
    roots = sorted(grouped)
    permuted = roots[:]
    random.Random(51011).shuffle(permuted)
    targets = dict(zip(roots, (grouped[g] for g in permuted)))
    counts = Counter()
    output = []
    for row in rows:
        g = row["group"]
        output.append({**row, "y": targets[g][counts[g] % len(targets[g])]})
        counts[g] += 1
    return output


def authorized_experiment(raw_inputs, authorization_raw, trusted_authorization_sha256, candidates, split_assignments):
    started = time.monotonic()
    auth = admission.strict_json(authorization_raw) if authorization_raw else {}
    if not auth or auth.get("max_cpu_experiment_seconds", 0) not in range(1,601):
        raise admission.AdmissionError("parent_cpu_wall_limit_missing")
    deadline = started + auth["max_cpu_experiment_seconds"]
    rows = admission.build_cpu_training_rows(raw_inputs, "primary", authorization_raw=authorization_raw,
            trusted_authorization_sha256=trusted_authorization_sha256, candidates=candidates, split_assignments=split_assignments)
    eligible = [r for r in rows if features(r["snapshot"])["eligible"]]
    positive = {r["group"] for r in eligible if r["y"] == 1}
    negative = {r["group"] for r in eligible if r["y"] == 0} - positive
    if len(positive) < 20 or len(negative) < 20:
        raise ValueError("feature_eligible_primary_group_floor_unmet")
    results = {}
    for mode in MODES:
        outputs = []
        for held in range(5):
            train = [r for r in eligible if fold(r["group"]) != held]
            test = [r for r in eligible if fold(r["group"]) == held]
            if not train or not test:
                raise ValueError("empty_fixed_fold")
            altered = shuffle_group_targets(train) if mode == "group_shuffled" else train
            bundle = fit(altered, "context_text" if mode == "group_shuffled" else mode, deadline)
            outputs.extend({"id": r["id"], "group": r["group"], "y": r["y"], "fold": held,
                            **predict(r["snapshot"], bundle)} for r in test)
        correct = [int(o["binary_diagnostic"] == o["y"]) for o in outputs]
        groups = sorted({o["group"] for o in outputs})
        balanced = sum(sum(o["binary_diagnostic"] == y for o in outputs if o["y"] == y) /
                       sum(o["y"] == y for o in outputs) for y in (0,1)) / 2
        results[mode] = {"row_accuracy": sum(correct)/len(correct), "balanced_row_accuracy": balanced,
            "group_macro_accuracy": sum(sum(o["binary_diagnostic"] == o["y"] for o in outputs if o["group"] == g)/
                                        sum(o["group"] == g for o in outputs) for g in groups)/len(groups),
            "rows": len(outputs), "groups": len(groups), "outputs": outputs}
    return {"schema_version": VERSION, "train_only_cross_validation": results,
            "new_dev_read": False, "qualified": False, "gpu_used": False,
            "final_bundle": fit(eligible, deadline=deadline), "fit_rows": len(eligible), "fit_groups": len({r["group"] for r in eligible}),
            "masked_by_feature_contract": len(rows)-len(eligible),
            "elapsed_seconds": time.monotonic()-started,
            "source_bindings": [r["source_binding"] for r in eligible],
            "group_shuffle_note": "Canonical-group label vectors permuted TRAIN-fold only; variable-length vectors cycled, class counts may change."}
