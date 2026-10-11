"""Pure proposal-only student runtime: STUDENT != V2.

student_predict returns exactly status, scores, labels, bank_authority, and
financial_authorization. The latter is always UNKNOWN, including on malformed
input; this student never establishes financial authorization. Parents using a
closed output schema must explicitly permit that field before integration.
student_features raises ValueError for malformed input; prediction returns INVALID.
No model loading, I/O, input mutation, or auxiliary-label selection occurs here.
"""

import json
import re


DOMAIN7 = (
    "proposal", "dispute", "correction", "current_affirm", "current_withdraw",
    "uncertain", "reported_third_party",
)
AUX4 = ("AFFIRM", "NEGATE", "INFORM", "REQUEST")
LABELS = DOMAIN7 + AUX4
FEATURE_DIM = 768
MIN_THRESHOLDS = (0.5, 0.5, 0.5, 1.01, 1.01, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
_ACTIVE = (0, 1, 2, 5, 6)
_MODEL_KEYS = (
    "schema", "labels", "feature_dim", "quantization", "weights", "scales",
    "bias", "thresholds", "disabled_heads",
    "context_mode", "bank_authority", "financial_authorization",
    "logit_cutoffs", "quant_logit_margins",
)


def _valid_input(current, previous):
    if type(current) is not str or not current.strip() or len(current) > 16384:
        return False
    if type(previous) is not list or len(previous) > 2:
        return False
    for turn in previous:
        if type(turn) is not dict or set(turn) != {"speaker", "text"}:
            return False
        if type(turn["speaker"]) is not str or turn["speaker"] not in (
            "ASSISTANT", "USER", "SYSTEM",
        ):
            return False
        if type(turn["text"]) is not str or len(turn["text"]) > 16384:
            return False
    return True


def _finite(value):
    return type(value) in (int, float) and -float("inf") < value < float("inf")


def _valid_model(model):
    if type(model) is not dict or any(key not in model for key in _MODEL_KEYS):
        return False
    if model["bank_authority"] is not False or type(model["financial_authorization"]) is not str or model["financial_authorization"] != "UNKNOWN":
        return False
    if type(model["context_mode"]) is not str or model["context_mode"] not in ("current_only", "observed_prior"):
        return False
    if type(model["schema"]) is not str or model["schema"] != "live_v2_student.v1":
        return False
    if type(model["labels"]) is not list or model["labels"] != list(LABELS):
        return False
    if any(type(label) is not str for label in model["labels"]):
        return False
    if type(model["feature_dim"]) is not int or model["feature_dim"] != FEATURE_DIM:
        return False
    if type(model["quantization"]) is not str or model["quantization"] != "int8_per_head":
        return False
    disabled = model["disabled_heads"]
    if type(disabled) is not list or disabled != ["current_affirm", "current_withdraw"]:
        return False
    if any(type(label) is not str for label in disabled):
        return False
    rows = model["weights"]
    if type(rows) is not list or len(rows) != 11:
        return False
    for row in rows:
        if type(row) is not list or len(row) != FEATURE_DIM:
            return False
        if any(type(weight) is not int or not -127 <= weight <= 127 for weight in row):
            return False
    for key in ("scales", "bias", "thresholds", "logit_cutoffs", "quant_logit_margins"):
        values = model[key]
        if type(values) is not list or len(values) != 11:
            return False
        if any(not _finite(value) for value in values):
            return False
    if any(type(scale) is not float or scale <= 0 for scale in model["scales"]):
        return False
    if any(type(bias) is not float for bias in model["bias"]):
        return False
    if any(value < floor for value, floor in zip(model["thresholds"], MIN_THRESHOLDS)):
        return False
    if any(value < 0 for value in model["quant_logit_margins"]):
        return False
    return True


def _add(block, feature):
    hashed = 2166136261
    for char in feature:
        hashed = ((hashed ^ ord(char)) * 16777619) & 0xffffffff
    block[hashed % 256] += 1 if hashed & 0x80000000 == 0 else -1


def _block(text):
    block = [0.0] * 256
    tokens = re.findall(r"[\w]+|[^\w\s]", text.lower())
    for index, token in enumerate(tokens):
        _add(block, "w:" + token)
        if index:
            _add(block, "b:" + tokens[index - 1] + " " + token)
        for start in range(len(token) - 2):
            _add(block, "c:" + token[start:start + 3])
    norm = sum(value * value for value in block) ** 0.5
    return [value / norm for value in block] if norm else block


def student_features(current, previous, no_context=False):
    """Return three independently L2-normalized 256-bin count blocks.

    Blocks represent the entire current text, its final 512 characters, and
    chronological prior turns. SYSTEM is rendered as ASSISTANT. no_context
    zeroes only the prior block; even ignored context must satisfy the contract.
    """
    if not _valid_input(current, previous) or type(no_context) is not bool:
        raise ValueError("Invalid student input")
    prior = "" if no_context else "\n".join(
        ("ASSISTANT" if turn["speaker"] == "SYSTEM" else turn["speaker"])
        + ": " + turn["text"] for turn in previous
    )
    return _block(current) + _block(current[-512:]) + _block(prior)


def _result(status, scores, labels):
    return {
        "status": status,
        "scores": scores,
        "labels": labels,
        "bank_authority": False,
        "financial_authorization": "UNKNOWN",
    }


def student_predict(current: str, previous: list, model: dict) -> dict:
    """Return diagnostic scores and active domain proposals, never authority."""
    if not _valid_input(current, previous) or not _valid_model(model):
        return _result("INVALID", [0.0] * 11, [])
    features = student_features(current, previous, no_context=model["context_mode"] == "current_only")
    if not any(features[:512]):
        return _result("ABSTAIN", [0.0] * 11, [])
    scores = []
    logits = []
    for row, scale, bias in zip(model["weights"], model["scales"], model["bias"]):
        # Scale after the dot product to avoid overflow during cancellation.
        logit = sum(weight * value for weight, value in zip(row, features)) * scale + bias
        if not _finite(logit):
            return _result("INVALID", [0.0] * 11, [])
        logits.append(logit)
        logit = max(-60.0, min(60.0, logit))
        scores.append(1.0 / (1.0 + 2.718281828459045 ** (-logit)))
    selected = [LABELS[index] for index in _ACTIVE
                if scores[index] >= model["thresholds"][index]
                and logits[index] >= model["logit_cutoffs"][index] + model["quant_logit_margins"][index]]
    return _result("OK" if selected else "ABSTAIN", scores, selected)
