"""Public SGD observed-input features and independent publisher target adapter.
Stdlib only; annotation/value/ancestry fields never enter feature functions.
"""
from collections import Counter
from functools import lru_cache
import hashlib
import math
import re

D, H = 512, 32
HEADS = ("intent", "requested", "presence", "acts")


@lru_cache(maxsize=8192)
def lexical(text):
    words = re.findall(r"[\w']+|\[REDACTED\]", text.casefold())[:64]
    tokens = ["w:" + w for w in words]
    tokens += ["b:" + a + ":" + b for a, b in zip(words, words[1:])]
    if not tokens:
        tokens = ["EMPTY"]
    counts = Counter()
    for token in tokens:
        number = int.from_bytes(hashlib.blake2s(token.encode(), digest_size=8).digest(), "little")
        counts[number % D] += 1 if (number >> 9) & 1 else -1
    return tuple(counts.items())


def vector(text, role="SCHEMA", age=0):
    counts = dict(lexical(text))
    for token in ["ROLE:" + role, "AGE:" + str(age)]:
        number = int.from_bytes(hashlib.blake2s(token.encode(), digest_size=8).digest(), "little")
        j = number % D
        counts[j] = counts.get(j, 0) + (1 if (number >> 9) & 1 else -1)
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1
    out = [0.0] * D
    for j, value in counts.items():
        out[j] = value / norm
    return out


def observed_nodes(observed):
    assert observed["speaker"] == "USER"
    earlier = observed.get("earlier_context", [])
    assert len(earlier) <= 8
    nodes = [(r["speaker"], r["text"]) for r in earlier] + [(observed["speaker"], observed["utterance"])]
    assert all(role in ("USER", "SYSTEM") and isinstance(text, str) for role, text in nodes)
    return nodes


def features(row):
    nodes = observed_nodes(row["input"])
    values = [vector(text, role, len(nodes) - 1 - i) for i, (role, text) in enumerate(nodes)]
    return values + [[0.0] * D for _ in range(9 - len(nodes))], [1.0] * len(nodes) + [0.0] * (9 - len(nodes)), [int(role == "SYSTEM") for role, _ in nodes] + [0] * (9 - len(nodes))


def schema_spec(schema, acts):
    services, queries, owners = [], [], []
    for s, item in enumerate(schema):
        services.append({"name": item["service_name"], "intents": ["NONE"] + [x["name"] for x in item["intents"]], "slots": [x["name"] for x in item["slots"]]})
        queries.append(item["service_name"] + " " + item["description"])
    slices, io, so, ao = {}, 0, 0, 0
    for s, item in enumerate(schema):
        services[s]["intent_offset"] = io
        services[s]["slot_offset"] = so
        services[s]["act_offset"] = ao
        io += len(services[s]["intents"])
        so += len(item["slots"])
        ao += len(acts)
    for kind in ("intent", "slot", "act"):
        start = len(queries)
        own = []
        for s, item in enumerate(schema):
            prefix = item["service_name"] + " " + item["description"] + " "
            if kind == "intent":
                descriptions = ["NONE no active publisher intent"] + [x["name"] + " " + x["description"] + " required " + " ".join(x["required_slots"]) + " optional " + " ".join(x["optional_slots"]) for x in item["intents"]]
            elif kind == "slot":
                descriptions = [x["name"] + " " + x["description"] for x in item["slots"]]
            else:
                descriptions = ["publisher USER act " + act.replace("_", " ") for act in acts]
            queries += [prefix + text for text in descriptions]
            own += [s] * len(descriptions)
        slices[kind] = [start, len(queries)]
        owners.append(own)
    return {"services": services, "acts": acts, "query_texts": queries, "query_slices": slices, "query_owners": dict(zip(("intent", "slot", "act"), owners)), "intent_count": io, "slot_count": so, "act_count": ao, "source_schema": schema}


def targets(row, spec):
    sizes = {"intent": len(spec["services"]), "requested": spec["slot_count"], "presence": spec["slot_count"], "acts": spec["act_count"], "updates": spec["slot_count"]}
    y = {h: [0] * n for h, n in sizes.items()}
    masks = {h: [0.0] * n for h, n in sizes.items()}
    reasons = Counter()
    service_ids = {s["name"]: i for i, s in enumerate(spec["services"])}
    for frame in row.get("targets", {}).get("frames", []):
        name = frame.get("service")
        if name not in service_ids or not row.get("service_supervision_masks", {}).get(name, False):
            reasons["frame_service_unknown_or_unobserved"] += 1
            continue
        sid = service_ids[name]
        service = spec["services"][sid]
        flags = frame.get("head_masks", {})
        if flags.get("active_intent") and isinstance(frame.get("active_intent_id"), int) and 0 <= frame["active_intent_id"] < len(service["intents"]) and frame.get("active_intent") == service["intents"][frame["active_intent_id"]]:
            y["intent"][sid], masks["intent"][sid] = frame["active_intent_id"], 1.0
        else:
            reasons["intent_missing_or_invalid"] += 1
        for h, field in [("requested", "requested_slots"), ("presence", "published_slot_map_presence")]:
            values = frame.get(field)
            if flags.get(field) and isinstance(values, list) and len(values) == len(service["slots"]) and all(v in (0, 1) for v in values):
                for j, value in enumerate(values):
                    index = service["slot_offset"] + j
                    y[h][index], masks[h][index] = value, 1.0
            else:
                reasons[h + "_missing_or_invalid"] += 1
        actions = frame.get("actions")
        if flags.get("publisher_actions") and isinstance(actions, list):
            for j, act in enumerate(spec["acts"]):
                index = service["act_offset"] + j
                y["acts"][index] = int(any(a.get("act") == act for a in actions))
                masks["acts"][index] = 1.0
            reasons["unknown_act_masked"] += sum(a.get("act") not in spec["acts"] for a in actions)
        else:
            reasons["actions_missing_or_invalid"] += 1
        # Independent audit found partial-word recoverability matches and one
        # affected KEEP/SET target. Frozen V1 update/value heads stay UNKNOWN.
        reasons["updates_disabled_independent_word_boundary_audit"] += len(frame.get("belief_updates", []))
        assert not frame.get("DELETE_mask", False)
        assert not any(flags.get(h, False) for h in ("bank_policy", "bank_permission", "ledger"))
    return y, masks, reasons


def clear_feature_cache():
    lexical.cache_clear()
