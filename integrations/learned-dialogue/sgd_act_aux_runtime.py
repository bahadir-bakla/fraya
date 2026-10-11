"""Stdlib source USER-act proposals. No bank permission or ledger authority.

Training uses sklearn HashingVectorizer; this module reproduces its signed
MurmurHash3 word unigram/bigram hashing and L2 normalization without sklearn.
Only observed current text and the immediately preceding SYSTEM text are read.
"""
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

ACTS = ("AFFIRM", "NEGATE", "INFORM", "REQUEST")
DIM = 4096
TOKEN = re.compile(r"(?u)\b\w\w+\b")


def observed_text(observed):
    if not isinstance(observed, dict) or observed.get("speaker") != "USER":
        raise ValueError("Expected observed USER input")
    current = observed.get("utterance")
    context = observed.get("earlier_context")
    if not isinstance(current, str) or not isinstance(context, list):
        raise ValueError("Invalid observed text/context")
    previous = ""
    if context:
        last = context[-1]
        if not isinstance(last, dict) or last.get("speaker") not in ("SYSTEM", "USER") or not isinstance(last.get("text"), str):
            raise ValueError("Invalid previous observed turn")
        if last["speaker"] == "SYSTEM":
            previous = last["text"]
    return current, previous


def feature_text(current, previous="", with_context=True):
    # Role prefixes are derived exclusively from observed turn position/speaker.
    words = ["u__" + w for w in TOKEN.findall(current.lower())]
    if with_context:
        words += ["s__" + w for w in TOKEN.findall(previous.lower())]
    return " ".join(words)


def murmur3(text):
    data = text.encode("utf-8")
    h, mask = 0, 0xffffffff
    limit = len(data) - len(data) % 4
    for i in range(0, limit, 4):
        k = int.from_bytes(data[i:i + 4], "little")
        k = (k * 0xcc9e2d51) & mask
        k = ((k << 15) | (k >> 17)) & mask
        k = (k * 0x1b873593) & mask
        h ^= k
        h = ((h << 13) | (h >> 19)) & mask
        h = (h * 5 + 0xe6546b64) & mask
    tail = data[limit:]
    if tail:
        k = int.from_bytes(tail, "little")
        k = (k * 0xcc9e2d51) & mask
        k = ((k << 15) | (k >> 17)) & mask
        h ^= (k * 0x1b873593) & mask
    h ^= len(data)
    h ^= h >> 16
    h = (h * 0x85ebca6b) & mask
    h ^= h >> 13
    h = (h * 0xc2b2ae35) & mask
    h ^= h >> 16
    return h if h < 0x80000000 else h - 0x100000000


def vector(current, previous="", with_context=True):
    words = TOKEN.findall(feature_text(current, previous, with_context))
    terms = words + [a + " " + b for a, b in zip(words, words[1:])]
    counts = Counter()
    for term in terms:
        h = murmur3(term)
        # Match sklearn's special handling of the minimum signed int32 hash.
        index = (2147483647 - (DIM - 1)) % DIM if h == -2147483648 else abs(h) % DIM
        counts[index] += 1 if h >= 0 else -1
    norm = math.sqrt(sum(v * v for v in counts.values()))
    return {i: v / norm for i, v in counts.items() if v} if norm else {}


def sigmoid(score):
    if score >= 0:
        return 1 / (1 + math.exp(-score))
    ex = math.exp(score)
    return ex / (1 + ex)


class ActProposer:
    def __init__(self, weights_path, calibration_path, expected_weights_sha256=None,
                 expected_calibration_sha256=None):
        raw = Path(weights_path).read_bytes()
        self.weights_sha256 = hashlib.sha256(raw).hexdigest()
        if expected_weights_sha256 and self.weights_sha256 != expected_weights_sha256:
            raise ValueError("Weights hash mismatch")
        self.weights = json.loads(raw)
        raw_cal = Path(calibration_path).read_bytes()
        if expected_calibration_sha256 and hashlib.sha256(raw_cal).hexdigest() != expected_calibration_sha256:
            raise ValueError("Calibration hash mismatch")
        self.calibration = json.loads(raw_cal)
        if self.calibration["weights_sha256"] != self.weights_sha256:
            raise ValueError("Calibration does not belong to these frozen weights")
        if self.weights["acts"] != list(ACTS) or self.weights["features"]["n_features"] != DIM:
            raise ValueError("Invalid act/features contract")
        if self.weights["format"] != "sgd-source-act-aux.v1":
            raise ValueError("Unknown format")
        for arm in ("context", "no_context"):
            if set(self.weights["arms"][arm]) != set(ACTS):
                raise ValueError("Invalid heads")
            for act in ACTS:
                head = self.weights["arms"][arm][act]
                if len(head["coef"]) != DIM or not all(math.isfinite(x) for x in head["coef"] + [head["intercept"]]):
                    raise ValueError("Invalid weights")
                threshold = self.calibration["arms"][arm][act]["threshold"]
                if threshold is not None and (not math.isfinite(threshold) or not 0 <= threshold <= 1):
                    raise ValueError("Invalid threshold")

    def propose(self, observed, arm="context"):
        if arm not in ("context", "no_context"):
            raise ValueError("Unknown arm")
        current, previous = observed_text(observed)
        x = vector(current, previous, arm == "context")
        result = {}
        for act in ACTS:
            head = self.weights["arms"][arm][act]
            score = head["intercept"] + sum(head["coef"][i] * value for i, value in x.items())
            probability = sigmoid(score)
            cfg = self.calibration["arms"][arm][act]
            accepted = cfg["threshold"] is not None and probability >= cfg["threshold"]
            result[act] = {"source_act_probability": probability,
                           "accepted_positive_proposal": accepted,
                           "proposal": act if accepted else "UNKNOWN"}
        return {"source_USER_acts": result, "bank_authority": None,
                "financial_authorization": "UNKNOWN", "ledger_truth": None,
                "Freya_validated": False,
                "scope": "SGD source acts only; AFFIRM conveys no financial authorization"}
