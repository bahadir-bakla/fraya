"""Strict packet adapter; final actual schema is pinned in the execution plan."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import numpy as np
from repayment_runtime import observed_text, features

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / "research/customer-benchmark/repayment-semantic"
HERE = Path(__file__).parent


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write_new(path, obj):
    with Path(path).open("xb") as f: f.write(encoded(obj))


def verify(pins):
    for path, digest in pins.items():
        if sha(ROOT / path) != digest: raise ValueError("Pinned source/input changed: " + path)


def snapshot(row):
    value = row["input"]
    observed_text(value)
    return value


def targets(row, labels):
    values = row["labels"]
    known = row["known_mask"]
    if type(values) is not dict or set(values) != set(labels) or type(known) is not dict or set(known) != set(labels): raise ValueError("Wrong semantic labels/masks")
    y, m = [], []
    for name in labels:
        v = values[name]
        if type(known[name]) is not bool or type(v) not in (bool, int) or v not in (0, 1): raise ValueError("Invalid binary target/known mask")
        y.append(float(v) if known[name] else 0.); m.append(float(known[name]))
    return y, m


def load_rows(path, split, labels, with_targets=True):
    rows = [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]
    ids = set()
    for row in rows:
        expected_split = {"train": "TRAIN", "calibration": "CAL", "eval": "HELDOUT"}[split]
        if row["split"] != expected_split or type(row["record_id"]) is not str or row["record_id"] in ids:
            raise ValueError("Split/identity mismatch")
        ids.add(row["record_id"])
        if type(row["group_id"]) is not str or not row["group_id"]: raise ValueError("Missing canonical group")
        snapshot(row)
        expected_input = hashlib.sha256(json.dumps(row["input"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if row["input_sha256"] != expected_input: raise ValueError("Raw observed input digest mismatch")
        if with_targets: targets(row, labels)
        if row.get("bank_authority", False) is not False: raise ValueError("Forbidden authority")
    return rows


def arrays(rows, labels):
    x = np.zeros((len(rows), 1024), np.float32); yy, mm = [], []
    counts = Counter(r["group_id"] for r in rows)
    gw = np.asarray([len(rows) / (len(counts) * counts[r["group_id"]]) for r in rows], np.float32)
    for i, r in enumerate(rows):
        for j, value in features(snapshot(r)).items(): x[i, j] = value
        y, m = targets(r, labels); yy.append(y); mm.append(m)
    return x, np.asarray(yy, np.float32), np.asarray(mm, np.float32), gw


def manifest():
    path = PACKET / "manifest.json"
    if not path.exists(): raise FileNotFoundError("Actual repayment packet manifest not ready")
    obj = json.loads(path.read_text(encoding="utf-8"))
    spec = json.loads((PACKET / "label-spec.json").read_text(encoding="utf-8"))
    labels = spec["heads"]
    if type(labels) is not list or not 1 <= len(labels) <= 16 or len(set(labels)) != len(labels) or any(type(x) is not str for x in labels):
        raise ValueError("Invalid actual taxonomy")
    files = {}
    for split, name in (("train", "train.jsonl"), ("calibration", "cal.jsonl"), ("eval", "heldout.jsonl")):
        record = obj["outputs"][name]
        p = (PACKET / name).resolve()
        if PACKET.resolve() not in p.parents or p.suffix != ".jsonl": raise ValueError("Packet path escape/unsupported format")
        if sha(p) != record["sha256"]: raise ValueError("Publisher/author manifest hash mismatch")
        files[split] = p
    return obj, labels, files


def split_integrity(files, labels):
    # Target values are not accessed in CAL/EVAL during source preflight.
    rows = {s: load_rows(p, s, labels, with_targets=(s == "train")) for s, p in files.items()}
    groups = {s: set(r["group_id"] for r in rr) for s, rr in rows.items()}
    identities = {s: set(r["record_id"] for r in rr) for s, rr in rows.items()}
    texts = {s: set(hashlib.sha256(observed_text(snapshot(r)).encode()).hexdigest() for r in rr) for s, rr in rows.items()}
    overlaps = {}
    for a, b in (("train", "calibration"), ("train", "eval"), ("calibration", "eval")):
        overlaps[a + ":" + b] = {"groups": len(groups[a] & groups[b]), "record_ids": len(identities[a] & identities[b]), "exact_observed_inputs": len(texts[a] & texts[b])}
        if any(overlaps[a + ":" + b].values()): raise ValueError("Actual group/record/input split leakage")
    return rows["train"], {"counts": {s: {"rows": len(rows[s]), "groups": len(groups[s])} for s in rows},
                           "overlap": overlaps, "CAL_EVAL_target_values_accessed": False}
