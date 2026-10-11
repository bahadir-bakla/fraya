"""Checkpoint05 lineage closure + two blind reviews + parent adjudication.

Consumes versioned parent overlays; never writes annotations or relabels data.
Evidence identifiers/flags must be checked independently by the parent. No
claimed cryptographic authentication, IID proof or semantic qualification.
"""
from modal_narrow_core import canonical, digest, hash_ok, POSITIVE_FLOOR, NEGATIVE_FLOOR


def assess_reviews_v3(packet, reviews, authorization, train, dev, source_manifest_blob, lineage_overlay):
    reasons, eligible, masked = [], [], {}
    auth = authorization or {}
    reviews = reviews or {}
    source = {r["example_id"]:r for r in train["records"]}
    cmap = lineage_overlay.get("canonical_map", {})
    bindings = {"packet_sha256":auth.get("packet_sha256"), "reviews_sha256":auth.get("reviews_sha256"),
                "source_manifest_sha256":digest(source_manifest_blob), "lineage_overlay_sha256":digest(canonical(lineage_overlay))}
    # Historical pretty canonical review hashes use the supplied source bytes;
    # caller verifies exact bytes and passes hash bindings in authorization.
    if auth.get("source_manifest_sha256") != bindings["source_manifest_sha256"] or auth.get("lineage_overlay_sha256") != bindings["lineage_overlay_sha256"] or not all(hash_ok(v) for v in bindings.values()):
        reasons.append("parent_exact_manifest_or_overlay_binding_missing")
    if auth.get("semantic_axes_version") != lineage_overlay.get("semantic_axes_version") or not auth.get("semantic_axes_version"):
        reasons.append("semantic_axes_version_missing")
    all_groups = {r["lineage_group_id"] for r in train["records"]+dev["records"]}
    if set(cmap) != all_groups or any(not isinstance(cmap.get(g), str) or cmap.get(cmap.get(g)) != cmap.get(g) for g in all_groups):
        reasons.append("complete_transitive_canonical_map_required")
    train_groups = {cmap.get(r["lineage_group_id"]) for r in train["records"]}
    dev_groups = {cmap.get(r["lineage_group_id"]) for r in dev["records"]}
    if (train_groups & dev_groups)-{None}:
        reasons.append("canonical_train_dev_overlap_quarantine_required")
    selected = {cmap.get(r["lineage_group_id"]) for r in packet["records"]}
    for member in packet["records"]:
        original = source.get(member.get("example_id"))
        if original is None or original["input"] != member.get("input") or original["lineage_group_id"] != member.get("lineage_group_id"):
            reasons.append("packet_member_source_mismatch")
    closure = {r["example_id"] for r in train["records"] if cmap.get(r["lineage_group_id"]) in selected}
    annotations = reviews.get("records", [])
    ids = [r.get("example_id") for r in annotations]
    missing = sorted(closure-set(ids))
    if set(ids) != closure or len(ids) != len(set(ids)):
        reasons.append("all_canonical_closure_members_exactly_once_required")
    if auth.get("parent_verified_blind_independence") is not True or auth.get("parent_adjudication_verified") is not True or auth.get("closure_supplement_delivered_verified") is not True:
        reasons.append("parent_independence_adjudication_or_supplement_missing")
    registry = auth.get("reviewer_registry", {})
    for row in annotations:
        original = source.get(row.get("example_id"))
        if original is None or original["split"] != "train" or row.get("example_id") not in closure:
            reasons.append("unknown_or_nontrain_review_id")
            continue
        if row.get("input_sha256") != digest(canonical(original["input"])):
            reasons.append("review_input_binding_mismatch")
        blind = row.get("annotations", [])
        reviewers = [item.get("reviewer_id") for item in blind]
        if len(blind) != 2 or len(set(reviewers)) != 2 or any(item.get("label") not in ("positive", "negative", "ambiguous") for item in blind):
            reasons.append("two_distinct_valid_blind_annotations_required")
            continue
        for name in reviewers:
            record = registry.get(name, {})
            if record.get("verified_independent_blind") is not True or record.get("is_original_author") is not False or not hash_ok(record.get("parent_evidence_sha256")):
                reasons.append("reviewer_exposure_identity_evidence_missing")
        adjudication = row.get("adjudication", {})
        final = adjudication.get("label")
        if final not in ("positive", "negative", "ambiguous") or adjudication.get("status") != "adjudicated" or not hash_ok(adjudication.get("parent_evidence_sha256")):
            reasons.append("independently_verified_final_adjudication_missing")
            continue
        if blind[0]["label"] != blind[1]["label"] or final != blind[0]["label"]:
            judge = adjudication.get("adjudicator_id")
            record = registry.get(judge, {})
            if judge in reviewers or record.get("verified_independent_blind") is not True or record.get("is_original_author") is not False or not hash_ok(record.get("parent_evidence_sha256")):
                reasons.append("independent_conflict_adjudicator_required")
        if final == "ambiguous":
            masked[row["example_id"]] = "adjudicated_primary_ambiguity"
            continue
        eligible.append({"id":row["example_id"], "original_group":original["lineage_group_id"],
                         "group":cmap.get(original["lineage_group_id"]), "snapshot":original["input"], "y":int(final == "positive"),
                         "privacy_review":row.get("privacy_review",{})})
    positive = {r["group"] for r in eligible if r["y"]}
    negative = {r["group"] for r in eligible if not r["y"]}
    if len(positive) < POSITIVE_FLOOR or len(negative-positive) < NEGATIVE_FLOOR:
        reasons.append("reviewed_canonical_class_floor_closed")
    return {"admitted":not reasons, "reasons":sorted(set(reasons)), "missing_closure_ids":missing,
            "canonical_positive_groups":len(positive), "canonical_negative_groups":len(negative),
            "additional_negative_groups":len(negative-positive), "mixed_groups":len(positive & negative),
            "complete_review_groups":len(selected) if not missing else None, "masked_rows_by_reason":masked,
            "eligible_rows_with_canonical_group":eligible if not reasons else [], "qualified":False, "iid_proven":False}
