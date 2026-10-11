"""Fixed diagnostic controls on supplied train/dev; no calibration or tuning."""
import copy
import hashlib
import json
import random
import time

from build_data import encoded, freeze
from context_v2 import BindingContext, binding_v2, predict_v2
from train_v2 import HERE, ROOT, evaluate_v2, fit_v2, load_worker_records, prepare_examples, strict_json


def main():
    path = HERE / "model_v2.json"
    raw = path.read_bytes()
    model = strict_json(raw)
    binding = model["source_binding"]
    train_rows, th = load_worker_records(ROOT / "research/customer-benchmark/context-semantic-v2-train.json")
    dev_rows, dh = load_worker_records(ROOT / "research/customer-benchmark/context-semantic-v2-dev.json")
    if th != binding["train_sha256"] or dh != binding["development_sha256"]:
        raise ValueError("Current worker data differs from frozen v2 sources")
    train, _ = prepare_examples(train_rows, "train")
    dev, _ = prepare_examples(dev_rows, "development")
    bundle = {"model_id": hashlib.sha256(raw).hexdigest(), "model": model}
    output = ROOT / "analysis/night-learned-dialogue.v2.controls.json"
    if output.exists():
        raise ValueError("Diagnostic controls already frozen")
    start = time.perf_counter()
    no_context, _ = fit_v2(train, epochs=model["config"]["epochs"], include_context=False)
    shuffled = copy.deepcopy(train)
    rng = random.Random(4313)
    for name in sorted({row["head"] for row in shuffled}):
        selected = [row for row in shuffled if row["head"] == name]
        labels = [row["label"] for row in selected]
        rng.shuffle(labels)
        for row, label in zip(selected, labels):
            row["label"] = label
    null_model, _ = fit_v2(shuffled, epochs=model["config"]["epochs"])
    runtime_status = []
    for row in dev_rows:
        snapshot = row["input"]
        proposal = predict_v2(snapshot, bundle, BindingContext(binding_v2(snapshot), bundle["model_id"]))
        runtime_status.append({"id": row["example_id"], "status": proposal["status"], "reasons": [a["reason"] for a in proposal["abstentions"]]})
    report = {"model_id": bundle["model_id"], "source_binding": binding,
              "guarded_runtime": {"qualified_acceptance": 0, "rows": runtime_status},
              "guards_only": {"primary_accuracy": None, "qualified_acceptance": 0, "rows": len(dev_rows),
                              "reason": "No semantic learner; unresolved raw input passed to independent deterministic authority only; abstain from semantic proposal"},
              "learned_only": evaluate_v2(model, dev),
              "no_context": evaluate_v2(no_context, dev),
              "shuffled_train_labels": evaluate_v2(null_model, dev),
              "control_seconds": time.perf_counter() - start,
              "limitations": "Fixed train/dev diagnostics only. No-context omits feature context and disables offer/readback/security heuristic context paths in runtime. Oracle-span scoring still uses supplied spans, so it is not a span detection evaluation. Shuffle is a deterministic train-label permutation within each head, not a statistical randomization test. No source independence, qualification, safety threshold or CPU ceiling proved."}
    freeze(output, encoded(report))
    print(json.dumps({name: report[name]["raw_head_accuracy"] for name in ("learned_only", "no_context", "shuffled_train_labels")}, indent=2))


if __name__ == "__main__":
    main()
