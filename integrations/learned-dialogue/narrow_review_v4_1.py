"""Pinned provisional machine TRAIN admission. Standard library, no trainer imports.

The parent supplies authorization bytes AND an independently trusted exact digest.
This module cannot authenticate a caller, issue authorization, or prove historical
review immutability. Never obtain the trust digest from the authorization itself.
Detector candidates are supplied separately; annotation spans are not detections.
"""
import argparse
import copy
import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = "reviewed_machine_train_admission.v4.1"
PACKET_SCHEMA = "input_only_canonical_review_packet.v3"
PATHS = {
    "primary": "research/customer-benchmark/semantic-v3-collection/label-free-primary-review-packet.json",
    "date": "research/customer-benchmark/semantic-v3-collection/label-free-date-review-packet.json",
    "reviewer-a": "analysis/night-v3-fresh-reviewer-a.json",
    "reviewer-b": "analysis/night-v3-fresh-reviewer-b.json",
    "adjudication": "analysis/night-v3-fresh-adjudication.json",
}
PINNED_SHA256 = dict(zip(PATHS.values(), (
    "7bf9081b5c51fb6e402a88d71ab57c398ba1292ef5eaa145948865d2f4e952f9",
    "7397467d49bbd557f8cfe3c5b23520049d081addb594e1a6696d749cdaa07808",
    "87280983ed1772b09d782d582cbc5647a3a478566c1327483a956b31ef780a31",
    "46efb3e528b738cf372ba81d178b875ce0bd080bd0045bd8785ee822033a75f9",
    "12fe2752007afc6c978b05f3a6b0db0f963683f1a3a5238f49b2589995d737b4",
)))
EXPECTED_COUNTS = {"primary": (119, 49), "date": (72, 22)}
# User-supplied thread inventory, NOT a verified registry. The parent must bind
# the actual A/B mapping; the reports themselves do not contain these agent IDs.
REVIEWER_IDS = ("reviewer-a", "reviewer-b", "fresh-machine-adjudicator")
EXPECTED_REVIEW_THREAD_IDS = frozenset(("01a128dd-0932-7313-9f0e-950885f79bb6",
                                      "01a128e3-ee71-71e3-9486-8d637975599b"))
EXPECTED_ADJUDICATOR_THREAD_ID = "01a128ec-2bb6-7601-94c8-cd9628280037"
HEADS = ("primary", "date_whole_row", "date_scoped_candidate")
FLOOR = 20


class AdmissionError(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    """Source digest recipe: compact UTF-8 JSON, original insertion order."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return sha(encoded(value))


def _require(condition, reason):
    if not condition:
        raise AdmissionError(reason)


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "duplicate_json_key")
            result[key] = value
        return result
    def invalid(_):
        raise AdmissionError("nonfinite_json_number")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def load_allowed_inputs(root=ROOT):
    """Reads exactly the five permitted data inputs, never a corpus/registry."""
    return {path: (Path(root) / path).read_bytes() for path in PINNED_SHA256}


def pointer(value, path):
    _require(isinstance(path, str) and path.startswith("/"), "unknown_span_pointer")
    try:
        for token in path[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            value = value[int(token)] if isinstance(value, list) else value[token]
        return value
    except (KeyError, ValueError, IndexError, TypeError):
        raise AdmissionError("unknown_span_pointer") from None


def validate_span(span, packet, kind, index):
    prefix = f"/records/{index}/input/"
    _require(span.get("source_packet") == PATHS[kind] and
             span.get("source_packet_raw_sha256") == PINNED_SHA256[PATHS[kind]], "span_packet_binding")
    path = span.get("raw_field_path", "")
    _require(path.startswith(prefix), "span_outside_source_member")
    text = pointer(packet, path)
    _require(isinstance(text, str), "span_source_not_string")
    start, end = span.get("char_start"), span.get("char_end")
    _require(type(start) is int and type(end) is int and 0 <= start < end <= len(text), "unknown_span_coordinates")
    _require(span.get("offset_unit") == "python_unicode_codepoints", "unknown_span_unit")
    _require(text[start:end] == span.get("text"), "span_exact_text_mismatch")
    bs, be = len(text[:start].encode("utf-8")), len(text[:end].encode("utf-8"))
    if "utf8_byte_start" in span or "utf8_byte_end" in span:
        _require(span.get("utf8_byte_start") == bs and span.get("utf8_byte_end") == be, "span_utf8_mismatch")
    _require(text.encode("utf-8")[bs:be] == span["text"].encode("utf-8"), "span_utf8_mismatch")
    if "source_record_path" in span:
        _require(span["source_record_path"] == f"/records/{index}", "span_record_pointer_mismatch")
    if "record_field_path" in span:
        _require(span["record_field_path"] == path[len(f"/records/{index}"):], "span_relative_pointer_mismatch")


def _walk_spans(value):
    if isinstance(value, dict):
        if "raw_field_path" in value:
            yield value
        else:
            for item in value.values():
                yield from _walk_spans(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_spans(item)


def _source_binding(row, source, kind, index):
    for key in ("example_id", "canonical_group_id", "lineage_group_id"):
        _require(row.get(key) == source[key], "source_identity_or_lineage_mismatch")
    _require(row.get("source_packet") == PATHS[kind] and
             row.get("source_packet_raw_sha256") == PINNED_SHA256[PATHS[kind]] and
             row.get("source_record_path") == f"/records/{index}", "source_position_or_packet_mismatch")
    record_digest = row.get("source_record_json_sha256", row.get("source_record_sha256"))
    _require(record_digest == digest(source), "source_record_hash_mismatch")
    if "source_input_json_sha256" in row:
        _require(row["source_input_json_sha256"] == digest(source["input"]), "source_input_hash_mismatch")
        _require(row.get("source_input_path") == f"/records/{index}/input", "source_input_pointer_mismatch")
    if "source_input" in row:
        _require(row["source_input"] == source["input"], "source_input_snapshot_mismatch")
    else:
        _require(row.get("source_snapshot") == source, "source_record_snapshot_mismatch")


def _label(row, kind, adjudicated=False):
    label = row.get("finalLabel" if adjudicated else "label")
    vocabulary = {"positive", "negative", "ambiguous"} if kind == "primary" else {"complete", "unfinished", "ambiguous"}
    _require(label in vocabulary, "unknown_annotation_label")
    observed = row.get("observed", row.get("observedbinary", row.get("observed_binary")))
    _require(observed is (label != "ambiguous"), "annotation_mask_mismatch")
    if kind == "primary":
        _require(row.get("binary_value") is (None if label == "ambiguous" else label == "positive"), "binary_mask_mismatch")
    return label


def _support(rows, positive, negative, additional=False):
    pos = {r["group"] for r in rows if r["label"] == positive}
    neg = {r["group"] for r in rows if r["label"] == negative}
    eligible_neg = neg - pos if additional else neg
    return {"positive_groups": len(pos), "negative_groups": len(neg),
            "additional_negative_groups": len(neg - pos), "overlap_groups": len(pos & neg),
            "unique_support_groups": len(pos | neg), "positive_group_ids": sorted(pos),
            "negative_group_ids": sorted(neg), "floor_negative_group_ids": sorted(eligible_neg),
            "floors_met": len(pos) >= FLOOR and len(eligible_neg) >= FLOOR}


def _validate_documents(documents):
    """Structural checks; production entry also verifies immutable raw pins."""
    packets = {kind: documents[PATHS[kind]] for kind in ("primary", "date")}
    reviews = {rid: documents[PATHS[rid]] for rid in ("reviewer-a", "reviewer-b")}
    adjud = documents[PATHS["adjudication"]]
    _require(adjud.get("adjudicator_id") == "fresh-machine-adjudicator" and
             adjud.get("fresh_context") is True and adjud.get("is_original_author") is False, "third_party_adjudicator_required")
    all_ids, aliases, closure, source_vector = set(), {}, {}, {}
    rows, date_annotations = {head: [] for head in HEADS}, []
    span_count = 0
    for kind, packet in packets.items():
        _require(packet.get("schema_version") == PACKET_SCHEMA, "packet_schema_mismatch")
        source_rows = packet["records"]
        ids = [r["example_id"] for r in source_rows]
        _require(len(ids) == len(set(ids)) and not all_ids.intersection(ids), "packet_duplicate_member")
        all_ids.update(ids)
        groups = defaultdict(list)
        vector = []
        for i, source in enumerate(source_rows):
            root = source["canonical_group_id"]
            groups[root].append(source)
            for alias in (root, source["lineage_group_id"]):
                _require(alias not in aliases or aliases[alias] == root, "canonical_lineage_alias_conflict")
                aliases[alias] = root
            vector.append({"packet_index": i, "example_id": source["example_id"], "canonical_group_id": root,
                           "lineage_group_id": source["lineage_group_id"], "source_record_path": f"/records/{i}",
                           "source_record_json_sha256": digest(source), "source_input_json_sha256": digest(source["input"])})
        selected = packet["selected_canonical_groups"]
        _require(len(selected) == len(set(selected)) and set(selected) == set(groups), "packet_selected_group_closure")
        _require((len(ids), len(groups)) == EXPECTED_COUNTS[kind], "packet_member_or_group_count_mismatch")
        source_vector[kind] = vector
        binding = adjud["source_binding_vectors"][kind]
        _require(binding["members"] == vector and binding["encoded_vector_sha256"] == digest(vector), "adjudication_source_vector_mismatch")
        closure[kind] = [{"canonical_group_id": root, "example_ids": sorted(r["example_id"] for r in members),
                          "lineage_group_ids": sorted({r["lineage_group_id"] for r in members})}
                         for root, members in sorted(groups.items())]
        for rid, review in reviews.items():
            _require(review.get("reviewer_id") == rid and review.get("fresh_context") is True and
                     review.get("is_original_author") is False, "independent_reviewer_identity_required")
            _require(review.get("sourcepacketrawhashes", {}).get(PATHS[kind]) == PINNED_SHA256[PATHS[kind]], "review_packet_hash_mismatch")
            annotated = review[kind + "_records"]
            _require([r.get("example_id") for r in annotated] == ids, "review_all_members_ordered_exactly_once")
        final_rows = adjud[kind + "_records"]
        _require([r.get("example_id") for r in final_rows] == ids, "adjudication_all_members_ordered_exactly_once")
        for i, (source, final) in enumerate(zip(source_rows, final_rows)):
            _source_binding(final, source, kind, i)
            _require(final.get("packet_kind") == kind and final.get("packet_index") == i, "adjudication_source_position_mismatch")
            originals = final["original_annotations"]
            _require([a.get("reviewer_id") for a in originals] == list(reviews), "two_distinct_original_reviews_required")
            labels = []
            for rid, original in zip(reviews, originals):
                annotation = reviews[rid][kind + "_records"][i]
                _source_binding(annotation, source, kind, i)
                labels.append(_label(annotation, kind))
                _require(original.get("annotation") == annotation and original.get("annotation_encoded_sha256") == digest(annotation)
                         and original.get("report_raw_sha256") == PINNED_SHA256[PATHS[rid]]
                         and original.get("report_path") == PATHS[rid]
                         and original.get("annotation_json_pointer") == f"/{kind}_records/{i}", "original_annotation_changed_or_unbound")
            decision = final["adjudication"]
            label = _label(decision, kind, True)
            _require(decision.get("status") == ("masked_ambiguous" if label == "ambiguous" else "adjudicated"), "final_adjudication_status")
            agreed = labels[0] == labels[1]
            _require(final.get("reviewer_labels_agree") is agreed, "review_agreement_flag_mismatch")
            _require(decision.get("decision_basis") == ("retained_agreement" if agreed else "source_adjudication_of_disagreement"), "third_party_decision_basis")
            _require(not agreed or label == labels[0], "adjudication_changed_agreement")
            _require(decision.get("machine_provisional_not_gold") is True and decision.get("payment_authority_inferred") is False, "engineering_only_authority_required")
            _require(bool(decision.get("evidence_spans")), "adjudication_source_evidence_required")
            for span in _walk_spans(final):
                validate_span(span, packet, kind, i)
                span_count += 1
            base = {"id": source["example_id"], "group": source["canonical_group_id"], "lineage_group_id": source["lineage_group_id"],
                    "snapshot": source["input"], "label": label, "mask": label != "ambiguous", "split": "train",
                    "source_binding": vector[i], "annotation_pointer": f"/{kind}_records/{i}/adjudication"}
            rows["primary" if kind == "primary" else "date_whole_row"].append(base)
            if kind == "date":
                for j, candidate in enumerate(decision.get("target_date_candidates", [])):
                    clabel = _label(candidate, "date")
                    _require(candidate.get("candidate_role") == "current", "superseded_candidate_cannot_supply_current_support")
                    targets = candidate.get("target_indices")
                    known = {t["index"] for t in source["input"]["targets"]}
                    requested = set(source["input"]["question"]["target_indices"])
                    _require(isinstance(targets, list) and bool(targets) and len(set(targets)) == len(targets)
                             and all(type(t) is int for t in targets) and set(targets) <= known & requested, "candidate_target_scope_unknown")
                    _require(candidate["source_span"]["raw_field_path"] == f"/records/{i}/input/utterance/text", "candidate_not_utterance_source")
                    item = {**base, "id": source["example_id"] + f":date:{j}", "example_id": source["example_id"],
                            "label": clabel, "mask": clabel != "ambiguous", "target_indices": targets,
                            "source_span": candidate["source_span"], "candidate_role": "current",
                            "annotation_pointer": f"/date_records/{i}/adjudication/target_date_candidates/{j}"}
                    date_annotations.append(item)
    b = reviews["reviewer-b"]
    _require(b["provisional_meanings_sha256"] == digest({k: b[k] for k in ("primary_records", "date_records")}), "reviewer_b_frozen_annotations_mismatch")
    return {"closure": closure, "aliases": aliases, "source_vectors": source_vector, "rows": rows,
            "date_annotations": date_annotations, "validated_span_occurrences": span_count,
            "definitions_sha256": digest(adjud["definitions"]),
            "reviewer_a_reported_historical_sha256": reviews["reviewer-a"]["provisional_meanings_snapshot"]["raw_sha256"],
            "reviewer_b_verified_frozen_annotations_sha256": b["provisional_meanings_sha256"]}


def validate_reviewed_inputs(raw_inputs):
    _require(set(raw_inputs) == set(PINNED_SHA256), "exact_allowed_input_set_required")
    for path, expected in PINNED_SHA256.items():
        _require(sha(raw_inputs[path]) == expected, "input_raw_hash_mismatch:" + path)
    try:
        return _validate_documents({path: strict_json(raw) for path, raw in raw_inputs.items()})
    except (KeyError, TypeError, IndexError) as error:
        raise AdmissionError("malformed_annotation_structure:" + type(error).__name__) from None


def validate_split_assignments(assignments, aliases):
    """Identifier-only external declarations; never opens development data."""
    _require(isinstance(assignments, list) and bool(assignments), "external_split_declarations_missing")
    split_by_root = {}
    for item in assignments:
        group, split = item.get("group_id"), item.get("split")
        _require(isinstance(group, str) and split in ("train", "dev", "holdout"), "unknown_split_declaration")
        root = aliases.get(group, group)
        _require(root not in split_by_root or split_by_root[root] == split, "group_train_dev_or_holdout_alias_leakage")
        split_by_root[root] = split
    _require(all(split_by_root.get(root) == "train" for root in set(aliases.values())), "all_packet_groups_declared_train_required")


def align_date_candidates(candidates, validated):
    """Match actual detector candidates to exact reviewed spans AND target sets.

    Candidate schema: id, example_id, target_indices, source_span, candidate_role.
    No label is accepted from a detector. Unmatched detections remain masked.
    """
    if candidates is None:
        return [], {"provided": False, "matched": 0, "unmatched": 0, "masked": 0}
    _require(isinstance(candidates, list), "candidate_vector_required")
    def key(item):
        s = item["source_span"]
        return (item["example_id"], tuple(sorted(item["target_indices"])), s["raw_field_path"], s["char_start"], s["char_end"], s["text"])
    annotations = {key(item): item for item in validated["date_annotations"]}
    _require(len(annotations) == len(validated["date_annotations"]), "duplicate_reviewed_candidate_scope")
    seen_ids, seen_scopes, aligned, unmatched, masked = set(), set(), [], 0, 0
    sources = {r["id"]: (i, r) for i, r in enumerate(validated["rows"]["date_whole_row"])}
    packet = {"records": [{"input": r["snapshot"]} for r in validated["rows"]["date_whole_row"]]}
    for item in candidates:
        _require(isinstance(item.get("id"), str) and item["id"] not in seen_ids, "duplicate_detector_candidate")
        seen_ids.add(item["id"])
        _require(item.get("example_id") in sources and item.get("candidate_role") == "current", "unknown_or_superseded_detector_candidate")
        index, _ = sources[item["example_id"]]
        validate_span(item["source_span"], packet, "date", index)
        _require("label" not in item and "y" not in item, "detector_must_not_supply_supervision")
        targets = item.get("target_indices")
        snapshot = sources[item["example_id"]][1]["snapshot"]
        known_targets = {t["index"] for t in snapshot["targets"]}
        requested_targets = set(snapshot["question"]["target_indices"])
        _require(isinstance(targets, list) and bool(targets) and all(type(t) is int for t in targets)
                 and len(targets) == len(set(targets)) and set(targets) <= known_targets & requested_targets,
                 "candidate_target_scope_unknown")
        scope = key(item)
        _require(scope not in seen_scopes, "duplicate_detector_candidate_scope")
        seen_scopes.add(scope)
        annotation = annotations.get(scope)
        if annotation is None:
            unmatched += 1
        elif not annotation["mask"]:
            masked += 1
        else:
            aligned.append({**annotation, "id": item["id"], "detector_candidate_sha256": digest(item)})
    return aligned, {"provided": True, "matched": len(aligned), "unmatched": unmatched, "masked": masked}


def assess_admission(raw_inputs, authorization_raw=None, trusted_authorization_sha256=None,
                     candidates=None, split_assignments=None, require_historical_immutability=False):
    """Prepare diagnostics and gated rows; missing authority always fails closed.

    A caller controlling both auth and the trust anchor is not authenticated by
    this API. Parent issuance must be established outside the data under review.
    """
    report = {"schema_version": SCHEMA, "admitted": False, "cpu_authorized": False, "gpu_authorized": False,
              "human_gold_rows": 0, "iid_gold_rows": 0, "qualified": False, "payment_authority": False,
              "scope": "provisional machine TRAIN engineering supervision; packet closure only",
              "model_identity": "inherited workhorse fallback; no verified 5.6 identity claim",
              "global_registry_closure": "unknown", "historical_reviewer_a_immutability": "unknown; historical bytes unavailable",
              "source_raw_sha256": {p: sha(b) for p, b in raw_inputs.items()}, "reasons": [],
              "eligible_rows": {head: [] for head in HEADS}}
    try:
        valid = validate_reviewed_inputs(raw_inputs)
        aligned, alignment = align_date_candidates(candidates, valid)
        valid["rows"]["date_scoped_candidate"] = aligned
        report.update({"data_validated": True, "canonical_packet_closure": valid["closure"],
                       "closure_schema_version": "supplied_canonical_packet_closure.v4",
                       "canonical_packet_closure_sha256": digest(valid["closure"]),
                       "source_vectors_sha256": {k: digest(v) for k, v in valid["source_vectors"].items()},
                       "definitions_sha256": valid["definitions_sha256"], "validated_span_occurrences": valid["validated_span_occurrences"],
                       "reviewer_a_historical_snapshot": {"reported_sha256": valid["reviewer_a_reported_historical_sha256"],
                           "verified": False, "status": "historical bytes absent from allowed inputs"},
                       "reviewer_b_frozen_annotations": {"sha256": valid["reviewer_b_verified_frozen_annotations_sha256"],
                           "current_annotation_digest_verified": True},
                       "alignment": alignment, "mask_counts": {"primary": 11, "date_whole_row": 3},
                       "annotated_candidate_support": _support(valid["date_annotations"], "complete", "unfinished"),
                       "candidate_vector_sha256": digest(candidates) if candidates is not None else None,
                       "split_assignments_sha256": digest(split_assignments) if split_assignments is not None else None})
        report["support"] = {head: _support(rows, "positive" if head == "primary" else "complete",
                                            "negative" if head == "primary" else "unfinished", head == "primary")
                             for head, rows in valid["rows"].items()}
        report["mask_counts"] = {head: sum(not row["mask"] for row in valid["rows"][head]) for head in ("primary", "date_whole_row")}
        common = []
        if require_historical_immutability:
            common.append("historical_reviewer_a_immutability_unverifiable")
        try:
            validate_split_assignments(split_assignments, valid["aliases"])
        except AdmissionError as error:
            common.append(str(error))
        if authorization_raw is None or trusted_authorization_sha256 is None:
            common.append("externally_trusted_exact_hash_parent_authorization_missing")
            authorization = {}
        else:
            _require(sha(authorization_raw) == trusted_authorization_sha256, "external_parent_authorization_hash_mismatch")
            authorization = strict_json(authorization_raw)
            _require(authorization.get("schema_version") == "parent_cpu_engineering_authorization.v4.1" and
                     authorization.get("issuer") == "parent" and authorization.get("cpu_only") is True and
                     authorization.get("gpu_authorized") is False and authorization.get("qualified") is False and
                     authorization.get("payment_authority") is False, "parent_cpu_only_engineering_authorization_required")
            _require(authorization.get("source_raw_sha256") == PINNED_SHA256 and
                     authorization.get("definitions_sha256") == valid["definitions_sha256"] and
                     authorization.get("source_vectors_sha256") == report["source_vectors_sha256"] and
                     authorization.get("candidate_vector_sha256") == report["candidate_vector_sha256"] and
                     authorization.get("split_assignments_sha256") == report["split_assignments_sha256"], "parent_authorization_data_binding_mismatch")
            _require(authorization.get("historical_immutability_required") is False and
                     authorization.get("acknowledges_unknown_reviewer_a_history") is True, "historical_reviewer_a_immutability_unverifiable")
            roster = authorization.get("reviewer_registry", {})
            _require(set(roster) == set(REVIEWER_IDS), "parent_verified_reviewer_roster_required")
            for rid in REVIEWER_IDS:
                entry = roster[rid]
                proof = ("parent_verified_isolated_source_adjudication" if rid == "fresh-machine-adjudicator"
                         else "parent_verified_isolated_blind_source_review")
                _require(entry.get(proof) is True and entry.get("is_original_author") is False,
                         "parent_verified_reviewer_roster_required")
            _require({roster[rid].get("thread_id") for rid in REVIEWER_IDS[:2]} == EXPECTED_REVIEW_THREAD_IDS and
                     roster["fresh-machine-adjudicator"].get("thread_id") == EXPECTED_ADJUDICATOR_THREAD_ID,
                     "parent_verified_reviewer_roster_required")
            requested = authorization.get("heads", [])
            _require(isinstance(requested, list) and bool(requested) and len(set(requested)) == len(requested)
                     and set(requested) <= set(HEADS), "unknown_authorized_head")
            report["authorization_raw_sha256"] = sha(authorization_raw)
        requested = authorization.get("heads", [])
        report["head_admission"] = {}
        for head in HEADS:
            reasons = list(common)
            if head not in requested:
                reasons.append("head_not_externally_authorized")
            if not report["support"][head]["floors_met"]:
                reasons.append("adjudicated_aligned_group_floor_unmet")
            if head == "date_scoped_candidate" and candidates is None:
                reasons.append("actual_detector_candidate_alignment_missing")
            report["head_admission"][head] = {"admitted": not reasons, "reasons": sorted(set(reasons))}
            if not reasons:
                report["eligible_rows"][head] = [copy.deepcopy({**row, "y": int(row["label"] in ("positive", "complete"))})
                                                  for row in valid["rows"][head] if row["mask"]]
        report["admitted"] = report["cpu_authorized"] = bool(requested) and all(report["head_admission"][h]["admitted"] for h in requested)
        if not report["admitted"]:
            report["eligible_rows"] = {head: [] for head in HEADS}
        report["reasons"] = sorted(set(common + [r for h in requested for r in report["head_admission"][h]["reasons"]]))
    except (AdmissionError, ValueError, KeyError, TypeError) as error:
        report.setdefault("data_validated", False)
        report["admitted"] = report["cpu_authorized"] = False
        report["reasons"] = [str(error)]
        report["eligible_rows"] = {head: [] for head in HEADS}
    return report


def build_cpu_training_rows(raw_inputs, head, **admission_arguments):
    """Returns only observed source-adjudicated rows after explicit head admission."""
    _require(head in HEADS, "unknown_training_head")
    result = assess_admission(raw_inputs, **admission_arguments)
    _require(result["admitted"] and result.get("head_admission", {}).get(head, {}).get("admitted"),
             "cpu_training_rows_not_authorized:" + ",".join(result["reasons"]))
    return result["eligible_rows"][head]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = assess_admission(load_allowed_inputs())
    _require(report.get("data_validated") is True, "report_generation_requires_validated_inputs")
    report["implementation_boundary"] = "No training, network, cloud, platform, GPU or secret actions. No authorization issued."
    report["handoff"] = "Parent reviews these bytes, supplies actual detector candidates and identifier-only split declarations, then externally issues CPU-only exact-hash authorization."
    report["api_contract"] = {
        "input_loader": "load_allowed_inputs(root=ROOT) reads only the five pinned files",
        "assessment": "assess_admission(raw_inputs, authorization_raw=None, trusted_authorization_sha256=None, candidates=None, split_assignments=None, require_historical_immutability=False)",
        "training_rows": "build_cpu_training_rows(raw_inputs, head, **admission_arguments); unauthorized or failed requested heads raise AdmissionError",
        "heads": list(HEADS), "class_floor": FLOOR,
        "primary_negative_semantics": "Known different primary act; never infer bank policy, absence of secondary payment, consent, refusal, invalidity or permission from binary zero.",
        "candidate_fields": ["id", "example_id", "target_indices", "source_span", "candidate_role=current"],
        "candidate_alignment": "Exact source example, target set, JSON Pointer, Unicode span bounds and text; labels/y from detectors rejected; unmatched/ambiguous candidates masked, superseded candidates rejected",
        "split_declaration_fields": ["group_id", "split=train|dev|holdout"],
        "split_scope": "Parent identifier-only declarations; canonical and supplied lineage aliases cannot cross splits. Global out-of-packet aliases remain unknown.",
        "authorization_schema": "parent_cpu_engineering_authorization.v4.1",
        "authorization_required_bindings": ["source_raw_sha256", "definitions_sha256", "source_vectors_sha256", "candidate_vector_sha256", "split_assignments_sha256"],
        "authorization_required_assertions": ["issuer=parent", "cpu_only=true", "gpu_authorized=false", "qualified=false", "payment_authority=false", "historical_immutability_required=false", "acknowledges_unknown_reviewer_a_history=true", "heads"],
        "reviewer_registry_requirement": "Externally parent-verified mapping of reviewer-a/reviewer-b to the two user-confirmed isolated threads and fresh-machine-adjudicator to the separately confirmed third thread. Each entry requires thread_id, parent_verified_isolated_blind_source_review=true, is_original_author=false. No verified registry is created here.",
        "trust_boundary": "The exact raw authorization digest must come from an independent trusted parent channel. A digest supplied by the receipt or untrusted caller does not authenticate parent issuance.",
    }
    output = ROOT / "analysis/night-v3-reviewed-data-admission.json"
    output.write_bytes(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n")
    summary = ["Reviewed machine TRAIN engineering data admission v4", "Admitted: false; CPU authorization pending; GPU authorization: false.",
               "Primary: 27 positive, 21 additional negative canonical groups, 49 packet groups; 11 ambiguous rows masked.",
               "DATE whole row: 22 complete / 19 unfinished groups; FAIL 20/20; 3 ambiguous rows masked.",
               "DATE annotations: 22 complete / 20 unfinished groups. Actual detector candidates were not supplied; aligned support 0/0; BLOCKED.",
               "Closure covers only supplied packet members; full corpus/registry closure unknown.",
               "Reviewer-a historical provisional snapshot unavailable; current received bytes bound, history unknown. Any historical-immutability requirement blocks admission.",
               "Zero human gold, IID gold, qualification or payment authority. No training or GPU authorization.",
               "Parent authorization must bind exact five input hashes, definitions, source vectors, actual candidate vector and split declarations; trust digest supplied out of band.",
               "Caller/trust-anchor authenticity must be established externally; this module does not authenticate the parent.",
               "API: assess_admission(raw_inputs, authorization_raw, trusted_authorization_sha256, candidates, split_assignments).",
               "Builder: build_cpu_training_rows(raw_inputs, head, **admission_arguments); heads primary/date_whole_row/date_scoped_candidate. No rows returned without admission.",
               "Candidates: detector id, example_id, target_indices, exact source_span, candidate_role=current; detector labels rejected.",
               "Split declarations: group_id and train/dev/holdout, identifier-only. Parent supplies the actual reviewer A/B mapping; none inferred here.",
               "Current validation: " + str(report["validated_span_occurrences"]) + " exact span occurrences; reviewer-b frozen annotation digest verified; no historical reviewer-a certification.",
               "", "Exact input SHA256:"]
    summary += [p + " " + h for p, h in PINNED_SHA256.items()]
    summary += ["", "JSON report SHA256: " + sha(output.read_bytes())]
    (ROOT / "analysis/night-v3-reviewed-data-admission.txt").write_bytes(("\n".join(summary) + "\n").encode("utf-8"))
    print(json.dumps({"data_validated": report.get("data_validated"), "admitted": report["admitted"], "reasons": report["reasons"]}))


if __name__ == "__main__":
    main()
