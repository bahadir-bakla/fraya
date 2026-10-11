"""Lossless indexed binary64 export; builder-only struct/base64 imports.

The generated research adapter imports json/re only, reconstructs binary64 with
builtins, and relies on an upstream trusted wrapper for the input-text hash.
This is a local artifact, not a Freya workflow or qualified deployment.
"""
import base64
import hashlib
import json
import struct
import time

from inference import HEADS, local_snapshot, predict
from train_eval import HERE, ROOT, load_data, load_model, write_json

RUNTIME_LOADER = '''
def decode64(text):
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    lookup = dict((ch, i) for i, ch in enumerate(alphabet))
    acc, bits, out = 0, 0, bytearray()
    for ch in text:
        if ch == "=":
            break
        acc = (acc << 6) | lookup[ch]
        bits += 6
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 255)
            acc &= (1 << bits) - 1
    return out

def binary64(blob):
    value = int.from_bytes(blob, "big")
    sign = -1.0 if value >> 63 else 1.0
    exponent = (value >> 52) & 2047
    mantissa = value & ((1 << 52) - 1)
    if exponent == 2047:
        raise ValueError("Nonfinite model weight")
    if exponent == 0:
        return sign * mantissa * (2.0 ** -1074)
    return sign * (1.0 + mantissa / (2.0 ** 52)) * (2.0 ** (exponent - 1023))

class Counter(dict):
    def __init__(self, items=()):
        super().__init__()
        self.update(items)
    def update(self, items):
        for item in items:
            self[item] = self.get(item, 0) + 1
'''


def main():
    model = load_model()
    keys = sorted({k for head in model["heads"].values() for weight in head["weights"] for k in weight})
    values, meta = [], {"format": model["format"], "word_vocabulary": model["word_vocabulary"],
                        "calibration": {"fitted": model["calibration"]["fitted"], "threshold": model["calibration"]["threshold"]},
                        "feature_keys": keys, "heads": {}}
    for name in HEADS:
        head = model["heads"][name]
        meta["heads"][name] = {"labels": head["labels"], "bias": head["bias"], "temperature": head["temperature"], "offset": len(values)}
        values.extend(weight.get(key, 0.0) for weight in head["weights"] for key in keys)
    binary = b"".join(struct.pack(">d", value) for value in values)
    encoded_weights = base64.b64encode(binary).decode()
    meta_text = json.dumps(meta, separators=(",", ":")).replace("{", "~L~").replace("}", "~R~")
    implementation = (HERE / "inference.py").read_text(encoding="utf-8")
    implementation = implementation[implementation.index("HEADS ="):implementation.index("def local_snapshot")]
    implementation = implementation.replace("math.sqrt(sum(v * v for v in counts.values()))", "sum(v * v for v in counts.values()) ** 0.5")
    implementation = implementation.replace("math.exp(x - peak)", "2.718281828459045 ** (x - peak)")
    implementation = implementation.replace('hashlib.sha256(text.encode()).hexdigest()', 'input_snapshot["input_sha256"]')
    setup = f'''import json
import re
{RUNTIME_LOADER}
MODEL = json.loads({meta_text!r}.replace("~L~", chr(123)).replace("~R~", chr(125)))
blob = decode64({encoded_weights!r})
keys = MODEL.pop("feature_keys")
for name, head in MODEL["heads"].items():
    offset = head.pop("offset")
    head["weights"] = []
    for index in range(len(head["labels"])):
        weight = dict()
        for column, key in enumerate(keys):
            position = (offset + index * len(keys) + column) * 8
            weight[key] = binary64(blob[position:position + 8])
        head["weights"].append(weight)
{implementation}
def bound_predict(snapshot):
    if not re.fullmatch(r"[0-9a-f]{{64}}", snapshot.get("input_sha256", "")):
        raise ValueError("Trusted upstream input_sha256 required")
    return predict(snapshot, MODEL)
return bound_predict
'''
    source = '"""Offline research export; no deployment qualification or permission authority."""\n'
    source += "def load_embedded_predictor():\n" + "\n".join("    " + line if line else "" for line in setup.splitlines())
    source += "\n\npredict_embedded = load_embedded_predictor()\n"
    if "{{" in source or "}}" in source:
        raise ValueError("Template marker in exported source")
    path = HERE / "runtime_embedded.py"
    path.write_text(source, encoding="utf-8")
    start = time.perf_counter()
    namespace, separate_globals = {}, {"__builtins__": __builtins__}
    exec(compile(source, str(path), "exec"), separate_globals, namespace)
    cold_ms = (time.perf_counter() - start) * 1000
    function = namespace["predict_embedded"]
    records, oracle, manifest, _ = load_data()
    maximum_difference = 0.0
    decisions_match = True
    binary_roundtrip = all(struct.unpack(">d", binary[i:i + 8])[0] == values[i // 8] for i in range(0, len(binary), 8))
    for record in records:
        snapshot = local_snapshot(record["utterance"], record["id"])
        snapshot["input_sha256"] = hashlib.sha256(snapshot["utterance"].encode()).hexdigest()
        offline, embedded = predict(snapshot, model), function(snapshot)
        decisions_match &= all(offline[k] == embedded[k] for k in ("candidate", "abstain", "reasons", "clauses", "corrections", "turn_id", "state_revision", "policy_hash", "input_sha256"))
        for head in HEADS:
            for label, value in offline["confidence"]["heads"][head]["distribution"].items():
                maximum_difference = max(maximum_difference, abs(value - embedded["confidence"]["heads"][head]["distribution"][label]))
    report = {"export_path": str(path), "export_utf8_bytes": len(source.encode()), "coefficient_count": len(values),
              "shared_features": len(keys), "coefficient_storage": "lossless binary64 in shared feature order; base64 decoded with builtins",
              "imports_in_generated_source": ["json", "re"], "separate_globals_locals_harness_passed": True,
              "binary64_storage_roundtrip_exact": binary_roundtrip, "all_96_proposal_decisions_match": decisions_match,
              "max_confidence_absolute_difference": maximum_difference,
              "cold_compile_and_decode_ms": cold_ms, "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "input_hash_contract": "Upstream trusted wrapper supplies input_sha256; runtime cannot independently verify raw text/hash binding",
              "qualified_for_freya": False, "scope": "Local parity only; builtin exp-by-power differs at floating point roundoff; no sandbox, raw-turn binding, competition eligibility or full latency qualification"}
    write_json(ROOT / "analysis/night-learned-dialogue.export.json", report)
    print(json.dumps(report, indent=2))
    if not decisions_match or maximum_difference > 1e-12 or not binary_roundtrip:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
