"""Pure stdlib sparse semantic inference. No I/O, tools or permission kernel.

Bundle loading and persistence live in the offline trainer. This module can be
embedded as source in a Python code step after separate deployment review.
"""
import hashlib
import math
import re
from collections import Counter

HEADS = ("primaryintent", "secondaryintent", "completion", "unresolvedcomponent")
INTENTS = ("account_question", "callback", "card_issue", "dispute", "human_support", "payment_discussion", "stop_contact", "unknown")
LABELS = {"primaryintent": INTENTS, "secondaryintent": ("none",) + INTENTS,
          "completion": ("complete", "unfinished", "correction", "negated", "unknown"),
          "unresolvedcomponent": ("none", "utterance_tail", "correction_target", "negated_scope", "intent")}
FORMAT = "learned-dialogue-sparse-softmax-v1"


def words(text):
    return re.findall(r"[a-z]+(?:'[a-z]+)?|\d+", text.lower().replace("\u2019", "'"))


def features(text):
    tokens = words(text)
    counts = Counter("w:" + t for t in tokens)
    counts.update("b:" + a + "/" + b for a, b in zip(tokens, tokens[1:]))
    padded = "^" + " ".join(tokens) + "$"
    counts.update("c:" + padded[i:i + 3] for i in range(len(padded) - 2))
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {key: value / norm for key, value in counts.items()}


def softmax(logits, temperature=1.0):
    values = [x / temperature for x in logits]
    peak = max(values)
    exps = [math.exp(x - peak) for x in values]
    total = sum(exps)
    return [x / total for x in exps]


def score(model, text):
    vector = features(text)
    result, confidence = {}, {}
    for name in HEADS:
        head = model["heads"][name]
        logits = [bias + sum(weights.get(k, 0.0) * v for k, v in vector.items())
                  for bias, weights in zip(head["bias"], head["weights"])]
        probs = softmax(logits, head.get("temperature", 1.0))
        ordered = sorted(range(len(probs)), key=lambda i: (-probs[i], i))
        result[name] = head["labels"][ordered[0]]
        confidence[name] = {"max_score": probs[ordered[0]], "margin": probs[ordered[0]] - probs[ordered[1]],
                            "distribution": dict(zip(head["labels"], probs))}
    return result, confidence


def uncertainty_guard(text):
    """Conservative lexical guard, not a complete language/ASR safety oracle."""
    normalized = text.lower().replace("\u2019", "'")
    tokens = words(normalized)
    correction = re.search(r"\b(actually|i meant|i mean|no wait|let me correct|revise|start again)\b", normalized)
    negation = re.search(r"\b(not|never|cannot|can't|don't|won't|isn't|didn't|no|unable)\b", normalized)
    conditional = re.search(r"\b(if|maybe|perhaps|might|could possibly|provided)\b", normalized)
    if correction:
        return "correction", "correction_target", "explicit_correction"
    if negation:
        return "negated", "negated_scope", "explicit_negation"
    if conditional:
        return "unknown", "intent", "conditional_uncertainty"
    tail = {"and", "or", "at", "on", "for", "is", "are", "was", "with", "to", "could", "when", "the", "a"}
    if len(tokens) < 3 or (tokens and tokens[-1] in tail) or normalized.rstrip().endswith(("...", "-", "\u2026")):
        return "unfinished", "utterance_tail", "incomplete_utterance"
    if tokens and all(t.isdigit() or t in {"one", "two", "three", "seven", "twenty", "hundred", "thousand", "and"} for t in tokens):
        return "unfinished", "utterance_tail", "unanchored_number_fragment"
    return None


def component_observations(text):
    """Evidence offsets only, no parsed numbers/dates/security values.

    V0 does not learn component completeness or targets. Detected spans remain
    ambiguous/unfinished and require a future independently labelled head.
    """
    patterns = {"amount": r"\b(?:\d+(?:[.,]\d+)?|hundred|thousand|dollars?|pounds?|euros?)\b",
                "date": r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today|\d{4}-\d{2}-\d{2})\b",
                "security": r"\b(?:pin|password|birth|security|identity)\b"}
    guard = uncertainty_guard(text)
    polarity = "negated" if guard and guard[0] == "negated" else "conditional" if guard and guard[2] == "conditional_uncertainty" else "question" if "?" in text else "asserted"
    result = {}
    for component, pattern in patterns.items():
        spans = [{"start": m.start(), "end": m.end()} for m in re.finditer(pattern, text, re.I)]
        result[component] = {"status": "unfinished" if spans and guard and guard[0] == "unfinished" else "ambiguous" if spans else "absent",
                             "polarity": polarity if spans else "unassessed", "evidence_spans": spans,
                             "target": None, "method": "conservative_lexical_observation_v0"}
    return result


def predict(input_snapshot, model_bundle):
    """Research-only bound semantic proposal; never authorizes side effects."""
    required = ("utterance", "turn_id", "state_revision", "policy_hash", "raw_text_provenance")
    if any(k not in input_snapshot for k in required):
        raise ValueError("Snapshot requires utterance/turn_id/state_revision/policy_hash/raw_text_provenance")
    text = input_snapshot["utterance"]
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError("Utterance must be text of at most 4096 characters")
    if not isinstance(input_snapshot["turn_id"], str) or not input_snapshot["turn_id"]:
        raise ValueError("Nonempty turn_id required")
    if type(input_snapshot["state_revision"]) is not int or input_snapshot["state_revision"] < 0:
        raise ValueError("Nonnegative integer state_revision required")
    if not re.fullmatch(r"[0-9a-f]{64}", input_snapshot["policy_hash"]):
        raise ValueError("policy_hash must be lowercase SHA256")
    if model_bundle.get("format") != FORMAT:
        raise ValueError("Unsupported model format")
    candidate, confidence = score(model_bundle, text)
    reasons = []
    if not model_bundle.get("calibration", {}).get("fitted", False):
        reasons.append("uncalibrated_bundle")
    if input_snapshot["raw_text_provenance"] != "verified_local_synthetic_fixture":
        reasons.append("trusted_latest_raw_turn_adapter_unverified")
    guard = uncertainty_guard(text)
    if guard:
        candidate = {"primaryintent": "unknown", "secondaryintent": "none", "completion": guard[0], "unresolvedcomponent": guard[1]}
        reasons.append(guard[2])
    if candidate["completion"] != "complete" or candidate["unresolvedcomponent"] != "none" or candidate["primaryintent"] == "unknown":
        reasons.append("learned_or_guarded_uncertainty")
    vocabulary = model_bundle.get("word_vocabulary", [])
    content = words(text)
    known_fraction = sum(t in vocabulary for t in content) / max(len(content), 1)
    if known_fraction < 0.6:
        reasons.append("out_of_vocabulary_input")
    joint_confidence = min(v["max_score"] for v in confidence.values())
    if joint_confidence < model_bundle.get("calibration", {}).get("threshold", 1.1):
        reasons.append("below_calibration_threshold")
    if confidence["primaryintent"]["margin"] < 0.12:
        reasons.append("small_primary_margin")
    components = component_observations(text)
    if any(v["status"] != "absent" for v in components.values()):
        reasons.append("unresolved_value_component")
    return {"schema_version": 1, "authority": "semantic_proposal_only", "research_only": True,
            "turn_id": input_snapshot["turn_id"], "state_revision": input_snapshot["state_revision"],
            "policy_hash": input_snapshot["policy_hash"], "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "candidate": candidate, "confidence": {"heads": confidence, "joint_score": joint_confidence,
                                                        "known_word_fraction": known_fraction,
                                                        "interpretation": "temperature-scaled score; not correctness probability"},
            "abstain": bool(reasons), "reasons": sorted(set(reasons)),
            "clauses": [{"target": None, "target_status": "unresolved", "evidence_span": {"start": 0, "end": len(text)},
                         "components": components}],
            "corrections": [{"target": None, "components": [], "status": "unresolved"}] if guard and guard[0] == "correction" else [],
            "consent_signal": "unassessed"}


def local_snapshot(text, record_id="offline-smoke", revision=0):
    return {"utterance": text, "turn_id": record_id, "state_revision": revision,
            "policy_hash": hashlib.sha256(b"fictional-local-policy-no-values-v1").hexdigest(),
            "raw_text_provenance": "verified_local_synthetic_fixture"}
