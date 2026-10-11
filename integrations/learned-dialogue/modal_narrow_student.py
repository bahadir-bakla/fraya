"""Optional TRAIN-only sparse student. Teacher scores are soft targets, not gold.

Standalone JSON+builtins/re inference; all predictions remain unqualified. This
implementation avoids frozen v2 reference/component heuristics completely.
"""
import math
import re
import inspect
from modal_narrow_core import canonical, digest, validate_payload


def features(text):
    words = re.findall(r"[a-z]+|[0-9]+", text.lower())
    words = ["<number>" if w.isdigit() else w for w in words]
    result = {}
    for width in (1, 2):
        for index in range(len(words)-width+1):
            result["w"+str(width)+":"+" ".join(words[index:index+width])] = 1.0
    folded = " ".join(words)
    for width in (3, 4):
        for index in range(len(folded)-width+1):
            result["c"+str(width)+":"+folded[index:index+width]] = 1.0
    return result


def sigmoid(z):
    # Builtins-only exp with range reduction and Taylor terms. Binary64 parity
    # checked against math.exp offline; no extra Freya runtime import.
    z = max(-32., min(32., z))
    value = abs(z)
    power = int(value/.6931471805599453)
    residual = value-power*.6931471805599453
    term, total = 1., 1.
    for index in range(1,27):
        term *= residual/index
        total += term
    e = total*(2.**power)
    return e/(1+e) if z >= 0 else 1/(1+e)


def propose(text, model):
    if type(text) is not str or not text or len(text) > 8192:
        return {"task":"primary_is_payment_proposal", "raw_score":None, "decision":"abstain", "qualified":False,
                "calibrated":False, "reason":"input_unavailable_or_overflow"}
    f = features(text)
    score = sigmoid(model["bias"]+sum(v*f.get(k, 0) for k,v in model["weights"].items()))
    return {"task":"primary_is_payment_proposal", "raw_score":score,
            "decision":"abstain", "qualified":False, "calibrated":False,
            "negative_semantics":"not this primary; no permission consequence"}


def fit_student(payload_blob, result, alpha=0., epochs=80, max_features=384):
    payload = validate_payload(payload_blob)
    if result.get("payload_sha256") != digest(payload_blob) or result.get("format") != "narrow_frozen_teacher_result.v3":
        raise ValueError("Exact TRAIN teacher/payload binding required")
    if alpha not in (0., .25) or epochs != 80 or max_features != 384:
        raise ValueError("Predeclared bounded student configuration only")
    rows = payload["rows"]
    targets = result["train_only_soft_targets"]
    by_id = {r["id"]:r for r in targets}
    if len(by_id) != len(targets) or set(by_id) != {r["id"] for r in rows}:
        raise ValueError("Only exact TRAIN soft targets allowed")
    groups, counts = {}, {}
    for row in rows:
        target = by_id[row["id"]]
        if target["group"] != row["group"] or type(target.get("logit")) not in (float, int) or not math.isfinite(target["logit"]) or abs(target["logit"]) > 64:
            raise ValueError("Finite bound group-matching soft target required")
        groups.setdefault(row["group"], []).append(dict(row, f=features(row["text"])))
    for members in groups.values():
        for key in {k for row in members for k in row["f"]}:
            counts[key] = counts.get(key, 0)+1
    vocabulary = sorted(sorted(counts, key=lambda k:(-counts[k], k))[:384])
    model = {"format":"sparse_primary_payment_student.v3", "weights":dict.fromkeys(vocabulary, 0.), "bias":0.,
             "qualified":False, "calibrated":False, "teacher_payload_sha256":digest(payload_blob), "alpha":alpha,
             "objective":"group mean (1-alpha)*gold binary CE + alpha*T^2*binary KL; T=2; alpha=.25 or gold-only=0; teacher is not gold"}
    for epoch in range(epochs):
        gradient, bias_gradient = dict.fromkeys(vocabulary, 0.), 0.
        for members in groups.values():
            for row in members:
                z = model["bias"]+sum(model["weights"][k]*row["f"].get(k, 0) for k in vocabulary)
                teacher_t = sigmoid(by_id[row["id"]]["logit"]/2)
                error = ((1-alpha)*(sigmoid(z)-row["y"]) + alpha*2*(sigmoid(z/2)-teacher_t))/(len(groups)*len(members))
                bias_gradient += error
                for key in vocabulary:
                    gradient[key] += error*row["f"].get(key, 0)
        rate = .7/math.sqrt(1+epoch/10)
        model["bias"] -= rate*bias_gradient
        for key in vocabulary:
            model["weights"][key] -= rate*(gradient[key]+.0002*model["weights"][key])
    if len(canonical(model)) > 500000 or len(model["weights"]) > 100000:
        raise ValueError("Compact student export gate failed")
    return model


def export_student(model):
    """Compact pure diagnostic module, imports only supported json/re."""
    import json
    source = "import json\nimport re\n" + "\n".join(inspect.getsource(f) for f in (features,sigmoid,propose))
    source += "\nMODEL = json.loads("+repr(canonical(model).decode())+")\n"
    source += "\ndef predict(text):\n    return propose(text,MODEL)\n"
    blob = source.encode("utf-8")
    if len(blob) > 500000 or len(model["weights"]) > 100000:
        raise ValueError("Compact runtime footprint exceeded")
    return blob
