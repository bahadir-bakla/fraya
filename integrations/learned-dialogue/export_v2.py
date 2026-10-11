"""Lossless <=500KB context-model research export. No runtime remote calls."""
import base64
import hashlib
import json
import struct
from pathlib import Path

from context_v2 import BindingContext, binding_v2, predict_v2
from export_runtime import RUNTIME_LOADER
from train_v2 import HERE, strict_json


def export_v2(bundle, path=None):
    model = bundle["model"]
    keys = sorted(set(model["vocabulary"]))
    meta = {key: value for key, value in model.items() if key not in {"heads", "secondary"}}
    meta["heads"], meta["secondary"] = {}, {}
    values = []
    for name, head in model["heads"].items():
        meta["heads"][name] = {key: value for key, value in head.items() if key != "weights"}
        meta["heads"][name]["offset"] = len(values)
        values.extend(weight.get(key, 0.0) for weight in head["weights"] for key in keys)
    for name, head in model["secondary"].items():
        meta["secondary"][name] = {"bias": head["bias"], "offset": len(values)}
        values.extend(head["weights"].get(key, 0.0) for key in keys)
    if len(values) > 100000:
        raise ValueError("Export exceeds 100000-coefficient cap")
    raw = b"".join(struct.pack(">d", v) for v in values)
    b64 = base64.b64encode(raw).decode()
    text = json.dumps(meta, separators=(",", ":"), allow_nan=False).replace("{", "~L~").replace("}", "~R~")
    # Generated function closure works when platform-like exec uses separate globals/locals.
    implementation = (HERE / "context_v2.py").read_text(encoding="utf-8")
    implementation = implementation[implementation.index("FORMAT_V2 ="):]
    body = f'''import json
import re
{RUNTIME_LOADER}
MODEL = json.loads({text!r}.replace("~L~", chr(123)).replace("~R~", chr(125)))
KEYS = MODEL["vocabulary"]
blob = decode64({b64!r})
for name, head in MODEL["heads"].items():
    offset = head.pop("offset")
    head["weights"] = []
    for index in range(len(head["labels"])):
        weight = dict()
        for column, key in enumerate(KEYS):
            position = (offset + index * len(KEYS) + column) * 8
            weight[key] = binary64(blob[position:position+8])
        head["weights"].append(weight)
for name, head in MODEL["secondary"].items():
    offset = head.pop("offset")
    head["weights"] = dict()
    for column, key in enumerate(KEYS):
        position = (offset + column) * 8
        head["weights"][key] = binary64(blob[position:position+8])
{implementation}
BUNDLE = dict(model_id={bundle["model_id"]!r}, model=MODEL)
def bound_predict(snapshot, authoritative_binding):
    context = BindingContext(authoritative_binding, BUNDLE["model_id"])
    return predict_v2(snapshot, BUNDLE, context)
return bound_predict
'''
    source = '"""Unqualified local context diagnostic; not a workflow or permission authority."""\n'
    source += "def load_context_predictor():\n" + "\n".join("    " + line if line else "" for line in body.splitlines())
    source += "\n\npredict_context_embedded = load_context_predictor()\n"
    if "{{" in source or "}}" in source:
        raise ValueError("Template marker in generated source")
    if len(source.encode()) > 500000:
        raise ValueError("Export exceeds 500000 UTF-8 bytes")
    if path is not None:
        if path.exists() and path.read_text(encoding="utf8") != source:
            raise ValueError("Frozen v2 export differs")
        if not path.exists():
            path.write_bytes(source.encode("utf8"))
    return source, {"utf8_bytes": len(source.encode()), "coefficient_count": len(values),
                    "source_sha256": hashlib.sha256(source.encode()).hexdigest(), "model_id": bundle["model_id"],
                    "storage": "Shared indices/lossless binary64", "runtime_imports": ["json", "re"], "qualified": False}


if __name__ == "__main__":
    path = HERE / "model_v2.json"
    blob = path.read_bytes()
    bundle = {"model_id": hashlib.sha256(blob).hexdigest(), "model": strict_json(blob)}
    _, report = export_v2(bundle, HERE / "runtime_context_v2.py")
    print(json.dumps(report, indent=2))
