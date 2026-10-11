"""TRAIN-only R4 exact source diagnostics. No label generation or admission grant."""
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import narrow_review_v4 as admission
from detector_r4 import DETECTOR_R4_VERSION, detect_candidates_r4
from window_r4 import FEATURE_R4_VERSION, date_features_r4

VERSION = "actual_r4_review_alignment.v5.0"


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


def source_span(index, text, a, b):
    return {"source_packet": admission.PATHS["date"],
            "source_packet_raw_sha256": admission.PINNED_SHA256[admission.PATHS["date"]],
            "source_record_path": f"/records/{index}",
            "raw_field_path": f"/records/{index}/input/utterance/text",
            "offset_unit": "python_unicode_codepoints", "char_start": a, "char_end": b,
            "text": text[a:b], "utf8_byte_start": len(text[:a].encode("utf-8")),
            "utf8_byte_end": len(text[:b].encode("utf-8"))}


def make_actual_vector(validated):
    """Detector first. No annotation spans/labels influence this function."""
    vector, diagnostics = [], []
    for index, row in enumerate(validated["rows"]["date_whole_row"]):
        s = row["snapshot"]
        q, text = s["question"], s["utterance"]["text"]
        replay = replay_surface_admission(s)
        detector = detect_candidates_r4(text, q.get("role", "none"), s.get("targets"),
                                        q.get("security_field"), "en")
        for c in detector.get("candidates", []):
            if c.get("kind") != "date":
                continue
            features = date_features_r4(s, c, replay)
            # A singleton active question is a context-scoped hypothesis, not a
            # learned target decision. Multi-target assignment remains unknown.
            requested = q.get("target_indices", [])
            known = {t["index"] for t in s.get("targets", [])}
            targets = requested if len(requested) == 1 and set(requested) <= known else None
            item = {"id": row["id"] + ":r4:" + c["candidate_id"], "example_id": row["id"],
                    "source_span": source_span(index, text, c["start"], c["end"]),
                    "candidate_role": "current"}
            if targets is not None:
                item["target_indices"] = list(targets)
                vector.append(item)
            diagnostics.append({"id": item["id"], "example_id": row["id"], "group": row["group"],
                                "candidate": c, "source_span": item["source_span"],
                                "target_indices": targets, "target_scope_status":
                                    "singleton_question_hypothesis" if targets else "unimplemented_multiple_target_scope",
                                "feature_eligible": features["eligible"], "feature_reason": features["reason"],
                                "window_bounds": features["window_bounds"],
                                "privacy_eligible": replay["nonsecurity_value_free"],
                                "reference_eligible": False, "normalization_eligible": False,
                                "overflow": detector.get("status") == "overflow"})
    return vector, diagnostics


def support(rows):
    return {label: {"rows": sum(r["label"] == label for r in rows),
                    "groups": len({r["group"] for r in rows if r["label"] == label}),
                    "group_ids": sorted({r["group"] for r in rows if r["label"] == label})}
            for label in ("complete", "unfinished", "ambiguous")}


def analyze(raw_inputs):
    valid = admission.validate_reviewed_inputs(raw_inputs)
    vector, diagnostic = make_actual_vector(valid)
    aligned, stats = admission.align_date_candidates(vector, valid)
    by_id = {d["id"]: d for d in diagnostic}
    eligible = [r for r in aligned if by_id[r["id"]]["feature_eligible"] and not by_id[r["id"]]["overflow"]]
    # Boundary comparisons are diagnostic only. No overlap is turned into a label.
    annotations, annotation_results = valid["date_annotations"], []
    for a in annotations:
        span = a["source_span"]
        candidates = [d for d in diagnostic if d["example_id"] == a["example_id"]]
        exact = [d for d in candidates if d["source_span"]["char_start"] == span["char_start"]
                 and d["source_span"]["char_end"] == span["char_end"]]
        overlap = [d for d in candidates if d["source_span"]["char_start"] < span["char_end"]
                   and span["char_start"] < d["source_span"]["char_end"]]
        scoped = [d for d in exact if d["target_indices"] == a["target_indices"]]
        annotation_results.append({"annotation_id": a["id"], "example_id": a["example_id"],
            "group": a["group"], "source_span": span, "target_indices": a["target_indices"],
            "label": a["label"], "mask": a["mask"], "annotation_pointer": a["annotation_pointer"],
            "status": "exact_scope" if scoped else "exact_span_scope_unresolved" if exact else
                      "boundary_mismatch" if overlap else "missing",
            "actual_candidate_ids": [d["id"] for d in (exact or overlap)]})
    exact_scope = [a for a in annotation_results if a["status"] == "exact_scope"]
    return {"schema_version": VERSION, "train_only": True, "new_dev_read": False,
            "data_validated": True, "admitted": False, "trained": False, "gpu_authorized": False,
            "qualified": False, "payment_authority": False, "human_gold_rows": 0, "iid_gold_rows": 0,
            "source_raw_sha256": dict(admission.PINNED_SHA256),
            "definitions_sha256": valid["definitions_sha256"],
            "source_vectors_sha256": {k: admission.digest(v) for k, v in valid["source_vectors"].items()},
            "detector_version": DETECTOR_R4_VERSION, "feature_version": FEATURE_R4_VERSION,
            "candidate_vector_sha256": admission.digest(vector), "candidate_vector": vector,
            "split_assignments": None, "split_assignments_sha256": None,
            "primary": {"rows": 119, "groups": 49, "masked_rows": 11,
                        "review_support": admission._support(valid["rows"]["primary"], "positive", "negative", True),
                        "surface_eligible_rows": sum(replay_surface_admission(r["snapshot"])["nonsecurity_value_free"]
                                                     for r in valid["rows"]["primary"]),
                        "head": "primary_is_payment_proposal; binary negative is another PRIMARY act only"},
            "date": {"rows": 72, "groups": 22, "actual_raw_candidates": len(diagnostic),
                     "candidate_vector_rows_with_singleton_scope": len(vector),
                     "reviewed_candidate_spans": len(annotations), "alignment": stats,
                     "annotation_status_counts": dict(Counter(a["status"] for a in annotation_results)),
                     "exact_scope_including_ambiguous_support": support(exact_scope),
                     "exact_observed_support": support(aligned),
                     "actual_feature_eligible_observed_support": support(eligible),
                     "completion_floor_met": all(len({r["group"] for r in eligible if r["label"] == label}) >= 20
                                                  for label in ("complete", "unfinished")),
                     "feature_mask_reasons": dict(Counter(d["feature_reason"] or "eligible" for d in diagnostic)),
                     "reference_eligible_candidates": 0, "normalization_eligible_candidates": 0,
                     "privacy_masked_candidates": sum(not d["privacy_eligible"] for d in diagnostic),
                     "candidate_diagnostics": diagnostic, "annotation_diagnostics": annotation_results},
            "limits": ["No independent absent-region review; unmatched detections have no validity target.",
                       "Singleton question target is an offline context hypothesis; multi-target binding unimplemented.",
                       "Reference and normalization masks are false; value_resolution labels do not verify bindings.",
                       "Current five input hashes bind received machine reviews, not historical reviewer-a immutability.",
                       "No parent exact-hash authorization or external split declaration inferred here.",
                       "Engineering supervision only; no human/IID gold, qualification or authority."]}


def main():
    root = admission.ROOT
    report = analyze(admission.load_allowed_inputs())
    report["source_sha256"] = {str(p.relative_to(root)).replace("\\", "/"): admission.sha(p.read_bytes())
        for p in [Path(__file__), Path(admission.__file__), root / "integrations/learned-dialogue/detector_r4.py",
                  root / "integrations/learned-dialogue/window_r4.py"]}
    base = root / "analysis/night-learned-dialogue.v5.alignment"
    json_path, txt_path = Path(str(base) + ".json"), Path(str(base) + ".txt")
    json_path.write_bytes(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n")
    lines = [VERSION, "TRAIN-only exact R4 alignment; new DEV unread; no fitting or authorization.",
             "Primary:119 rows/49 groups,11 masked; reviewed support27 positive/21 additional negative groups.",
             "DATE:" + json.dumps({k: report["date"][k] for k in ("actual_raw_candidates", "reviewed_candidate_spans",
                 "annotation_status_counts", "alignment", "completion_floor_met")}),
             "Actual feature-eligible observed support:" + json.dumps(report["date"]["actual_feature_eligible_observed_support"]),
             "Candidate vector SHA256:" + report["candidate_vector_sha256"], *report["limits"]]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(json_path), "candidate_vector_sha256": report["candidate_vector_sha256"],
                      "date": {k: report["date"][k] for k in ("alignment", "annotation_status_counts", "actual_feature_eligible_observed_support")}}))


if __name__ == "__main__":
    main()
