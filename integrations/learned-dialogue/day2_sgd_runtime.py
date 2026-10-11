"""Stdlib-only offline shared-schema semantic proposals; no bank authority."""
import argparse
import base64
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct

_path = Path(__file__).with_name("day2_sgd_adapter.py")
_spec = importlib.util.spec_from_file_location("day2_sgd_adapter_runtime", _path)
adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adapter)
SHAPES = {"E": [512, 32], "node_bias": [32], "query_bias": [32], "Bcurrent": [32, 32], "Bcontext": [32, 32], "Bprior": [5, 32], "Wmessage": [2, 32, 32], "Bmessage": [32, 32], "Whead": [5, 32, 32], "head_bias": [5], "prior_head": [5, 2]}
HEADS = adapter.HEADS


def mat(vector, matrix, rows, cols, offset=0):
    return [sum(vector[i] * matrix[offset + i * cols + j] for i in range(rows)) for j in range(cols)]


def sigmoid(x):
    return 1 / (1 + math.exp(-max(-60, min(60, x))))


def softmax(values):
    maximum = max(values)
    values = [math.exp(v - maximum) for v in values]
    total = sum(values)
    return [v / total for v in values]


def initial_memory(spec):
    return {"intent": [0.] * spec["intent_count"], "requested": [0.] * spec["slot_count"], "presence": [0.] * spec["slot_count"], "acts": [0.] * spec["act_count"], "known": 0.}


class CompiledModel:
    def __init__(self, spec, record):
        self.spec, self.relations = spec, record["relations"]
        self.weights = {}
        assert set(record["weights"]) == set(SHAPES)
        for name, shape in SHAPES.items():
            entry = record["weights"][name]
            assert entry["shape"] == shape
            raw = base64.b64decode(entry["float32_le_base64"], validate=True)
            count = math.prod(shape)
            assert len(raw) == count * 4
            values = list(struct.unpack("<" + str(count) + "f", raw))
            assert all(math.isfinite(x) for x in values)
            self.weights[name] = values
        w = self.weights
        self.queries = []
        for text in spec["query_texts"]:
            projection = mat(adapter.vector(text), w["E"], 512, 32)
            self.queries.append([math.tanh(a + b) for a, b in zip(projection, w["query_bias"])])

    def logits(self, observed, prior):
        nodes = adapter.observed_nodes(observed)
        w, hidden = self.weights, []
        for i, (role, text) in enumerate(nodes):
            projection = mat(adapter.vector(text, role, len(nodes) - 1 - i), w["E"], 512, 32)
            hidden.append([math.tanh(a + b) for a, b in zip(projection, w["node_bias"])])
        mean = [sum(v[j] for v in hidden) / len(hidden) for j in range(32)]
        entropy = -sum(p * math.log(max(p, 1e-9)) for p in prior["intent"]) / len(self.spec["services"])
        summary = [entropy, sum(prior["requested"]) / len(prior["requested"]), sum(prior["presence"]) / len(prior["presence"]), sum(prior["acts"]) / len(prior["acts"]), prior["known"]]
        current_path = mat(hidden[-1], w["Bcurrent"], 32, 32)
        context_path = mat(mean, w["Bcontext"], 32, 32)
        prior_path = mat(summary, w["Bprior"], 5, 32)
        base = [a + b + c for a, b, c in zip(current_path, context_path, prior_path)]
        if self.relations and len(nodes) > 1:
            messages = [mat(hidden[i], w["Wmessage"], 32, 32, int(nodes[i][0] == "SYSTEM") * 1024) for i in range(len(nodes) - 1)]
            relation = [sum(v[j] for v in messages) / len(messages) for j in range(32)]
            projected = mat(relation, w["Bmessage"], 32, 32)
            base = [a + b for a, b in zip(base, projected)]
        pooled = [math.tanh(x) for x in base]
        output = {}
        for hi, h in enumerate(HEADS):
            kind = "intent" if h == "intent" else "act" if h == "acts" else "slot"
            start, end = self.spec["query_slices"][kind]
            state = mat(pooled, w["Whead"], 32, 32, hi * 1024)
            previous = prior["presence"] if h == "updates" else prior[h]
            output[h] = []
            for j, qi in enumerate(range(start, end)):
                owner = self.spec["query_owners"][kind][j]
                query = [(a + b) / math.sqrt(2) for a, b in zip(self.queries[qi], self.queries[owner])]
                score = sum(a * b for a, b in zip(state, query)) / math.sqrt(32)
                score += w["head_bias"][hi] + previous[j] * w["prior_head"][hi * 2] + prior["known"] * w["prior_head"][hi * 2 + 1]
                output[h].append(score)
        return output

    def memory(self, logits):
        out = initial_memory(self.spec)
        for service in self.spec["services"]:
            a, c = service["intent_offset"], len(service["intents"])
            out["intent"][a:a + c] = softmax(logits["intent"][a:a + c])
        for h in ("presence",):
            out[h] = [sigmoid(v) for v in logits[h]]
        out["known"] = 1.
        return out


class SemanticSession:
    def __init__(self, bundle_path, expected_sha256, arm="G_relations"):
        self.available, self.reason = False, "unavailable"
        self.key, self.prior = None, None
        try:
            raw = Path(bundle_path).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == expected_sha256
            bundle = json.loads(raw)
            spec = bundle["schema"]
            recomputed = adapter.schema_spec(spec["source_schema"], spec["acts"])
            assert spec == recomputed and len(spec["services"]) == 26 and spec["slot_count"] == 215 and spec["intent_count"] == 79
            self.model = CompiledModel(spec, bundle["arms"][arm])
            self.spec, self.calibration = spec, bundle["calibration"][arm]
            for h in HEADS:
                c = self.calibration[h]
                assert math.isfinite(c["temperature"]) and c["temperature"] > 0
                assert math.isfinite(c["threshold"]) and 0 <= c["threshold"] <= 1
            self.available, self.reason = True, "available_semantic_only"
        except (OSError, ValueError, KeyError, TypeError, AssertionError, OverflowError) as error:
            self.reason = "artifact_unavailable:" + type(error).__name__

    def reset(self):
        self.key, self.prior = None, None

    def step(self, observed, dialogue_key, split_key="runtime"):
        if not self.available:
            return {"available": False, "abstain": True, "reason": self.reason, "bank_authority": None}
        key = (split_key, dialogue_key)
        if key != self.key:
            self.prior, self.key = initial_memory(self.spec), key
        try:
            logits = self.model.logits(observed, self.prior)
            self.prior = self.model.memory(logits)
            services = []
            for service in self.spec["services"]:
                a, c = service["intent_offset"], len(service["intents"])
                cfg = self.calibration["intent"]
                probs = softmax([x / cfg["temperature"] for x in logits["intent"][a:a + c]])
                winner = max(range(c), key=lambda i: probs[i])
                slots = []
                for j, name in enumerate(service["slots"]):
                    index = service["slot_offset"] + j
                    item = {"slot": name, "value": "UNKNOWN", "KEEP_SET": "UNKNOWN", "DELETE": "UNKNOWN"}
                    for h in ("requested", "presence"):
                        cfg = self.calibration[h]
                        probability = sigmoid(logits[h][index] / cfg["temperature"])
                        item[h + "_probability"] = probability
                        item[h + "_proposal"] = bool(probability >= cfg["threshold"]) if cfg["available"] else "UNKNOWN"
                    slots.append(item)
                act_cfg = self.calibration["acts"]
                acts = {name: sigmoid(logits["acts"][service["act_offset"] + j] / act_cfg["temperature"]) for j, name in enumerate(self.spec["acts"])}
                services.append({"service": service["name"], "relevance": "UNKNOWN", "intent": service["intents"][winner], "intent_confidence": probs[winner], "intent_abstain": not self.calibration["intent"]["available"] or probs[winner] < self.calibration["intent"]["threshold"], "slots": slots, "publisher_act_probabilities": acts})
            return {"available": True, "services": services, "bank_authority": None, "ledger_truth": None, "complete_DST": False}
        except (ValueError, KeyError, TypeError, AssertionError, OverflowError):
            self.reset()
            return {"available": False, "abstain": True, "reason": "invalid_observed_input", "bank_authority": None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    session = SemanticSession(args.bundle, args.sha256)
    print(json.dumps(session.step({"speaker": "USER", "utterance": args.text, "earlier_context": []}, "new-dialogue"), ensure_ascii=False))
