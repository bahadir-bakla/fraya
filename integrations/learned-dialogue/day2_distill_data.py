"""Pinned TRAIN-only cache alignment. No CAL/EVAL loader exists here."""
import hashlib
import json
import struct
from pathlib import Path
import numpy as np
from safetensors.numpy import load_file

ROOT = Path(__file__).resolve().parents[2]
PINS = {
    "research/customer-benchmark/day2-training-data/train.jsonl": "cbe4f19f99e10065fb9c19c33c82b5e17fa76685c497a1f99d1c072e96692406",
    "research/customer-benchmark/day2-training-data/taxonomy.json": "338a9dae6fea33fa3f4a921d751633aa344f0f7f6a4386f3f6e38caedcc4c128",
    "research/customer-benchmark/day2-training-data/v2/train.jsonl": "03707b592734838d9ad80fadaab3d87f42a5ed72c170580b86fa9cb58876e60f",
    "local-runs/customer-benchmark-day2-pretrained/train-embeddings.safetensors": "ec755cf2f46e72d12966e7c75a2097d1eaac2063c2efdad75bbac7761a3f5d22",
    "integrations/learned-dialogue/day2_pretrained_head.json": "fb3d2758994ea47c2d7e88bafc2deab552a506dd09a39780fda85f2c6036cd5e",
    "integrations/learned-dialogue/day2_pretrained_runtime.py": "355e946677aa0a08b35d3714802b4ba645a0405f7d2f1910d6b5b6f26f37e2db",
    "integrations/learned-dialogue/day2_pretrained_train.py": "7755b4275e003384d4a2e908b7581f497bfdd2865eabd5f3c4dc160c4ac5afe4",
    "analysis/day2-pretrained-baseline.json": "8db22980ab96b4904c84246512c53b684e357f341da124770585ee2dedcd0870",
}
TRAIN = next(iter(PINS))
CACHE = "local-runs/customer-benchmark-day2-pretrained/train-embeddings.safetensors"
HEAD = "integrations/learned-dialogue/day2_pretrained_head.json"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def write_new(path, obj):
    with Path(path).open("xb") as f:
        f.write(encoded(obj))


def check_pins(pins):
    for path, expected in pins.items():
        if sha(ROOT / path) != expected:
            raise ValueError("Frozen hash mismatch: " + path)


def identity(rows):
    return hashlib.sha256(encoded([[r["record_id"], r["group_id"], r["text"], r["source_label_id"]] for r in rows])).hexdigest()


def validate_rows(rows, labels):
    if len(rows) != 7943 or len({r["record_id"] for r in rows}) != 7943:
        raise ValueError("Wrong row count or duplicate IDs")
    for r in rows:
        if r["split"] != "train" or r["publisher_split"] != "train" or r["source_id"] != "banking77-publisher-train":
            raise ValueError("Non-TRAIN input")
        if type(r["text"]) is not str or not r["text"].strip() or len(r["text"]) > 4096:
            raise ValueError("Unknown source feature input")
        y = r["source_label_id"]
        if type(y) is not int or not 0 <= y < 77 or labels[y] != r["source_label"]:
            raise ValueError("Invalid publisher supervision")
        if r["bank_policy_target"] is not None or r["ledger_target"] is not None:
            raise ValueError("Forbidden authority target")


def check_cache_header(header):
    m = header.get("__metadata__", {})
    if m != {"split": "train", "input_sha256": PINS[TRAIN], "encoder_revision": REVISION}:
        raise ValueError("Cache source/split mismatch")
    if header.get("embeddings", {}).get("shape") != [7943, 384] or header["embeddings"]["dtype"] != "F32":
        raise ValueError("Invalid embedding shape/dtype")


def raw_teacher(embeddings, head):
    # Explicit allowlist: temperature/threshold/calibration are never accessed.
    q = np.asarray(head["weights_qint16"])
    scales = np.asarray(head["weight_scales"], dtype=np.float64)
    bias = np.asarray(head["intercept"], dtype=np.float64)
    if q.shape != (77, 384) or scales.shape != (77,) or bias.shape != (77,):
        raise ValueError("Invalid teacher shape")
    if not np.isfinite(q).all() or not np.isfinite(scales).all() or not np.isfinite(bias).all() or (scales <= 0).any():
        raise ValueError("Invalid teacher weights")
    if (q != np.rint(q)).any() or np.abs(q).max() > 32767:
        raise ValueError("Invalid quantized weights")
    if embeddings.shape != (7943, 384) or not np.isfinite(embeddings).all():
        raise ValueError("Invalid TRAIN embeddings")
    z = (embeddings.astype(np.float64) @ (q * scales[:, None]).T + bias).astype(np.float32)
    if not np.isfinite(z).all():
        raise ValueError("Nonfinite raw teacher logits")
    return z


def load_train():
    check_pins(PINS)
    rows = [json.loads(l) for l in (ROOT / TRAIN).read_text(encoding="utf-8").splitlines()]
    taxonomy = json.loads((ROOT / "research/customer-benchmark/day2-training-data/taxonomy.json").read_text(encoding="utf-8"))
    labels = [r["source_label"] for r in taxonomy["labels"]]
    validate_rows(rows, labels)
    newer = [json.loads(l) for l in (ROOT / "research/customer-benchmark/day2-training-data/v2/train.jsonl").read_text(encoding="utf-8").splitlines()]
    bank = {r["record_id"]: r for r in newer if r["source_id"] == "banking77-publisher-train"}
    if len(bank) != 7943:
        raise ValueError("v2 subset mismatch")
    for r in rows:
        n = bank[r["record_id"]]
        if any(n[k] != r[k] for k in ("text", "group_id", "source_label", "source_label_id", "source_text_sha256")) or n["head_mask"]["banking77_intent"] is not True:
            raise ValueError("TRAIN identity/text/label/mask mismatch")
    with (ROOT / CACHE).open("rb") as f:
        length = struct.unpack("<Q", f.read(8))[0]
        if length > 100000:
            raise ValueError("Oversized cache header")
        check_cache_header(json.loads(f.read(length)))
    embeddings = load_file(str(ROOT / CACHE))["embeddings"]
    head = json.loads((ROOT / HEAD).read_text(encoding="utf-8"))
    if head["labels"] != labels:
        raise ValueError("Teacher taxonomy order mismatch")
    logits = raw_teacher(embeddings, head)
    return rows, labels, logits
