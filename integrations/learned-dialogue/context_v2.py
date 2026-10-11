"""Context-aware semantic proposal v2. Pure json/re/builtins implementation.

Current v2 is diagnostic: every head is unqualified, every output abstains.
No text digest, canonical value, policy authority or action is emitted.
"""
import re

FORMAT_V2 = "context-sparse-diagnostic-v2"
COMPONENTS = ("amount", "date", "time", "security_answer", "recipient", "allocation")
INPUT_KEYS = ("schema_version", "call_local_id", "turn_id", "state_revision", "policy_hash", "api_hash",
              "utterance", "phase", "question", "targets", "pending", "spoken_offers", "active_readback")
INTENTS_V2 = ("recipient_self", "third_party", "wrong_number", "deceased", "security_answer", "security_decline",
              "payment_proposal", "offer_acceptance", "readback_affirmation", "payment_refusal", "amount_too_high",
              "current_arrears_paid_claim", "historical_closed_or_paid_off_claim", "debt_dispute", "hardship",
              "restructuring_request", "human_request", "stop_request", "callback_proposal", "support_acceptance",
              "support_decline", "ai_question", "purpose_question", "legitimacy_question", "discount_question",
              "information_question", "correction", "other", "unknown")
ADMIN_LABELS = ("ai_question", "purpose_question", "legitimacy_question", "discount_question", "human_request")


class InputRejected(ValueError):
    """No trustworthy binding context exists; no proposal can be fabricated."""


class ProposalOverflow(ValueError):
    pass


class BindingContext:
    """Caller-owned current kernel binding; construction is not authentication.

    A separately verified adapter must supply this from authoritative state.
    Offline fixtures/replays can supply it for diagnostic execution only.
    """
    __slots__ = ("_values", "_model_id")

    def __init__(self, binding, model_id):
        if not isinstance(binding, dict) or set(binding) != {"turn_id", "state_revision", "policy_hash", "api_hash"}:
            raise InputRejected("Complete authoritative binding required")
        if not isinstance(binding["turn_id"], str) or not 1 <= len(binding["turn_id"]) <= 128:
            raise InputRejected("Valid turn ID required")
        if type(binding["state_revision"]) is not int or binding["state_revision"] < 0:
            raise InputRejected("Valid state revision required")
        if any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
               for value in (binding["policy_hash"], binding["api_hash"], model_id)):
            raise InputRejected("Real policy/API/model SHA256 bindings required")
        object.__setattr__(self, "_values", tuple(binding[key] for key in ("turn_id", "state_revision", "policy_hash", "api_hash")))
        object.__setattr__(self, "_model_id", model_id)

    def __setattr__(self, key, value):
        raise InputRejected("BindingContext is immutable")

    @property
    def model_id(self):
        return self._model_id

    def binding(self):
        return dict(zip(("turn_id", "state_revision", "policy_hash", "api_hash"), self._values))


def tokens_v2(text):
    # Number tokens delexicalized before intent fitting; offsets use raw text.
    return ["<number>" if m.group().isdigit() else m.group().lower() for m in
            re.finditer(r"[A-Za-z]+(?:['\u2019][A-Za-z]+)?|\d+", text)]


def _counts(items):
    result = dict()
    for item in items:
        result[item] = result.get(item, 0) + 1
    return result


def feature_v2(snapshot, candidate=None, include_context=True):
    """Feature allowlist; never includes labels, IDs, hashes or canonical facts."""
    text = snapshot["utterance"]["text"]
    token = tokens_v2(text)
    f = _counts("w:" + t for t in token)
    for a, b in zip(token, token[1:]):
        key = "b:" + a + "/" + b
        f[key] = f.get(key, 0) + 1
    padded = "^" + " ".join(token) + "$"
    for i in range(len(padded) - 2):
        key = "c:" + padded[i:i + 3]
        f[key] = f.get(key, 0) + 1
    if include_context:
        context = ["phase=" + snapshot["phase"], "question=" + snapshot["question"]["role"],
                   "security_field=" + str(snapshot["question"].get("security_field", "none")),
                   "target_count=" + str(min(len(snapshot["targets"]), 3)),
                   "has_offer=" + str(bool(snapshot["spoken_offers"])),
                   "has_readback=" + str(bool(snapshot["active_readback"]))]
        for item in context:
            f["ctx:" + item] = 3.0
            for word in token[:16]:
                f["cross:" + item + "/" + word] = 1.0
        requested_indices = snapshot["question"].get("target_indices", [])
        if len(requested_indices) == 1:
            matched = [item for item in snapshot["pending"] if item.get("target_index") == requested_indices[0]]
            f["pending:current_target_count=" + str(len(matched))] = 1.0
            for component in COMPONENTS:
                for item in matched:
                    status = item.get("components", {}).get(component, {}).get("status", "unobserved")
                    f["pending:current:" + component + "=" + str(status)] = 1.0
        else:
            f["pending:current_target=unresolved"] = 1.0
    if candidate:
        start, end = candidate["start"], candidate["end"]
        for item in ("component=" + candidate["name"], "surface=" + " ".join(tokens_v2(text[start:end])),
                     "suffix=" + " ".join(tokens_v2(text[start:end]))[-4:], "tail=" + str(end == len(text)),
                     "fragment=" + str(text[start:end].rstrip().endswith(("...", "\u2026", "-")))):
            f["span:" + item] = 3.0
        prefix = text[max(0, start - 32):start].lower()
        for word in tokens_v2(prefix):
            f["left:" + word] = 1.0
    norm = sum(v * v for v in f.values()) ** .5 or 1.0
    return dict((key, value / norm) for key, value in f.items())


def distribution_v2(head, feature):
    logits = [bias + sum(weight.get(key, 0.0) * value for key, value in feature.items())
              for bias, weight in zip(head["bias"], head["weights"])]
    if not logits or len(logits) != len(head["labels"]) or any(not -float("inf") < value < float("inf") for value in logits):
        raise ValueError("Malformed or nonfinite linear head")
    top = max(logits)
    exp = [2.718281828459045 ** (value - top) for value in logits]
    denom = sum(exp)
    return dict(zip(head["labels"], [value / denom for value in exp]))


def binary_score_v2(head, feature):
    logit = head["bias"] + sum(head["weights"].get(key, 0.0) * value for key, value in feature.items())
    if not -float("inf") < logit < float("inf"):
        raise ValueError("Nonfinite binary head")
    return 1.0 / (1.0 + 2.718281828459045 ** (-max(-50, min(50, logit))))


def candidate_spans_v2(snapshot, include_context=True):
    """Bounded lexical span proposals, not gold or complete value parsing."""
    text = snapshot["utterance"]["text"]
    patterns = {"amount": r"\b(?:\d+(?:[.,]\d+)?|(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|hundred|thousand)(?:\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|hundred|thousand|and))*)\b",
                "date": r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|tomorrow|today|next week|Fri\.\.\.|Mon\.\.\.|\d{4}-\d{2}-\d{2})",
                "time": r"\b\d{1,2}:\d{2}\b"}
    question_role = snapshot["question"]["role"]
    if include_context and question_role == "security":
        patterns = {"security_answer": r"\S(?:.*\S)?"}
    candidates = []
    for name, pattern in patterns.items():
        for match in re.finditer(pattern, text, re.I):
            end = match.end()
            if name == "amount" and match.group().lower().endswith(" and") and re.match(r"\s+(?:the\s+)?(?:date|time|security)\b", text[end:], re.I):
                end -= 4
            candidates.append({"name": name, "start": match.start(), "end": end})
    if len(candidates) > 16:
        raise ProposalOverflow("More than 16 span candidates; no silent truncation")
    return candidates


def qualifiers_v2(snapshot):
    """Evidence channels remain separate from learned intent/completeness."""
    text = snapshot["utterance"]["text"]
    patterns = {"correction": r"\b(?:actually|I meant|I mean|no wait|revise|correct)\b",
                "negation": r"\b(?:not|never|cannot|can't|don't|won't|no)\b",
                "qualifier": r"\b(?:if|maybe|perhaps|provided|but)\b"}
    spans = []
    for role, pattern in patterns.items():
        for match in re.finditer(pattern, text, re.I):
            spans.append({"turn_id": snapshot["turn_id"], "start": match.start(), "end": match.end(), "role": role})
    if len(spans) > 16:
        raise ProposalOverflow("More than 16 qualifier spans; no silent truncation")
    return sorted(spans, key=lambda span: (span["start"], span["end"]))


def binding_v2(snapshot):
    return {key: snapshot[key] for key in ("turn_id", "state_revision", "policy_hash", "api_hash")}


def _reason(reason, clause_id=None, components=None):
    return {"reason": reason, "clause_id": clause_id, "target_indices": [], "components": components or []}


def neutral_v2(binding_context, reason):
    return {"schema_version": "semantic_proposal.v1", "binding": binding_context.binding(), "model_id": binding_context.model_id,
            "status": "abstain", "primary": None, "secondary": [], "clauses": [], "corrections": [],
            "consent_signal": {"kind": "ambiguous", "evidence": [], "candidate_readback_id": None,
                               "has_new_terms": "unknown", "decision": "descriptive_only"},
            "ood": {"decision": "unassessed", "known_feature_fraction": None, "nearest_train_similarity": None,
                    "margin": None, "reasons": [reason]}, "abstentions": [_reason(reason)]}


def _check_snapshot(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != set(INPUT_KEYS) or snapshot["schema_version"] != "semantic_input.v1":
        return "unknown_schema"
    if type(snapshot["state_revision"]) is not int or snapshot["state_revision"] < 0:
        return "stale_binding"
    for key in ("policy_hash", "api_hash"):
        if not isinstance(snapshot[key], str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot[key]):
            return "stale_binding"
    if not isinstance(snapshot["turn_id"], str) or not 1 <= len(snapshot["turn_id"]) <= 128:
        return "stale_binding"
    utterance = snapshot["utterance"]
    if not isinstance(utterance, dict) or set(utterance) != {"text", "source", "source_turn_id", "complete_transport", "offset_unit"}:
        return "missing_input"
    if not isinstance(utterance["text"], str):
        return "missing_input"
    if len(utterance["text"]) > 4096:
        return "size_limit"
    if not utterance["text"].strip():
        return "missing_input"
    if utterance["source"] not in {"trusted_turn", "authored_fixture"}:
        return "untrusted_text"
    if utterance["source_turn_id"] != snapshot["turn_id"]:
        return "stale_binding"
    if utterance["complete_transport"] is not True:
        return "transport_truncated"
    if utterance["offset_unit"] != "python_unicode_codepoints":
        return "invalid_span"
    if not isinstance(snapshot["phase"], str) or not isinstance(snapshot["question"], dict) or not isinstance(snapshot["question"].get("role"), str):
        return "missing_input"
    if any(not isinstance(snapshot[key], list) or len(snapshot[key]) > 16 for key in ("targets", "pending", "spoken_offers")):
        return "size_limit"
    if any(not isinstance(item, dict) for key in ("targets", "pending", "spoken_offers") for item in snapshot[key]):
        return "missing_input"
    offer_ids = [item.get("offer_id") for item in snapshot["spoken_offers"]]
    if any(not isinstance(v, str) for v in offer_ids) or len(set(offer_ids)) != len(offer_ids):
        return "unresolved_reference"
    return None


def _predict_v2(input_snapshot, model_bundle, binding_context=None):
    """Descriptive, schema-aligned diagnostic; unsupported heads fail closed.

    Binding/model hashes are supplied by the trusted offline loader/wrapper.
    This does not authenticate a caller or create a Freya trusted-turn adapter.
    """
    if not isinstance(binding_context, BindingContext):
        raise InputRejected("Caller-owned authoritative BindingContext is required")
    reason = _check_snapshot(input_snapshot)
    if reason:
        return neutral_v2(binding_context, reason)
    if binding_v2(input_snapshot) != binding_context.binding() or model_bundle.get("model_id") != binding_context.model_id:
        return neutral_v2(binding_context, "stale_binding")
    model = model_bundle["model"]
    if model.get("format") != FORMAT_V2:
        return neutral_v2(binding_context, "unknown_schema")
    if not model.get("qualification", {}).get("primary", {}).get("trained", False):
        return neutral_v2(binding_context, "untrained_head")
    text = input_snapshot["utterance"]["text"]
    vector = feature_v2(input_snapshot, include_context=model.get("include_context", True))
    if len(vector) > 4096:
        return neutral_v2(binding_context, "size_limit")
    probs = distribution_v2(model["heads"]["primary"], vector)
    label = max(probs, key=lambda key: (probs[key], key))
    evidence = [{"turn_id": input_snapshot["turn_id"], "start": 0, "end": len(text), "role": "intent"}]
    def decision(score, trained=True):
        return {"score": score, "calibrated_probability": None, "calibration_id": None,
                "decision": "abstain", "abstain_reason": "uncalibrated" if trained else "untrained_head"}
    primary = dict(decision(probs[label]), label=label, evidence=evidence)
    secondary = []
    for secondary_label, head in sorted(model["secondary"].items()) if model["qualification"].get("secondary", {}).get("trained") else []:
        score = binary_score_v2(head, vector)
        if score >= .5 and secondary_label not in {label, "unknown"}:
            secondary.append(dict(decision(score), label=secondary_label, evidence=evidence))
    if len(secondary) > 16:
        return neutral_v2(binding_context, "size_limit")
    try:
        qualifiers = qualifiers_v2(input_snapshot)
        candidates = candidate_spans_v2(input_snapshot, model.get("include_context", True))
    except ProposalOverflow:
        return neutral_v2(binding_context, "size_limit")
    component_rows = []
    for candidate in candidates:
        span_vector = feature_v2(input_snapshot, candidate, model.get("include_context", True))
        completion_trained = model["qualification"].get("component_completion", {}).get("trained", False)
        polarity_trained = model["qualification"].get("component_polarity", {}).get("trained", False)
        support = model.get("component_support", {}).get(candidate["name"])
        if support is not None:
            completion_trained = completion_trained and support.get("component_completion", {}).get("observed_samples", 0) > 0
            polarity_trained = polarity_trained and support.get("component_polarity", {}).get("observed_samples", 0) > 0
        completion_scores = distribution_v2(model["heads"]["component_completion"], span_vector) if completion_trained else {"ambiguous": 0.0}
        polarity_scores = distribution_v2(model["heads"]["component_polarity"], span_vector) if polarity_trained else {"unknown": 0.0}
        # Heads are trained on weak authored span labels, but not qualified.
        component_rows.append({"name": candidate["name"], "completion": max(completion_scores, key=completion_scores.get),
                               "polarity": max(polarity_scores, key=polarity_scores.get),
                               "evidence": [{"turn_id": input_snapshot["turn_id"], "start": candidate["start"], "end": candidate["end"], "role": "value"}],
                               "reference": None, "confidence": decision(0.0, trained=completion_trained and polarity_trained)})
    # At most one candidate per name can fit the contract until clause/target heads exist.
    counts = dict()
    for component in component_rows:
        counts[component["name"]] = counts.get(component["name"], 0) + 1
    components = [component for component in component_rows if counts[component["name"]] == 1]
    for name in COMPONENTS:
        if counts.get(name, 0) != 1:
            unresolved_evidence = [span for item in component_rows if item["name"] == name for span in item["evidence"]]
            components.append({"name": name, "completion": "ambiguous", "polarity": "unknown", "evidence": unresolved_evidence,
                               "reference": None, "confidence": decision(0.0, trained=False)})
    clause_id = input_snapshot["turn_id"] + ":c0"
    reference, readback_reference, references_reason = reference_candidate_v2(input_snapshot, label, model.get("include_context", True))
    clauses = [{"clause_id": clause_id, "intent": primary, "scope": "unresolved", "target_refs": [],
                "collective_id": None, "amount_scope": "unresolved" if any(c["name"] == "amount" for c in components) else "absent",
                "components": components, "qualifiers": qualifiers, "offer_reference": reference}]
    correction_evidence = [s for s in qualifiers if s["role"] == "correction"]
    corrections = [{"target_refs": [], "components": ["unknown"], "evidence": correction_evidence,
                    "supersedes": None, "status": "candidate"}] if correction_evidence else []
    abstentions = [_reason("uncalibrated"), _reason("untrained_head", clause_id, ["recipient", "allocation"]), _reason("unknown_target", clause_id)]
    if references_reason:
        abstentions.append(_reason(references_reason, clause_id))
    if correction_evidence:
        abstentions.append(_reason("unknown_correction_scope", clause_id))
    if any(value > 1 for value in counts.values()):
        abstentions.append(_reason("inconsistent_heads", clause_id))
    # Consent head absent: retain ambiguity, never convert predicted affirmation to consent.
    consent = {"kind": "ambiguous", "evidence": [], "candidate_readback_id": readback_reference,
               "has_new_terms": "unknown", "decision": "descriptive_only"}
    return {"schema_version": "semantic_proposal.v1", "binding": binding_v2(input_snapshot), "model_id": model_bundle["model_id"],
            "status": "abstain", "primary": primary, "secondary": secondary, "clauses": clauses,
            "corrections": corrections, "consent_signal": consent,
            "ood": {"decision": "unassessed", "known_feature_fraction": sum(key in model["vocabulary"] for key in vector) / max(1, len(vector)),
                    "nearest_train_similarity": None, "margin": sorted(probs.values(), reverse=True)[0] - sorted(probs.values(), reverse=True)[1],
                    "reasons": ["uncalibrated"]}, "abstentions": abstentions}


def predict_v2(input_snapshot, model_bundle, binding_context=None):
    if not isinstance(binding_context, BindingContext):
        raise InputRejected("Caller-owned authoritative BindingContext is required")
    try:
        return _predict_v2(input_snapshot, model_bundle, binding_context)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, OverflowError):
        return neutral_v2(binding_context, "runtime_failure")


def reference_candidate_v2(snapshot, predicted_label, include_context=True):
    """Exact immutable ID from an actually spoken context reference, no terms."""
    if not include_context:
        return None, None, "unresolved_reference" if predicted_label in {"offer_acceptance", "readback_affirmation"} else None
    if predicted_label == "readback_affirmation":
        readback = snapshot["active_readback"]
        if not isinstance(readback, dict) or not isinstance(readback.get("readback_id"), str) or readback.get("valid") is not True or readback.get("completed_speech") is not True:
            return None, None, "unresolved_reference"
        if readback.get("state_revision") != snapshot["state_revision"]:
            return None, None, "stale_binding"
        return None, readback["readback_id"], None
    reference = snapshot["question"].get("spoken_offer_id")
    if predicted_label != "offer_acceptance" or reference is None:
        return None, None, "unresolved_reference" if predicted_label == "offer_acceptance" else None
    matches = [offer for offer in snapshot["spoken_offers"] if offer["offer_id"] == reference]
    if len(matches) != 1 or matches[0].get("superseded") is not False or matches[0].get("spoken_turn_id") is None:
        return None, None, "unresolved_reference"
    if matches[0].get("state_revision", 0) > snapshot["state_revision"]:
        return None, None, "stale_binding"
    return reference, None, None


def check_deferred_refusal_v2(authoritative_pending, event):
    """Pure revision check; returns diagnosis only, never changes bank/pending state."""
    if not isinstance(event, dict) or type(event.get("target_index")) is not int or type(event.get("component_revision")) is not int or not isinstance(event.get("offer_id"), str):
        return {"eligible_for_kernel_review": False, "reason": "malformed_revision_event"}
    target = event.get("target_index")
    current = next((p for p in authoritative_pending if p.get("target_index") == target), None)
    if current is None:
        return {"eligible_for_kernel_review": False, "reason": "unknown_target"}
    if type(current.get("component_revision")) is not int or not isinstance(current.get("spoken_offer_id"), str):
        return {"eligible_for_kernel_review": False, "reason": "missing_authoritative_revision"}
    if event.get("component_revision") != current.get("component_revision"):
        return {"eligible_for_kernel_review": False, "reason": "superseded_component_revision"}
    if event.get("offer_id") != current.get("spoken_offer_id"):
        return {"eligible_for_kernel_review": False, "reason": "superseded_offer_reference"}
    return {"eligible_for_kernel_review": True, "reason": "matching_revision_requires_external_policy"}
