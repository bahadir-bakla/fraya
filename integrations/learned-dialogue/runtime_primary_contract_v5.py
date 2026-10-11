import json
import re
VERSION='primary_sparse.v5.0.cap1024.epochs80.groupmean'

def replay_surface_admission(snapshot):
    """Immutable authored replay eligibility; never authenticates live ingress."""
    u, q = snapshot.get("utterance", {}), snapshot.get("question", {})
    sensitive = (snapshot.get("phase") == "security" or q.get("role") == "security"
                 or q.get("security_field") is not None
                 or bool(re.search(r"\b(?:password|passcode|security code|social security|cvv|pin code)\b",
                                   u.get("text", ""), re.I)))
    source = (isinstance(u.get("text"), str) and u.get("complete_transport") is True
              and u.get("offset_unit") == "python_unicode_codepoints"
              and u.get("source_turn_id") == snapshot.get("turn_id"))
    return {"verified_current_source": source, "framing_complete": source,
            "nonsecurity_value_free": not sensitive, "has_unisolated_secret": sensitive,
            "question_role_verified": source, "binding_scope": "pinned authored offline replay only"}

def features(snapshot, mode="context_text"):
    """Exactly the same feature contract in table, training and pure scoring."""
    a = replay_surface_admission(snapshot)
    if not a["verified_current_source"] or not a["nonsecurity_value_free"] or not a["framing_complete"]:
        return {"eligible": False, "reason": "source_or_privacy_mask", "features": {}}
    text = snapshot["utterance"]["text"]
    if len(text) > 512:
        return {"eligible": False, "reason": "whole_primary_scope_exceeds_512", "features": {}}
    values = {}
    if mode not in ("context_only", "constant"):
        if mode == "fragment_only":
            text = text[-48:]
        words = re.findall(r"[a-z]+(?:['’][a-z]+)?|<number>|\.{3}|…", re.sub(r"\d+", "<number>", text.lower()))
        for w in words:
            values["w:" + w] = 1.
        for x, y in zip(words, words[1:]):
            values["b:" + x + "_" + y] = 1.
        normalized = " ".join(words)
        for n in (3, 4):
            for i in range(min(512, max(0, len(normalized) - n + 1))):
                values["c" + str(n) + ":" + normalized[i:i+n]] = 1.
    if mode not in ("text_only", "fragment_only", "constant"):
        for key, value in (("phase", snapshot.get("phase")), ("question", snapshot.get("question", {}).get("role"))):
            if value in {"payment", "callback", "readback", "recipient", "support", "date", "amount", "offer", "none"}:
                values["context:" + key + "=" + value] = 1.
        # Target identities/revisions and canonical values are deliberately absent.
        pending = snapshot.get("pending", [])
        for ordinal, target in enumerate(snapshot.get("question", {}).get("target_indices", [])):
            entry = next((p for p in pending if p.get("target_index") == target), {})
            for kind in ("amount", "date"):
                state = entry.get("components", {}).get(kind, {}).get("status")
                if state in {"absent", "complete", "unfinished", "ambiguous"}:
                    values[f"context:question_target_slot{ordinal}:{kind}={state}"] = 1.
    norm = sum(v*v for v in values.values()) ** .5 or 1.
    return {"eligible": True, "reason": None, "features": {k:v/norm for k,v in values.items()}}

def sigmoid(z):
    return 1 / (1 + 2.718281828459045 ** (-max(-40., min(40., z))))

def predict(snapshot, bundle):
    if bundle.get("schema_version") != VERSION:
        raise ValueError("feature_version_mismatch")
    f = features(snapshot, bundle["mode"])
    if not f["eligible"]:
        return {"raw_score": None, "probability_uncalibrated": None, "decision": "abstain", "qualified": False}
    z = bundle["bias"] + sum(v*f["features"].get(k, 0.) for k,v in bundle["weights"].items())
    if not -float('inf') < z < float('inf'):
        raise ValueError("nonfinite_bundle")
    return {"raw_score": z, "probability_uncalibrated": sigmoid(z), "binary_diagnostic": int(z >= 0),
            "decision": "abstain", "qualified": False}
