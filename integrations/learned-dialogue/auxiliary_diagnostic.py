"""Inspect frozen public-intent proposals locally; no bank or platform calls."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from verified_auxiliary_bundle import BundleRejected, load_auxiliary

ROOT = Path(__file__).resolve().parents[2]
FREEZE_PATH = ROOT / "integrations/learned-dialogue/day2_public_freeze_v2.json"
FREEZE_SHA = "846904edf6afd341b54f0eb1d1f791bdbe90fa4a65b5882179d08b7e19138830"
RUNTIME_PATH = "integrations/learned-dialogue/day2_public_model_v2.py"
TAXONOMY_PATH = "research/customer-benchmark/day2-training-data/taxonomy.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def public_model(family):
    if family not in {"gnn", "no_edges", "sparse"} or sha(FREEZE_PATH) != FREEZE_SHA:
        raise BundleRejected("Frozen experiment anchor mismatch")
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf8"))
    if sha(ROOT / RUNTIME_PATH) != freeze["source_sha256"][RUNTIME_PATH]:
        raise BundleRejected("Inference source digest mismatch")
    if sha(ROOT / TAXONOMY_PATH) != freeze["input_sha256"][TAXONOMY_PATH]:
        raise BundleRejected("Taxonomy digest mismatch")
    taxonomy = json.loads((ROOT / TAXONOMY_PATH).read_text(encoding="utf8"))
    labels = [item["source_label"] for item in taxonomy["labels"]]
    relative = "integrations/learned-dialogue/day2_public_model_v2." + family + ".json"
    return load_auxiliary(ROOT / relative, expected_sha256=freeze["models_sha256"][relative],
                          expected_labels=labels, kind="public_intent_v2")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("gnn", "no_edges", "sparse"), default="gnn")
    parser.add_argument("--text", action="append", required=True)
    args = parser.parse_args()
    model = public_model(args.family)
    # Import only after the committed source digest has been verified.
    from day2_public_model_v2 import predict
    results = []
    for text in args.text:
        started = time.perf_counter()
        result = predict(text, model)
        result["inference_ms"] = (time.perf_counter() - started) * 1000
        results.append(result)
    print(json.dumps({"model": args.family, "scope": "offline diagnostic",
                      "bank_authority": "none", "proposals": results},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
