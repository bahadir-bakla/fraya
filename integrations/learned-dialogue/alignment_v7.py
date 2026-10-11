"""Exact frozen V6 detection/source adjudication join. No fitting or grants."""
import json
from collections import Counter
from pathlib import Path

import jsonschema
import data_v6 as source

ROOT = source.ROOT
VERSION = "reviewed_source_alignment.v7.0"
PINS = {
    "analysis/night-v6-adjudication.primary-packet.json":"491fc880ce2fbe4e33e5052dd0703db765e14430883154d70edb363f4538cf84",
    "analysis/night-v6-adjudication.peer-packet.json":"5f3693e86cbb4300394ec3b4c2fe757ce2bdb8055caeb4133d46c78785003a4c",
    "research/customer-benchmark/semantic-v6-extension/source-adjudicated-lineage.json":"f2bc3e0a9631a4707f7863401f42fa74dbe41a189f261ed56e11f73373c84612",
    "analysis/night-v6-adjudication.json":"a85af45818da6ba169c6ac079da6719754a9a806e4d928c4a45ef1600d30ff8b",
    "analysis/night-v6-parent-source-review-proof.json":"e7afca1b6cd50c6d0c2d6dcb7b43975f922aea803ae8a1b4c01b4cb73c5dd9bd",
    "research/customer-benchmark/semantic-v6-peer-extension/independent-review.schema.json":"a6858f8b42b76ccf98a5cdd3bcb68fe9eed16376d7dc587fd2d858e4e25b7424",
    "research/customer-benchmark/semantic-v6-extension/runtime-candidates.v6.json":"3e19e40f4e91ccf57c6336329338e943d0020b366d1e6c057bb02fca4921b226",
    "research/customer-benchmark/semantic-v6-extension/runtime-features.v6.json":"e1323a3c5da823e2d53fe7dd56973c29f8956b2e7788f24164b74bfcce922af9",
    "analysis/night-learned-dialogue.v6-preparation.json":"b6b8ff06a4899d11c0a355c7561b68d5b39cdaf79da8fb4e1f4d177539a6de33",
    "analysis/night-learned-dialogue.v5.primary-readiness.json":"68e9fe630ebc50199e06e015b6a2600a238a4f1ce57a7c645aa51224cff6524f",
}


def load_inputs(root=ROOT):
    raw = {p:(Path(root)/p).read_bytes() for p in PINS}
    for p,pin in PINS.items():source.require(source.sha(raw[p])==pin,"v7_input_hash_mismatch:"+p)
    documents = {p:source.strict_json(b) for p,b in raw.items()}
    proof = documents["analysis/night-v6-parent-source-review-proof.json"]
    reviews = {}
    for item in proof["observations"]:
        p = item["annotation"]
        source.require(p in {
            "analysis/night-v6-reviewer-a.primary-packet.json","analysis/night-v6-reviewer-a.peer-packet.json",
            "analysis/night-v6-reviewer-b.primary-packet.json","analysis/night-v6-reviewer-b.peer-packet.json"},"review_path_not_allowlisted")
        b = (Path(root)/p).read_bytes()
        source.require(source.sha(b)==item["annotation_sha256"],"review_proof_hash_mismatch")
        raw[p] = b;reviews[p] = source.strict_json(b)
    return raw,documents,reviews,source.load_sources(root)


def validate_review_packet(review,packet,path,schema):
    validator = jsonschema.Draft202012Validator(schema)
    source.require(not list(validator.iter_errors(review)),"review_schema")
    source.require(review["source_packet_path"]==path and review["source_packet_raw_sha256"]==source.PACKETS[path][0],"review_packet_binding")
    source.require(len(review["records"])==len(packet["records"]),"review_membership_count")
    span_count = 0
    for index,(r,s) in enumerate(zip(review["records"],packet["records"])):
        source.require(r["example_id"]==s["example_id"] and r["source_record_path"]==f"/records/{index}","review_member_order")
        source.require(r["source_record_json_sha256"]==source.sha(source.encoded(s)) and
                       r["source_input_json_sha256"]==source.sha(source.encoded(s["input"])),"review_record_hash")
        source.require(r["primary_observed"] is (r["primary_label"] in {"positive","negative"}),"primary_observed_mask")
        targets = {t["index"] for t in s["input"]["targets"]}
        for candidate in r["date_candidates"]:
            source.require(set(candidate["target_indices"])<=targets,"review_target_not_source")
            source.require(candidate["completion_observed"] is (candidate["completion"] in {"complete","unfinished"}),"completion_observed_mask")
        for span in r["evidence_spans"]+[c["source_span"] for c in r["date_candidates"]]:
            source.require(span["raw_field_path"]==f"/records/{index}/input/utterance/text","span_cross_source_member")
            source.check_span(span,packet);span_count+=1
    return span_count


def validate_lineage(lineage,source_rows):
    members = lineage["member_source_bindings"]
    source.require(len(members)==132 and len({m["example_id"] for m in members})==132,"lineage_member_count")
    source.require(set(lineage["canonical_map"])==set(source_rows),"lineage_full_canonical_closure")
    roots = {r["canonical_root_id"]:r for r in lineage["canonical_roots"]}
    source.require(len(roots)==18,"lineage_component_count")
    closure = set()
    for root,r in roots.items():
        source.require(r["member_count"]==len(r["members"]) and len(r["members"])==len(set(r["members"])),"canonical_member_duplicates")
        source.require(not closure.intersection(r["members"]),"canonical_root_overlap")
        closure.update(r["members"])
        for member in r["members"]:source.require(lineage["canonical_map"][member]==root,"canonical_map_mismatch")
    source.require(closure==set(source_rows),"canonical_missing_members")
    for m in members:
        r = source_rows[m["example_id"]]
        for key,other in (("source_packet_path","source_packet"),("source_packet_raw_sha256","source_packet_raw_sha256"),
                          ("source_record_pointer","source_record_path"),("source_record_json_sha256","source_record_json_sha256"),
                          ("source_input_json_sha256","source_input_json_sha256")):
            source.require(m[key]==r[other],"lineage_source_binding")
        source.require(m["canonical_root"]==lineage["canonical_map"][m["example_id"]],"lineage_root_binding")
    return {m["example_id"]:m for m in members},roots


def span_key(span):
    return span["raw_field_path"],span["char_start"],span["char_end"],span["text"]


def summarize_support(rows,labels):
    result = {}
    sets = {label:{r["canonical_root"] for r in rows if r["label"]==label} for label in labels}
    for label in labels:
        result[label] = {"rows":sum(r["label"]==label for r in rows),"construction_components":len(sets[label]),
                         "component_ids":sorted(sets[label])}
    if labels==("positive","negative"):
        result["additional_negative_components"] = len(sets["negative"]-sets["positive"])
        result["additional_negative_component_ids"] = sorted(sets["negative"]-sets["positive"])
    return result


def align(documents,sources):
    candidate_packet = documents["research/customer-benchmark/semantic-v6-extension/runtime-candidates.v6.json"]
    feature_packet = documents["research/customer-benchmark/semantic-v6-extension/runtime-features.v6.json"]
    lineage = documents["research/customer-benchmark/semantic-v6-extension/source-adjudicated-lineage.json"]
    row_index = {r["example_id"]:r for r in candidate_packet["rows"]}
    source.require(len(row_index)==132,"candidate_row_duplicates")
    member,roots = validate_lineage(lineage,row_index)
    features = {(r["example_id"],r["head"],r.get("candidate_id")):r for r in feature_packet["rows"]}
    feature_indices = {(r["example_id"],r["head"],r.get("candidate_id")):i for i,r in enumerate(feature_packet["rows"])}
    source.require(len(features)==len(feature_packet["rows"]),"feature_vector_duplicates")
    source.require(feature_packet["candidate_row_vector_sha256"]==source.sha(source.encoded(candidate_packet["rows"])),"feature_candidate_vector_binding")
    primary_rows,date_rows,annotation_rows = [],[],[]
    frozen_candidate_annotations = {}
    for path,review_name in zip(source.PACKETS,(
            "analysis/night-v6-adjudication.primary-packet.json","analysis/night-v6-adjudication.peer-packet.json")):
        packet,review = sources[path],documents[review_name]
        for index,(s,a) in enumerate(zip(packet["records"],review["records"])):
            row = row_index[s["example_id"]]
            root = lineage["canonical_map"][s["example_id"]]
            ancestry = not (lineage["all_independent_support_masked"] or member[s["example_id"]]["independent_support_masked"]
                            or roots[root]["independent_support_masked"])
            known_profile = row["runtime_diagnostics"].get("ingress_reason") is None and not row["runtime_diagnostics"].get("runtime_failure",False)
            primary_feature = features[(s["example_id"],"primary_is_payment_proposal",None)]
            primary_reasons = []
            if not a["primary_observed"]:primary_reasons.append("primary_ambiguous_or_unobserved")
            if not a["privacy_surface_eligible"] or not primary_feature["replay_features"]["eligible"]:primary_reasons.append("privacy_or_feature_mask")
            if not known_profile:primary_reasons.append("runtime_schema_profile_unqualified")
            if not ancestry:primary_reasons.append("independent_ancestry_support_unresolved")
            primary_rows.append({"example_id":s["example_id"],"canonical_root":root,"label":a["primary_label"],
                "annotation_pointer":f"{review_name}#/records/{index}","source_binding":{k:row[k] for k in
                    ("source_packet","source_packet_raw_sha256","source_record_path","source_record_json_sha256","source_input_json_sha256")},
                "pre_ancestry_eligible":not [r for r in primary_reasons if r!="independent_ancestry_support_unresolved"],
                "post_ancestry_eligible":not primary_reasons,"loss_mask":False,"parent_authorized":False,"mask_reasons":primary_reasons})
            annotations = a["date_candidates"]
            for j,truth in enumerate(annotations):
                exact = [c for c in row["candidates"] if span_key(c["source_span"])==span_key(truth["source_span"])]
                scoped = [c for c in exact if c["target_indices_hypothesis"] is not None and
                          set(c["target_indices_hypothesis"])==set(truth["target_indices"])]
                overlaps = [c for c in row["candidates"] if c["source_span"]["char_start"]<truth["source_span"]["char_end"] and
                            truth["source_span"]["char_start"]<c["source_span"]["char_end"]]
                status = "exact_span_and_target" if scoped else "exact_span_target_unresolved_or_mismatch" if exact else "boundary_mismatch" if overlaps else "missing"
                annotation_rows.append({"example_id":s["example_id"],"canonical_root":root,"annotation_pointer":f"{review_name}#/records/{index}/date_candidates/{j}",
                    "source_span":truth["source_span"],"target_indices":truth["target_indices"],"completion":truth["completion"],
                    "candidate_role":truth["candidate_role"],"presence":truth["presence"],"status":status,
                    "actual_candidate_ids":[c["id"] for c in (scoped or exact or overlaps)]})
            for c in row["candidates"]:
                exact = [(j,t) for j,t in enumerate(annotations) if span_key(c["source_span"])==span_key(t["source_span"])]
                scoped = [(j,t) for j,t in exact if c["target_indices_hypothesis"] is not None and
                          set(c["target_indices_hypothesis"])==set(t["target_indices"])]
                reasons = []
                if not exact:reasons.append("no_exact_reviewed_boundary")
                elif not scoped:reasons.append("target_scope_unresolved_or_mismatch")
                elif len(scoped)!=1:reasons.append("duplicate_exact_review_scope")
                picked = scoped[0] if len(scoped)==1 else None
                feature = features[(s["example_id"],"date_completion",c["id"])]
                truth = picked[1] if picked else None
                if truth:
                    if truth["presence"]!="present":reasons.append("presence_not_established")
                    if not truth["maximal_boundary_observed"]:reasons.append("maximal_boundary_unobserved")
                    if not truth["target_scope_observed"]:reasons.append("target_scope_unobserved")
                    if truth["candidate_role"]!="current":reasons.append("superseded_or_uncertain_candidate")
                    if not truth["completion_observed"] or truth["completion"] not in {"complete","unfinished"}:reasons.append("completion_unobserved")
                if not a["privacy_surface_eligible"]:reasons.append("privacy_review_mask")
                if not feature["replay_features"]["eligible"]:reasons.append("feature:"+feature["replay_features"]["reason"])
                if row["detector_status"]=="overflow":reasons.append("candidate_overflow")
                if not known_profile:reasons.append("runtime_schema_profile_unqualified")
                before = list(reasons)
                if not ancestry:reasons.append("independent_ancestry_support_unresolved")
                date_rows.append({"candidate_id":c["id"],"example_id":s["example_id"],"canonical_root":root,
                    "source_span":c["source_span"],"actual_target_hypothesis":c["target_indices_hypothesis"],
                    "annotation_pointer":None if picked is None else f"{review_name}#/records/{index}/date_candidates/{picked[0]}",
                    "label":None if not truth else truth["completion"],"reviewed_axes":truth,
                    "feature_pointer":f"research/customer-benchmark/semantic-v6-extension/runtime-features.v6.json#/rows/{feature_indices[(s['example_id'],'date_completion',c['id'])]}",
                    "feature_contract_unchanged":True,"pre_ancestry_eligible":not before,"post_ancestry_eligible":not reasons,
                    "polarity_observed":bool(truth and truth["polarity"] in {"asserted","negated","conditional","question","quoted"}),
                    "polarity_training_mask":False,
                    "reference_mask":False,"normalization_mask":False,"loss_mask":False,"parent_authorized":False,"mask_reasons":reasons})
    return {"schema_version":VERSION,"primary_rows":primary_rows,"actual_date_candidate_rows":date_rows,
            "reviewed_date_annotation_rows":annotation_rows,"canonical_components":len(roots),
            "all_masks_disabled_without_fresh_parent_admission":True,"trained":False,"qualified":False,
            "lineage_independent_support_all_masked":lineage["all_independent_support_masked"]}
