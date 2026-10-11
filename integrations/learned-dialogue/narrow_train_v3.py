"""Group-averaged sparse binary CE; actual CLI requires bound independent review."""
import argparse
import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path

from build_data import encoded, freeze
from context_v2 import binary_score_v2, feature_v2
from narrow_review_v3 import SEMANTICS, TASK, assess_reviews, sha
from train_v2 import HERE, strict_json


def fit_grouped(rows, include_context=True, epochs=80, max_features=384, seed=1729):
    """Mean CE within group, then across groups; no reliability/class weights."""
    if not rows or not 1 <= epochs <= 200 or not 32 <= max_features <= 512:
        raise ValueError("Bounded nonempty training configuration required")
    groups = {}
    for row in rows:
        if row["y"] not in (0, 1):
            raise ValueError("Ambiguous primary must be masked before fitting")
        groups.setdefault(row["group"], []).append(dict(row, features=feature_v2(row["snapshot"], include_context=include_context)))
    groups = {group: sorted(members, key=lambda r:r['id']) for group,members in sorted(groups.items())}
    # Frequency counts each feature once per group; descendants cannot dominate.
    frequency = Counter(key for members in groups.values() for key in {k for row in members for k in row["features"]})
    contexts = sorted(k for k in frequency if k.startswith("ctx:"))
    vocabulary = contexts[:max_features]
    vocabulary += [k for k in sorted(frequency, key=lambda k:(-frequency[k], k)) if k not in set(vocabulary)][:max_features-len(vocabulary)]
    vocabulary = sorted(vocabulary)
    allowed = set(vocabulary)
    for members in groups.values():
        for row in members:
            row["features"] = {k:v for k,v in row["features"].items() if k in allowed}
    head = {"bias": 0.0, "weights": dict.fromkeys(vocabulary, 0.0)}
    losses = []
    for epoch in range(epochs):
        gradient, bias_gradient, loss = dict.fromkeys(vocabulary, 0.0), 0.0, 0.0
        for members in groups.values():
            for row in members:
                p = binary_score_v2(head, row["features"])
                scale = 1 / (len(groups) * len(members))
                error = (p-row["y"]) * scale
                bias_gradient += error
                loss -= scale * math.log(max(p if row["y"] else 1-p, 1e-15))
                for key, value in row["features"].items():
                    gradient[key] += error * value
        step = .7 / math.sqrt(1 + epoch / 10)
        head["bias"] -= step * bias_gradient
        for key in vocabulary:
            head["weights"][key] -= step * (gradient[key] + .0002 * head["weights"][key])
        losses.append(loss)
    model = {"format":"grouped-primary-payment-binary.v3", "task":TASK, "semantics":SEMANTICS,
             "include_context":include_context, "vocabulary":vocabulary, "head":head,
             "objective":"Mean masked CE within each lineage group, then mean across groups; L2=.0002",
             "config":{"epochs":epochs,"max_features":max_features,"seed":seed,"class_weights":"none; unweighted control"},
             "support":{"rows":len(rows),"lineage_groups":len(groups),"positive_groups":len({r['group'] for r in rows if r['y']==1}),"negative_groups":len({r['group'] for r in rows if r['y']==0})},
             "calibrated":False,"qualified":False}
    return model, losses


def binary_diagnostic(snapshot, model):
    f = feature_v2(snapshot, include_context=model["include_context"])
    return {"task":TASK, "raw_score":binary_score_v2(model["head"], f), "decision":"abstain",
            "calibrated_probability":None, "qualified":False,
            "negative_semantics":"Not this primary act; no behavioral authority", "wire_mapping":"Offline sidecar only; no new intent or permission"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reviews", type=Path, required=True)
    parser.add_argument("--parent-review-authorization", type=Path, required=True)
    args = parser.parse_args()
    folder = HERE / "narrow-v3"
    packet_bytes = (folder / "review-packet.json").read_bytes()
    review_bytes = args.reviews.read_bytes()
    packet, reviews = strict_json(packet_bytes), strict_json(review_bytes)
    authorization = strict_json(args.parent_review_authorization.read_bytes())
    # Hashes bind exact canonical bytes; canonical files are required, never rewritten.
    if packet_bytes != encoded(packet) or review_bytes != encoded(reviews):
        raise ValueError("Review/packet must use canonical frozen encoded JSON bytes")
    readiness = assess_reviews(packet, reviews, authorization)
    if not readiness["admitted"]:
        raise ValueError("Review gate closed: " + ", ".join(readiness["reasons"]))
    output = folder / "model-reviewed.json"
    if output.exists():
        raise ValueError("Reviewed binary experiment already frozen")
    rows = readiness["eligible_rows"]
    model, losses = fit_grouped(rows)
    no_context, _ = fit_grouped(rows, include_context=False)
    null_rows = [dict(row) for row in rows]
    labels = [r["y"] for r in null_rows]
    random.Random(4313).shuffle(labels)
    for row, label in zip(null_rows, labels):
        row["y"] = label
    null_model, _ = fit_grouped(null_rows)
    model["source_binding"] = {"packet_sha256":sha(packet_bytes),"review_sha256":sha(review_bytes),
                               "authorization_sha256":sha(args.parent_review_authorization.read_bytes())}
    freeze(output, encoded(model))
    freeze(folder / "no-context-reviewed.json", encoded(no_context))
    freeze(folder / "shuffled-train-labels.json", encoded(null_model))
    freeze(folder / "train-losses.json", encoded({"epoch_group_ce":losses,"no_development_or_qualification_metrics_claimed":True}))
    print(json.dumps({"model_id":sha(encoded(model)),"support":model['support'],"qualified":False,"gpu_authorized":False},indent=2))


if __name__ == '__main__':
    main()
