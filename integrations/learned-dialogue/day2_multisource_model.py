"""Pure local auxiliary proposal inference; no I/O, tools or permissions.

Caller loads a hash-pinned finite artifact once. Public semantic scores never
authenticate the input, become normalized bank values or grant authority.
"""
import base64
import hashlib
import json
import math
import struct
from day2_multisource_features import WIDTH, MAX_NODES, RELATIONS, source_graph

VERSION = "day2.multisource.proposal.v1"
HIDDEN = 24
HEAD_SLICES = {"banking77_intent": (0, 77), "nlupp_intents": (77, 139), "nlupp_slot_presence": (139, 156)}


def parameter_shapes(architecture, training=False):
    dim = WIDTH if architecture == "sparse" else HIDDEN
    shapes = {"readout": [dim, 156], "bias": [156]}
    if architecture != "sparse":
        if architecture != "gnn":
            raise ValueError("Unknown architecture")
        shapes.update(embedding=[WIDTH, HIDDEN], embedding_bias=[HIDDEN], self=[HIDDEN, HIDDEN], message_bias=[HIDDEN])
        shapes.update({r: [HIDDEN, HIDDEN] for r in RELATIONS})
    if training:
        shapes.update(next_readout=[dim, WIDTH], next_bias=[WIDTH])
    return shapes


def decode_parameters(encoded, shapes):
    if type(encoded) is not dict or set(encoded) != set(shapes):
        raise ValueError("Parameter names mismatch")
    result = {}
    for name, shape in shapes.items():
        item = encoded[name]
        if type(item) is not dict or item.get("shape") != shape or item.get("dtype") != "float32-le":
            raise ValueError("Parameter shape/type mismatch")
        if type(item.get("base64")) is not str:
            raise ValueError("Missing encoded array")
        size = math.prod(shape)
        if len(item["base64"]) > 4 * ((size * 4 + 2) // 3):
            raise ValueError("Encoded array exceeds bound")
        raw = base64.b64decode(item["base64"], validate=True)
        if len(raw) != size * 4:
            raise ValueError("Encoded array length mismatch")
        values = list(struct.unpack("<" + str(size) + "f", raw))
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Nonfinite weights")
        result[name] = [values[i:i + shape[1]] for i in range(0, len(values), shape[1])] if len(shape) == 2 else values
    return result


def compile_bundle(raw, expected_sha256, expected_taxonomy):
    """expected hash/taxonomy supplied by caller's frozen manifest, not bundle."""
    if type(raw) is not bytes or len(raw) > 500000:
        raise ValueError("Bounded artifact bytes required")
    if type(expected_sha256) is not str or len(expected_sha256) != 64 or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Out-of-band artifact pin mismatch")
    m = json.loads(raw)
    if (type(m) is not dict or m.get("version") != VERSION or m.get("qualified") is not False
            or m.get("bank_acceptance") is not False or m.get("authority") != "none"):
        raise ValueError("Unqualified auxiliary contract required")
    if type(m.get("use_edges")) is not bool or m.get("taxonomy") != expected_taxonomy:
        raise ValueError("Topology or taxonomy mismatch")
    if set(expected_taxonomy) != set(HEAD_SLICES):
        raise ValueError("Taxonomy namespaces mismatch")
    for head, (a, b) in HEAD_SLICES.items():
        labels = expected_taxonomy[head]
        if type(labels) is not list or len(labels) != b - a or any(type(v) is not str for v in labels) or len(set(labels)) != b - a:
            raise ValueError("Taxonomy dimension mismatch")
    c = m.get("calibration")
    if type(c) is not dict or set(c) != set(HEAD_SLICES):
        raise ValueError("Calibration heads mismatch")
    for head, value in c.items():
        if type(value) is not dict or type(value.get("fitted")) is not bool:
            raise ValueError("Calibration schema")
        for key, low, high in (("temperature", 0, 100), ("threshold", 0, 1.1)):
            v = value.get(key)
            if type(v) not in (float, int) or not math.isfinite(v) or not low <= v <= high or (key == "temperature" and v <= 0):
                raise ValueError("Finite positive calibration required")
    m["parameters"] = decode_parameters(m["parameters"], parameter_shapes(m["architecture"]))
    m["compiled_sha256"] = expected_sha256
    return m


def pooled(graph, p, architecture):
    if architecture == "sparse":
        return [graph["linear"].get(i, 0.0) for i in range(WIDTH)]
    h0 = [[math.tanh(p["embedding_bias"][j] + sum(p["embedding"][i][j] * v for i, v in node.items()))
           for j in range(HIDDEN)] for node in graph["nodes"]]
    incoming = {i: {r: [] for r in RELATIONS} for i in range(len(h0))}
    for a, b, relation in graph["edges"]:
        incoming[b][relation].append(a)
    h1 = []
    for i, row in enumerate(h0):
        h1.append([math.tanh(p["message_bias"][j] + sum(row[k] * p["self"][k][j] for k in range(HIDDEN))
                            + sum(sum(sum(h0[a][k] * p[r][k][j] for k in range(HIDDEN)) for a in sources) / len(sources)
                                  for r, sources in incoming[i].items() if sources)) for j in range(HIDDEN)])
    return [sum(h1[i][j] * w for i, w in zip(graph["readout_nodes"], graph["readout_weights"])) for j in range(HIDDEN)]


def logits(snapshot, model, **controls):
    if "compiled_sha256" not in model:
        raise ValueError("Compile pinned finite model first")
    graph = source_graph(snapshot, model["use_edges"], **controls)
    if graph is None:
        return None
    rep = pooled(graph, model["parameters"], model["architecture"])
    p = model["parameters"]
    return [p["bias"][j] + sum(rep[k] * p["readout"][k][j] for k in range(len(rep))) for j in range(156)]


def head_probabilities(values, calibration):
    out = {}
    for head, (a, b) in HEAD_SLICES.items():
        z = [v / calibration[head]["temperature"] for v in values[a:b]]
        if head == "banking77_intent":
            top = max(z); exp = [math.exp(max(-700, v - top)) for v in z]; total = sum(exp)
            out[head] = [v / total for v in exp]
        else:
            out[head] = [1 / (1 + math.exp(-max(-700, min(700, v)))) for v in z]
    return out


def predict(snapshot, compiled):
    neutral = {"version": VERSION, "mode": "offline_shadow", "qualified": False,
               "authority": "none", "bank_acceptance": False, "bank_mapping": None,
               "unknown_axes": ["policy", "ledger", "financial_consent", "completion", "polarity", "normalized_values", "targets", "readback_freshness"]}
    try:
        z = logits(snapshot, compiled)
    except (ValueError, TypeError, KeyError, OverflowError):
        return {**neutral, "status": "input_rejected", "source_proposals": {}}
    if z is None:
        return {**neutral, "status": "input_unavailable", "source_proposals": {}}
    probs = head_probabilities(z, compiled["calibration"])
    result = {}
    for head, values in probs.items():
        c = compiled["calibration"][head]; labels = compiled["taxonomy"][head]
        order = sorted(range(len(values)), key=lambda i: (-values[i], i))
        proposed = [order[0]] if head == "banking77_intent" else [i for i in order if c["fitted"] and values[i] >= c["threshold"]]
        if not c["fitted"] or head == "banking77_intent" and values[order[0]] < c["threshold"]:
            proposed = []
        result[head] = {"candidates": [{"label": labels[i], "marginal_score": values[i]} for i in order[:5]],
                        "proposed_labels": [labels[i] for i in proposed], "calibrated": c["fitted"],
                        "statistical_qualification": False}
    return {**neutral, "status": "auxiliary_only", "source_proposals": result}
