"""Pure stdlib source-intent proposal inference; never grants bank authority."""
import base64
import hashlib
import json
import math
import re
import struct

SHAPES = {"E": (1024, 32), "b": (32,), "W": (32, 77), "c": (77,)}
FEATURE_VERSION = "text-only-sha256-signed-1024-v1"


def features(text):
    if type(text) is not str or not text.strip() or len(text) > 4096:
        raise ValueError("Unknown/malformed text; no structured-value stringification")
    text = re.sub(r"\d+(?:st|nd|rd|th)?", "number", text.casefold())
    words = re.findall(r"[^\W\d_]+", text)
    keys = ["w:" + w for w in words]
    keys += ["b:" + a + " " + b for a, b in zip(words, words[1:])]
    keys += ["c:" + text[i:i + 3] for i in range(max(0, len(text) - 2))]
    x = {}
    for key in keys:
        d = hashlib.sha256(key.encode("utf-8")).digest()
        j = int.from_bytes(d[:4], "little") % 1024
        x[j] = x.get(j, 0.0) + (1.0 if d[4] & 1 else -1.0)
    norm = math.sqrt(sum(v * v for v in x.values()))
    if not norm:
        raise ValueError("Unknown input: no nonzero features")
    return {j: v / norm for j, v in x.items() if v}


def decode(blob, expected_sha256):
    if type(blob) is not bytes or hashlib.sha256(blob).hexdigest() != expected_sha256:
        raise ValueError("Artifact hash mismatch")
    obj = json.loads(blob)
    if set(obj) != {"schema", "feature_version", "labels", "parameters", "bank_authority", "qualified", "arm"}:
        raise ValueError("Unexpected bundle fields")
    if obj["schema"] != "day2_distill_student.v1" or obj["feature_version"] != FEATURE_VERSION:
        raise ValueError("Unsupported feature contract")
    if obj["bank_authority"] is not False or obj["qualified"] is not False:
        raise ValueError("Forbidden authority")
    labels = obj["labels"]
    if type(labels) is not list or len(labels) != 77 or len(set(labels)) != 77 or any(type(x) is not str for x in labels):
        raise ValueError("Invalid labels")
    if set(obj["parameters"]) != set(SHAPES):
        raise ValueError("Invalid parameter names")
    out = {}
    for name, shape in SHAPES.items():
        raw = base64.b64decode(obj["parameters"][name], validate=True)
        n = math.prod(shape)
        if len(raw) != 4 * n:
            raise ValueError("Invalid parameter dimensions")
        vals = struct.unpack("<" + str(n) + "f", raw)
        if not all(math.isfinite(x) for x in vals):
            raise ValueError("Nonfinite artifact")
        out[name] = vals
    return {"parameters": out, "labels": labels}


def logits(text, model):
    x = features(text)
    p = model["parameters"]
    h = [math.tanh(p["b"][j] + sum(v * p["E"][i * 32 + j] for i, v in x.items())) for j in range(32)]
    z = [p["c"][k] + sum(h[j] * p["W"][j * 77 + k] for j in range(32)) for k in range(77)]
    if not all(math.isfinite(v) for v in z):
        raise ValueError("Nonfinite inference")
    return z


def predict(text, model):
    try:
        z = logits(text, model)
    except (ValueError, TypeError, KeyError):
        return {"source_intent": None, "abstain": True, "bank_authority": False, "reason": "unknown_or_malformed"}
    k = max(range(77), key=lambda i: z[i])
    return {"source_intent": model["labels"][k], "raw_logits": z, "confidence": None,
            "abstain": True, "bank_authority": False, "reason": "uncalibrated_unqualified_auxiliary"}
