"""Pure, CPU, unqualified binary proposals; no tools, policy values or I/O.

The graph is source-defined: question->clause and prior-clause->next-clause.
Graph parameters are learned by day2_train, never by this runtime module.
"""
import hashlib
import math
import re

VERSION = "day2.source_graph_binary.v1"
BINS = 192
HIDDEN = 8
MAX_NODES = 9


def normalized(text):
    return re.sub(r"\d+(?:st|nd|rd|th)?", "number", text.casefold())


def lexical(text):
    text = normalized(text)
    words = re.findall(r"[^\W\d_]+", text)
    keys = ["w:" + w for w in words]
    keys += ["b:" + a + " " + b for a, b in zip(words, words[1:])]
    keys += ["c:" + text[i:i + 3] for i in range(len(text) - 2)]
    return keys


def vector(keys):
    result = {}
    for key in keys:
        digest = hashlib.sha256(key.encode("utf8")).digest()
        index = int.from_bytes(digest[:4], "little") % BINS
        sign = 1 if digest[4] & 1 else -1
        result[index] = result.get(index, 0.0) + sign
    norm = math.sqrt(sum(v * v for v in result.values())) or 1.0
    return {i: v / norm for i, v in result.items() if v}


def source_input(snapshot, include_context=True, include_edges=True):
    """Only exact source input fields enter features; IDs/hashes/labels excluded."""
    if type(snapshot) is not dict or snapshot.get("schema_version") != "semantic_input.v1":
        return None, ["unknown_schema"]
    utterance, question = snapshot.get("utterance"), snapshot.get("question")
    if type(utterance) is not dict or type(question) is not dict:
        return None, ["malformed_source"]
    text = utterance.get("text")
    if type(text) is not str or not text.strip() or len(text) > 4096:
        return None, ["missing_or_oversized_raw_text"]
    if utterance.get("source") != "authored_fixture" or utterance.get("complete_transport") is not True:
        return None, ["untrusted_or_truncated_source"]
    if utterance.get("source_turn_id") != snapshot.get("turn_id"):
        return None, ["source_binding_mismatch"]
    phase, role, qtext = snapshot.get("phase"), question.get("role"), question.get("text", "")
    if any(type(v) is not str for v in (phase, role, qtext)) or len(qtext) > 2048:
        return None, ["structured_context_rejected"]
    if any(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", v) is None for v in (phase, role)):
        return None, ["unknown_context_symbol"]
    if phase == "security" or role == "security" or question.get("security_field") is not None:
        return None, ["security_context_mask"]
    if re.search(r"\b(?:password|passcode|security\s+code|social\s+security|cvv|pin\s+code)\b", text, re.I):
        return None, ["unisolated_security_surface"]
    # Punctuation gives source intervals, never annotation clause boundaries.
    spans = [(m.start(), m.end()) for m in re.finditer(r"[^;.!?\n]+[;.!?]?", text) if m.group().strip()]
    if not spans or len(spans) >= MAX_NODES:
        return None, ["source_clause_overflow"]
    context_keys = []
    if include_context:
        context_keys = ["phase:" + phase, "question_role:" + role] + ["q:" + k for k in lexical(qtext)]
        context_keys += ["readback_present:" + str(type(snapshot.get("active_readback")) is dict),
                         "offer_present:" + str(bool(snapshot.get("spoken_offers")))]
    nodes = [vector(["node:question"] + context_keys)]
    nodes += [vector(["node:user"] + lexical(text[a:b])) for a, b in spans]
    edges = []
    if include_edges:
        if include_context:
            edges += [[0, i, "question_context"] for i in range(1, len(nodes))]
        edges += [[i - 1, i, "speech_order"] for i in range(2, len(nodes))]
    flat = vector(lexical(text) + context_keys)
    return {"nodes": nodes, "edges": edges, "user_nodes": list(range(1, len(nodes))),
            "source_spans": [[a, b] for a, b in spans], "linear": flat}, []


def sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-min(z, 700)))
    e = math.exp(max(z, -700))
    return e / (1.0 + e)


def raw_score(snapshot, bundle):
    if bundle.get("version") != VERSION or bundle.get("qualified") is not False:
        raise ValueError("Unqualified day2 bundle required")
    graph, reasons = source_input(snapshot, bundle["include_context"], bundle["include_edges"])
    if graph is None:
        return None, reasons
    params = bundle["parameters"]
    if bundle["architecture"] == "sparse_logistic":
        return sigmoid(params["bias"] + sum(params["weights"][i] * v for i, v in graph["linear"].items())), []
    if bundle["architecture"] != "tiny_relational_gnn":
        raise ValueError("Unsupported architecture")
    h0 = [[math.tanh(params["embedding_bias"][j] + sum(params["embedding"][i][j] * v for i, v in node.items()))
           for j in range(HIDDEN)] for node in graph["nodes"]]
    incoming = {i: [] for i in range(len(h0))}
    for source, dest, relation in graph["edges"]:
        incoming[dest].append((source, relation))
    h1 = []
    for i, row in enumerate(h0):
        values = []
        for j in range(HIDDEN):
            z = params["message_bias"][j] + sum(row[k] * params["self"][k][j] for k in range(HIDDEN))
            for source, relation in incoming[i]:
                z += sum(h0[source][k] * params[relation][k][j] for k in range(HIDDEN))
            values.append(math.tanh(z))
        h1.append(values)
    pooled = [sum(h1[i][j] for i in graph["user_nodes"]) / len(graph["user_nodes"]) for j in range(HIDDEN)]
    return sigmoid(params["bias"] + sum(pooled[j] * params["readout"][j] for j in range(HIDDEN))), []


def predict(snapshot, bundle):
    """Semantic proposal only. No score can relax any external guard."""
    score, reasons = raw_score(snapshot, bundle)
    binding = {k: snapshot.get(k) for k in ("turn_id", "state_revision", "policy_hash", "api_hash")}
    return {"version": VERSION, "binding": binding, "status": "abstain", "qualified": False,
            "candidate": {"primary_is_payment_proposal": score >= 0.5} if score is not None else None,
            "uncalibrated_binary_score": score, "authority": "none", "training_admission": False,
            "reasons": reasons + ["experimental_only", "uncalibrated", "ancestry_unqualified", "deployment_closed"]}
