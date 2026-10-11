"""Source-only portable features, shared by future fitting and inference.

Graph uses observed speaker/text ordering, never publisher graph IDs/targets.
No bank policy, consent, normalized dates or semantic gold inferred here.
"""
import hashlib
import math
import re

VERSION = "day2.multisource.features.v1"
WIDTH = 512
MAX_NODES = 8
RELATIONS = ("turn_membership", "source_order", "observed_next_turn")


def feature_keys(text, neutral_placeholders=False):
    if type(text) is not str or type(neutral_placeholders) is not bool:
        raise ValueError("Typed text/flag required")
    text = re.sub(r"\d+(?:st|nd|rd|th)?", "number", text.casefold())
    if neutral_placeholders:
        text = re.sub(r"\[redacted(?:_[a-z]+)*\]", " ", text)
    words = re.findall(r"[^\W\d_]+", text)
    return (["w:" + w for w in words] + ["b:" + a + " " + b for a, b in zip(words, words[1:])]
            + ["c:" + text[i:i + 3] for i in range(len(text) - 2)])


def sparse(keys):
    result = {}
    for key in keys:
        digest = hashlib.sha256(key.encode("utf8")).digest()
        index = int.from_bytes(digest[:4], "little") % WIDTH
        result[index] = result.get(index, 0.0) + (1 if digest[4] & 1 else -1)
    norm = math.sqrt(sum(v * v for v in result.values())) or 1.0
    return {index: value / norm for index, value in result.items() if value}


def source_graph(snapshot, use_edges=True, neutral_placeholders=False, latest_only=False):
    if any(type(v) is not bool for v in (use_edges, neutral_placeholders, latest_only)):
        raise ValueError("Feature controls must be booleans")
    if type(snapshot) is not dict or set(snapshot) != {"text", "context"}:
        raise ValueError("Runtime input accepts only text and context")
    text, context = snapshot["text"], snapshot["context"]
    if type(text) is not str or type(context) is not list or len(context) > 6:
        raise ValueError("Malformed raw source")
    if len(text) > 8192:
        return None
    for turn in context:
        if (type(turn) is not dict or set(turn) != {"speaker", "text"}
                or type(turn["speaker"]) is not str or turn["speaker"] not in {"user", "assistant"}
                or type(turn["text"]) is not str):
            raise ValueError("Malformed role/text")
        if len(turn["text"]) > 8192:
            return None
    if context and context[-1]["text"] != text:
        raise ValueError("Source mismatch")
    if not text.strip() and not any(t["text"].strip() for t in context):
        return None
    keys = lambda value: feature_keys(value, neutral_placeholders)
    if context and not latest_only:
        turns = [sparse(["type:turn", "speaker:" + t["speaker"]] + keys(t["text"])) for t in context]
        summary = sparse(["type:summary"] + [k for t in context for k in ["speaker:" + t["speaker"]] + keys(t["text"])])
        nodes = [summary] + turns
        edges = [[0, j, "turn_membership"] for j in range(1, len(nodes))] if use_edges else []
        if use_edges:
            edges += [[j - 1, j, "observed_next_turn"] for j in range(2, len(nodes))]
        # 0.5 last context + 0.5 last USER, or context mean if there is no USER.
        users = [j + 1 for j, turn in enumerate(context) if turn["speaker"] == "user"]
        local_readout = [len(nodes) - 1, users[-1]] if users else list(range(1, len(nodes)))
        readout = [0] + local_readout
        readout_weights = [0.5] + [0.5 / len(local_readout)] * len(local_readout)
        linear = {}
        for j, weight in zip(readout, readout_weights):
            for k, v in nodes[j].items():
                linear[k] = linear.get(k, 0.0) + v * weight
    else:
        tokens = list(re.finditer(r"\S+", text))
        if not tokens:
            return None
        count = min(3, max(1, (len(tokens) + 5) // 6))
        spans = [(tokens[j * len(tokens) // count].start(), tokens[(j + 1) * len(tokens) // count - 1].end()) for j in range(count)]
        speaker = context[-1]["speaker"] if context else "user"
        nodes = [sparse(["type:turn", "speaker:" + speaker] + keys(text))]
        nodes += [sparse(["type:ordered_span"] + keys(text[a:b])) for a, b in spans]
        edges = [[0, j, "turn_membership"] for j in range(1, len(nodes))] if use_edges else []
        if use_edges:
            edges += [[j - 1, j, "source_order"] for j in range(2, len(nodes))]
        readout = list(range(len(nodes)))
        readout_weights = [0.5] + [0.5 / (len(nodes) - 1)] * (len(nodes) - 1)
        linear = {}
        for j, weight in zip(readout, readout_weights):
            for k, v in nodes[j].items():
                linear[k] = linear.get(k, 0.0) + v * weight
    if len(nodes) > MAX_NODES:
        return None
    return {"version": VERSION, "nodes": nodes, "edges": edges, "readout_nodes": readout,
            "readout_weights": readout_weights,
            "linear": linear, "all_source_turns_retained": not latest_only,
            "annotation_features": False}
