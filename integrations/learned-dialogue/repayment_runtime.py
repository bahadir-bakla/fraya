"""Compact offline semantic proposal. No policy values, bank calls or authority."""
import base64
import hashlib
import json
import math
import re
import struct

FEATURE_VERSION = "repayment-observed-context-hash1024-v1"


def observed_text(snapshot):
    if type(snapshot) is not dict or set(snapshot) != {"current_utterance", "previous_utterances"}:
        raise ValueError("Unsupported observed-input schema")
    prior = snapshot["previous_utterances"]; current = snapshot["current_utterance"]
    if type(prior) is not list or len(prior) > 2: raise ValueError("Invalid observed history; last two source turns required")
    lines = []
    for turn in prior + [current]:
        if type(turn) is not dict or set(turn) != {"speaker", "text"} or turn["speaker"] not in ("SYSTEM", "ASSISTANT", "USER"):
            raise ValueError("Invalid speaker/source structure")
        text = turn["text"]
        if type(text) is not str or not text.strip() or len(text) > 2048: raise ValueError("Invalid observed text")
        lines.append(turn["speaker"] + ": " + text)
    if current["speaker"] != "USER" or sum(len(s) for s in lines) > 4096: raise ValueError("Unsupported current user/history")
    return "\n".join(lines) + "\n"


def features(snapshot, without_context=False):
    text = observed_text(snapshot)
    if without_context:
        text = observed_text({"current_utterance": snapshot["current_utterance"], "previous_utterances": []})
    text = re.sub(r"\d+(?:st|nd|rd|th)?", "number", text.casefold())
    words = re.findall(r"[^\W\d_]+", text)
    keys = ["w:" + w for w in words] + ["b:" + a + " " + b for a, b in zip(words, words[1:])]
    keys += ["c:" + text[i:i + 3] for i in range(max(0, len(text) - 2))]
    out = {}
    for key in keys:
        digest = hashlib.sha256(key.encode("utf-8")).digest()
        j = int.from_bytes(digest[:4], "little") % 1024
        out[j] = out.get(j, 0.) + (1. if digest[4] & 1 else -1.)
    norm = math.sqrt(sum(v * v for v in out.values()))
    if not norm: raise ValueError("No nonzero features")
    return {k: v / norm for k, v in out.items() if v}


def sigmoid(value):
    if not math.isfinite(value): raise ValueError("Nonfinite logit")
    return 1 / (1 + math.exp(-max(-80., min(80., value))))


def decode(blob, expected_sha256):
    if hashlib.sha256(blob).hexdigest() != expected_sha256: raise ValueError("Bundle hash mismatch")
    obj = json.loads(blob)
    if set(obj) != {"schema", "features", "labels", "parameters", "qualified", "bank_authority", "arm"}:
        raise ValueError("Unexpected fields")
    if obj["schema"] != "repayment_student.v1" or obj["features"] != FEATURE_VERSION or obj["bank_authority"] is not False or obj["qualified"] is not False:
        raise ValueError("Unsupported contract/authority")
    labels = obj["labels"]
    if type(labels) is not list or not 1 <= len(labels) <= 16 or any(type(x) is not str for x in labels) or len(set(labels)) != len(labels):
        raise ValueError("Invalid taxonomy")
    k = len(labels); shapes = {"E": (1024, 32), "b": (32,), "W": (32, k), "c": (k,)}
    if set(obj["parameters"]) != set(shapes): raise ValueError("Invalid parameter keys")
    p = {}
    for name, shape in shapes.items():
        raw = base64.b64decode(obj["parameters"][name], validate=True); n = math.prod(shape)
        if len(raw) != n * 4: raise ValueError("Invalid shape")
        values = struct.unpack("<" + str(n) + "f", raw)
        if not all(math.isfinite(v) for v in values): raise ValueError("Nonfinite weights")
        p[name] = values
    return {"parameters": p, "labels": labels}


def logits(snapshot, model, without_context=False):
    x = features(snapshot, without_context); p = model["parameters"]; k = len(model["labels"])
    hidden = [math.tanh(p["b"][j] + sum(v * p["E"][i * 32 + j] for i, v in x.items())) for j in range(32)]
    return [p["c"][a] + sum(hidden[j] * p["W"][j * k + a] for j in range(32)) for a in range(k)]


def predict(snapshot, model, calibrator=None):
    try: z = logits(snapshot, model)
    except (ValueError, TypeError, KeyError):
        return {"proposals": {}, "abstain": True, "bank_authority": False, "reason": "unknown_input"}
    proposals = {}
    for i, label in enumerate(model["labels"]):
        if calibrator is None:
            proposals[label] = {"score": sigmoid(z[i]), "suggested": None, "qualified": False}
        else:
            t, threshold = calibrator["temperature"][i], calibrator["threshold"][i]
            if type(t) not in (int, float) or not math.isfinite(t) or t <= 0 or type(threshold) not in (int, float) or not math.isfinite(threshold):
                raise ValueError("Invalid calibration")
            score = sigmoid(z[i] / t)
            proposals[label] = {"score": score, "suggested": score >= threshold, "qualified": False}
    return {"proposals": proposals, "abstain": True, "bank_authority": False,
            "label_mask": {name: (bool(calibrator["trained_heads"][i]) if calibrator is not None else None) for i,name in enumerate(model["labels"])},
            "calibration_available": {name: (calibrator is not None and calibrator["per_class_CAL"][i]["selective_available"]) for i,name in enumerate(model["labels"])},
            "reason": "experimental_semantic_only_not_permission"}
