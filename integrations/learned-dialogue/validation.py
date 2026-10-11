"""Caller-side proposal validation only; no state reducer or permission grant."""
import math
import hashlib
from inference import HEADS, LABELS

OUTPUT_KEYS = {"schema_version", "authority", "research_only", "turn_id", "state_revision", "policy_hash",
               "input_sha256", "candidate", "confidence", "abstain", "reasons", "clauses", "corrections", "consent_signal"}
FORBIDDEN = {"permission", "authorized", "verified", "recorded", "tools", "tool", "action", "route", "outcome",
             "canonical_amount", "canonical_date", "api_request", "policy_amount", "bank_response"}


def validate_proposal(proposal, current_snapshot):
    if set(proposal) != OUTPUT_KEYS:
        raise ValueError("Unexpected/missing proposal fields")
    if proposal["authority"] != "semantic_proposal_only" or proposal["research_only"] is not True or proposal["schema_version"] != 1:
        raise ValueError("Unexpected authority/schema")
    for key in ("turn_id", "state_revision", "policy_hash"):
        if proposal[key] != current_snapshot[key]:
            raise ValueError("Stale or cross-policy binding: " + key)
    if proposal["input_sha256"] != hashlib.sha256(current_snapshot["utterance"].encode()).hexdigest():
        raise ValueError("Text provenance hash mismatch")
    if set(proposal["candidate"]) != set(HEADS):
        raise ValueError("Invalid candidate fields")
    for head in HEADS:
        if proposal["candidate"][head] not in LABELS[head]:
            raise ValueError("Unknown candidate label")
    if type(proposal["abstain"]) is not bool or proposal["consent_signal"] != "unassessed":
        raise ValueError("Invalid decision/consent")
    def visit(value):
        if isinstance(value, dict):
            if FORBIDDEN.intersection(value):
                raise ValueError("Forbidden authority/action fields")
            if "start" in value or "end" in value:
                if set(value) != {"start", "end"} or type(value["start"]) is not int or type(value["end"]) is not int or not 0 <= value["start"] <= value["end"] <= len(current_snapshot["utterance"]):
                    raise ValueError("Invalid evidence span")
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Nonfinite proposal value")
    visit(proposal)
    return True
