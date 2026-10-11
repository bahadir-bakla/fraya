"""Public-intent auxiliary encoder/classifier. Always unqualified; pure CPU.

Publisher intent names are a taxonomy, never bank permissions or policy facts.
No source annotation, record ID, dataset split or group ID becomes a feature.
"""
import hashlib
import math
import re

VERSION = "day2.public_source_intent.calibrated.v2"
WIDTH = 512
HIDDEN = 24
MAX_NODES = 4


def keys(text):
    normalized = re.sub(r"\d+(?:st|nd|rd|th)?", "number", text.casefold())
    words = re.findall(r"[^\W\d_]+", normalized)
    return (["w:" + w for w in words] + ["b:" + a + " " + b for a, b in zip(words, words[1:])]
            + ["c:" + normalized[i:i + 3] for i in range(len(normalized) - 2)])


def sparse(keys_):
    result = {}
    for key in keys_:
        d = hashlib.sha256(key.encode("utf8")).digest()
        i = int.from_bytes(d[:4], "little") % WIDTH
        result[i] = result.get(i, 0.0) + (1 if d[4] & 1 else -1)
    norm = math.sqrt(sum(v * v for v in result.values())) or 1.0
    return {i: v / norm for i, v in result.items() if v}


def source_graph(text, use_edges=True):
    if type(text) is not str or not text.strip() or len(text) > 2048:
        return None
    tokens = list(re.finditer(r"\S+", text))
    # Entire source retained: up to 3 contiguous balanced token intervals.
    # Long utterances increase chunk size instead of silently losing tokens.
    chunks = min(3, max(1, (len(tokens) + 5) // 6))
    spans = []
    for j in range(chunks):
        a = tokens[j * len(tokens) // chunks].start()
        b = tokens[(j + 1) * len(tokens) // chunks - 1].end()
        spans.append([a, b])
    nodes = [sparse(["type:turn"] + keys(text))]
    nodes += [sparse(["type:ordered_span"] + keys(text[a:b])) for a, b in spans]
    edges = [[0, j, "turn_membership"] for j in range(1, len(nodes))] if use_edges else []
    if use_edges:
        edges += [[j - 1, j, "source_order"] for j in range(2, len(nodes))]
    return {"nodes": nodes, "edges": edges, "spans": spans, "linear": sparse(keys(text)),
            "user_nodes": list(range(1, len(nodes))), "complete_source_token_coverage": True}


def distribution(logits):
    top = max(logits)
    exps = [math.exp(max(-700, z - top)) for z in logits]
    total = sum(exps)
    return [v / total for v in exps]


def score(text, model):
    if model.get("version") != VERSION or model.get("qualified") is not False:
        raise ValueError("Unqualified auxiliary bundle required")
    graph = source_graph(text, model["use_edges"])
    if graph is None:
        return None
    p = model["parameters"]; classes = len(model["publisher_labels"])
    if model["architecture"] == "sparse_softmax":
        logits = [p["bias"][j] + sum(p["weights_q"][i][j] * p["weight_scale"][j] * v for i, v in graph["linear"].items()) for j in range(classes)]
    else:
        if model["architecture"] != "tiny_relational_gnn": raise ValueError("Unknown architecture")
        h0 = [[math.tanh(p["embedding_bias"][j] + sum(p["embedding"][i][j] * v for i, v in node.items())) for j in range(HIDDEN)] for node in graph["nodes"]]
        incoming = {i: [] for i in range(len(h0))}
        for a, b, relation in graph["edges"]: incoming[b].append((a, relation))
        h1 = []
        for i, h in enumerate(h0):
            h1.append([math.tanh(p["message_bias"][j] + sum(h[k] * p["self"][k][j] for k in range(HIDDEN))
                                + sum(sum(h0[a][k] * p[relation][k][j] for k in range(HIDDEN)) for a, relation in incoming[i])) for j in range(HIDDEN)])
        pooled = [sum(h1[i][j] for i in graph["user_nodes"]) / len(graph["user_nodes"]) for j in range(HIDDEN)]
        logits = [p["bias"][j] + sum(pooled[k] * p["readout"][k][j] for k in range(HIDDEN)) for j in range(classes)]
    temperature = model.get("calibration", {}).get("temperature", 1.0)
    return distribution([v / temperature for v in logits])


def predict(text, model):
    probs = score(text, model)
    order = sorted(range(len(probs)), key=lambda i: (-probs[i], i))[:3] if probs is not None else []
    calibrated = model.get("calibration", {}).get("fitted") is True
    threshold = model.get("calibration", {}).get("threshold", 1.1)
    source_accepted = bool(order) and calibrated and probs[order[0]] >= threshold
    return {"version": VERSION, "status": "bank_abstain", "qualified": False, "authority": "none",
            "auxiliary_taxonomy": "BANKING77.publisher_intent",
            "candidate_publisher_intents": [{"label": model["publisher_labels"][i], "source_intent_score": probs[i]} for i in order],
            "source_intent_diagnostic_decision": "accept_proposal" if source_accepted else "abstain",
            "bank_policy_adaptation": "untrained_unreviewed", "acceptance": False,
            "reasons": ["public_taxonomy_only", "no_bank_mapping", "bank_deployment_closed"]}
