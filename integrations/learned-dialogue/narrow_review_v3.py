"""Label-free TRAIN review packet and fail-closed binary annotation admission.

Local provenance checks do not authenticate reviewers or prove semantic truth.
The parent must independently verify the reviewer roster/blinding and bind its
authorization to exact packet/review bytes before the gated trainer may run.
"""
import hashlib
import json
import random
from collections import Counter

from build_data import encoded, freeze
from train_v2 import HERE, ROOT, observed, strict_json

TASK = "primary_is_payment_proposal"
SEMANTICS = "Positive means primary act payment_proposal. Negative means another primary act; never no payment, no secondary payment, refusal, invalidity, or permission. Ambiguous primary is masked."


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def plan_packet(records, seed=303):
    groups = {}
    for row in records:
        if row["split"] != "train":
            raise ValueError("Review packet accepts TRAIN only")
        groups.setdefault(row["lineage_group_id"], []).append(row)
    positive, negative = set(), set()
    for group, rows in groups.items():
        for row in rows:
            label, mask = observed(row["labels"], "primary_intent")
            if mask:
                (positive if label == "payment_proposal" else negative).add(group)
    rng = random.Random(seed)
    positives = sorted(positive)
    rng.shuffle(positives)
    selected_positive = set(positives[:20])
    eligible_negative = negative - positive
    order = sorted(eligible_negative)
    rng.shuffle(order)
    strata = {
        "refusal": {"payment_refusal"}, "correction": {"correction"},
        "historical_paid": {"historical_closed_or_paid_off_claim"},
        "question": {"information_question", "purpose_question", "discount_question", "legitimacy_question", "ai_question"},
        "support": {"support_acceptance", "support_decline"}, "stop": {"stop_request"},
        "hardship": {"hardship"}, "ordinary": {"recipient_self", "third_party", "other", "human_request"}}
    selected_negative, coverage = set(), {}
    for name, labels in strata.items():
        candidates = [group for group in order if any(row["labels"].get("primary_intent") in labels for row in groups[group])]
        coverage[name] = candidates[0] if candidates else None
        if candidates:
            selected_negative.add(candidates[0])
    for polarity in ("conditional", "quoted"):
        candidates = [group for group in order if any(any(p.get("value") == polarity for p in row["labels"].get("clause_polarity", []))
                      or any(c["polarity"] == polarity for clause in row["labels"].get("frame", {}).get("clauses", []) for c in clause["components"])
                      for row in groups[group])]
        coverage[polarity] = candidates[0] if candidates else None
        if candidates:
            selected_negative.add(candidates[0])
    for group in order:
        if len(selected_negative) >= 20:
            break
        selected_negative.add(group)
    if len(selected_positive) != 20 or len(selected_negative) != 20:
        raise ValueError("Weak strata cannot supply 20 positive and 20 additional negative groups")
    selected = sorted(selected_positive | selected_negative)
    # Remove labels, annotation rationales, predictions, verdicts and weak stratum.
    members = [{"example_id": row["example_id"], "lineage_group_id": group, "input": row["input"]}
               for group in selected for row in groups[group]]
    rng.shuffle(members)
    packet = {"schema_version": "narrow_binary_review_packet.v1", "task": TASK,
              "label_semantics": SEMANTICS, "allowed_use": "Blind TRAIN annotation only; no qualification",
              "selected_lineage_groups": selected, "records": members,
              "optional_annotation_only_axes": {"act_completion": ["complete", "unfinished", "ambiguous"],
                                                "act_commitment": "Scope of commitment to the labelled act, distinct from embedded predicate polarity",
                                                "predicate_scope": "Source spans and person/question referent; do not infer from phase label alone",
                                                "primary_and_secondary_clause_metadata": True,
                                                "missing_axis_masked": True,
                                                "binary_positive_does_not_imply_completed_act": True,
                                                "wire_change_authorized": False},
              "review_instructions": ["Annotate every supplied group member from legitimate source context only.",
                                      "Do not inspect sampling-admin.json, original author labels, model outputs or development/qualification data.",
                                      "Return positive/negative/ambiguous and preserve disagreements; current wire and deterministic authority remain unchanged.",
                                      "Act completion is independent of amount/date completion. Complete hardship plus unfinished payment retains hardship; unfinished hardship/deceased cannot imply actionable kernel precedence.",
                                      "Recipient name-only/phase-conditioned acknowledgement can be descriptive, never verified identity or financial consent."]}
    admin = {"seed": seed, "sampling_basis": "Predeclared weak-author primary strata; no model-correctness selection",
             "positive_weak_groups": sorted(selected_positive), "additional_negative_weak_groups": sorted(selected_negative),
             "negative_stratum_coverage": coverage, "missing_negative_strata": sorted(k for k,v in coverage.items() if v is None),
             "weak_positive_groups_available": len(positive), "weak_negative_groups_available": len(negative),
             "overlapping_class_group_count": len(positive & negative), "distinct_selected_groups": len(selected),
             "reviewer_visible": False, "annotation_gate_passed": False, "independently_reviewed_groups": 0}
    return packet, admin


def assess_reviews(packet, reviews, authorization=None):
    reasons, eligible = [], []
    members = {row["example_id"]: row for row in packet["records"]}
    if reviews is None:
        return {"admitted": False, "reasons": ["independent_annotations_missing"], "eligible_rows": [],
                "positive_groups": 0, "negative_groups": 0, "additional_negative_groups": 0}
    if reviews.get("task") != TASK or reviews.get("packet_sha256") != sha(encoded(packet)):
        reasons.append("review_task_or_packet_binding_mismatch")
    registry = (authorization or {}).get("reviewer_registry", {})
    if not authorization or authorization.get("parent_verified_blind_independence") is not True:
        reasons.append("parent_verified_reviewer_independence_missing")
    if authorization and (authorization.get("packet_sha256") != sha(encoded(packet)) or authorization.get("reviews_sha256") != sha(encoded(reviews))):
        reasons.append("parent_authorization_hash_binding_mismatch")
    rows = reviews.get("records", [])
    ids = [row.get("example_id") for row in rows]
    if len(set(ids)) != len(ids) or set(ids) != set(members):
        reasons.append("all_selected_members_exactly_once_required")
    for row in rows:
        if row.get("example_id") not in members:
            continue
        annotations = row.get("annotations", [])
        reviewers = [item.get("reviewer_id") for item in annotations]
        if len(annotations) != 2 or len(set(reviewers)) != 2:
            reasons.append("two_distinct_blind_annotations_required")
            continue
        if any(item.get("label") not in ("positive", "negative", "ambiguous") for item in annotations):
            reasons.append("unknown_annotation_label")
            continue
        if any(registry.get(name, {}).get("verified_independent_blind") is not True or registry.get(name, {}).get("is_original_author") is not False for name in reviewers):
            reasons.append("unverified_or_original_author_reviewer")
        adjudication = row.get("adjudication", {})
        final = adjudication.get("label")
        if final not in {"positive", "negative", "ambiguous"} or adjudication.get("status") != "adjudicated":
            reasons.append("final_adjudication_missing")
            continue
        agreed = annotations[0]["label"] == annotations[1]["label"]
        if agreed and final != annotations[0]["label"]:
            reasons.append("adjudication_changed_agreement_without_dispute")
        if not agreed:
            judge = adjudication.get("adjudicator_id")
            if judge in reviewers or registry.get(judge, {}).get("verified_independent_blind") is not True or registry.get(judge, {}).get("is_original_author") is not False:
                reasons.append("independent_conflict_adjudicator_required")
        if final != "ambiguous":
            member = members[row["example_id"]]
            eligible.append({"id": member["example_id"], "group": member["lineage_group_id"], "snapshot": member["input"], "y": int(final == "positive")})
    positive = {row["group"] for row in eligible if row["y"] == 1}
    negative = {row["group"] for row in eligible if row["y"] == 0}
    if len(positive) < 20 or len(negative - positive) < 20:
        reasons.append("adjudicated_binary_group_floor_unmet")
    return {"admitted": not reasons, "reasons": sorted(set(reasons)), "eligible_rows": eligible if not reasons else [],
            "positive_groups": len(positive), "negative_groups": len(negative), "additional_negative_groups": len(negative - positive),
            "ambiguous_masked_rows": sum(r.get("adjudication", {}).get("label") == "ambiguous" for r in rows),
            "iid_or_semantic_truth_proven": False, "gpu_authorized": False}


def main():
    raw = (HERE / "v2-final-data/train.json").read_bytes()
    packet, admin = plan_packet(strict_json(raw)["records"])
    packet["source_train_sha256"] = sha(raw)
    packet_bytes = encoded(packet)
    admin["packet_sha256"] = sha(packet_bytes)
    admin["source_train_sha256"] = sha(raw)
    folder = HERE / "narrow-v3"
    folder.mkdir(exist_ok=True)
    freeze(folder / "review-packet.json", packet_bytes)
    freeze(folder / "sampling-admin.json", encoded(admin))
    design_bytes = (ROOT / "analysis/learned-layer-design.json").read_bytes()
    design = strict_json(design_bytes)
    contract = {"designer_source_sha256": sha(design_bytes), "document_version": design["document_version"],
                "atomic_turn_semantics_v2": design["atomic_turn_semantics_v2"], "narrow_head_experiment": design["narrow_head_experiment"],
                "implementation_boundary": "Atomic rules constrain the independent deterministic consumer; this scaffold emits no state patch or authority and does not implement unsupported graph relations in frozen wire."}
    freeze(folder / "checkpoint03-contract.json", encoded(contract))
    report = {"packet_sha256": sha(packet_bytes), "selected_groups": len(packet["selected_lineage_groups"]), "all_selected_member_rows": len(packet["records"]),
              "blind_review_not_inferred_from_packet_creation": True, "independent_gold_rows": 0,
              "readiness": assess_reviews(packet, None), "admin_sampling": admin,
              "frozen_v2_model_unchanged": "4b96a26d0b99ed2ff2d774d7678131c4cb14960b462ba48bcc3790972d31b427",
              "semantic_negative_has_no_authority": True, "no_calibration_qualification_or_gpu_call": True}
    freeze(ROOT / "analysis/night-learned-dialogue.v3.review-prep.json", encoded(report))
    print(json.dumps({k:report[k] for k in ("packet_sha256", "selected_groups", "all_selected_member_rows", "readiness")}, indent=2))


if __name__ == "__main__":
    main()
