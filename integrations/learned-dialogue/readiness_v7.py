"""Actual reviewed alignment/readiness freeze only. Never a training grant."""
import io
import json
import time
import unittest
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

import alignment_v7 as alignment
import checkpoint_v6

ROOT = alignment.ROOT
OUTPUT = "research/customer-benchmark/semantic-v6-extension/reviewed-alignment.v7.json"
REPORT = "analysis/night-learned-dialogue.v7-alignment.json"


def verify_inputs():
    raw,documents,reviews,sources = alignment.load_inputs()
    schema = documents["research/customer-benchmark/semantic-v6-peer-extension/independent-review.schema.json"]
    spans = {"adjudicated":0,"original_reviews":0}
    for name,path in zip(("primary","peer"),sources):
        spans["adjudicated"] += alignment.validate_review_packet(documents[f"analysis/night-v6-adjudication.{name}-packet.json"],sources[path],path,schema)
        for rid in ("a","b"):
            spans["original_reviews"] += alignment.validate_review_packet(reviews[f"analysis/night-v6-reviewer-{rid}.{name}-packet.json"],sources[path],path,schema)
    lineage = documents["research/customer-benchmark/semantic-v6-extension/source-adjudicated-lineage.json"]
    summary = documents["analysis/night-v6-adjudication.json"]
    integrity = {i["path"]:i["raw_sha256"] for i in summary["output_integrity"]}
    for name in ("analysis/night-v6-adjudication.primary-packet.json","analysis/night-v6-adjudication.peer-packet.json",
                 "research/customer-benchmark/semantic-v6-extension/source-adjudicated-lineage.json"):
        alignment.source.require(alignment.source.sha(raw[name])==integrity[name],"adjudication_output_integrity")
    return raw,documents,reviews,sources,spans


def verify_V6_freeze(documents):
    prep=documents["analysis/night-learned-dialogue.v6-preparation.json"]
    expected=dict(prep["source_sha256"])
    expected.update({
        "analysis/night-learned-dialogue.v6-preparation.json":alignment.PINS["analysis/night-learned-dialogue.v6-preparation.json"],
        "analysis/night-learned-dialogue.v6-preparation.txt":"ac95bba65facc0860203b7bc8d6c33e59a8f80d0dbb0f19a71bba663a5c69987",
        "research/customer-benchmark/semantic-v6-extension/runtime-candidates.v6.json":alignment.PINS["research/customer-benchmark/semantic-v6-extension/runtime-candidates.v6.json"],
        "research/customer-benchmark/semantic-v6-extension/runtime-features.v6.json":alignment.PINS["research/customer-benchmark/semantic-v6-extension/runtime-features.v6.json"]})
    for path,pin in expected.items():alignment.source.require(alignment.source.sha((ROOT/path).read_bytes())==pin,"frozen_V6_artifact_changed")
    return {"files":len(expected),"all_byte_identical":True,"sha256":expected}


def assessment(joined,documents):
    primary = joined["primary_rows"]
    dates = joined["actual_date_candidate_rows"]
    truths = joined["reviewed_date_annotation_rows"]
    lineage = documents["research/customer-benchmark/semantic-v6-extension/source-adjudicated-lineage.json"]
    old = documents["analysis/night-learned-dialogue.v5.primary-readiness.json"]
    old_date = old["date"]["actual_feature_eligible_observed_support"]
    summary = {
        "rows":len(primary),"adjudicated_primary_row_labels":dict(Counter(r["label"] for r in primary)),
        "adjudicated_DATE_annotations":len(truths),"actual_DATE_detector_candidates":len(dates),
        "annotation_alignment_status":dict(Counter(r["status"] for r in truths)),
        "actual_candidate_mask_reasons":dict(Counter(reason for r in dates for reason in r["mask_reasons"])),
        "primary_mask_reasons":dict(Counter(reason for r in primary for reason in r["mask_reasons"])),
        "construction_components":joined["canonical_components"],
        "primary_pre_ancestry_construction_support":alignment.summarize_support([r for r in primary if r["pre_ancestry_eligible"]],("positive","negative")),
        "DATE_pre_ancestry_construction_support":alignment.summarize_support([r for r in dates if r["pre_ancestry_eligible"]],("complete","unfinished")),
        "primary_post_all_masks_support":alignment.summarize_support([r for r in primary if r["post_ancestry_eligible"]],("positive","negative")),
        "DATE_post_all_masks_support":alignment.summarize_support([r for r in dates if r["post_ancestry_eligible"]],("complete","unfinished")),
        "primary_pre_ancestry_row_pointers":[r["annotation_pointer"] for r in primary if r["pre_ancestry_eligible"]],
        "DATE_pre_ancestry_candidate_pointers":[{"candidate_id":r["candidate_id"],"annotation":r["annotation_pointer"],"feature":r["feature_pointer"]}
                                                for r in dates if r["pre_ancestry_eligible"]],
        "old_V5_separate":{"source_report_raw_sha256":alignment.PINS["analysis/night-learned-dialogue.v5.primary-readiness.json"],
                          "primary_rows":old["feature_eligible_rows"],"primary_positive_groups":old["positive_groups"],
                          "primary_additional_negative_groups":old["additional_negative_groups"],
                          "date_complete_groups":old_date["complete"]["groups"],"date_unfinished_groups":old_date["unfinished"]["groups"],
                          "fit_calls":0,"old_grant_reused":False,"new_groups_added":0,"combined_support_computed":False},
        "lineage":{"all_members":len(lineage["member_source_bindings"]),"all_independent_support_masked":lineage["all_independent_support_masked"],
                    "peer_pairs_accounted":len(lineage["peer_potential_alias_pair_decisions"]),
                    "possible_old_TRAIN_links":len(lineage["possible_known_old_train_aliases"]),
                    "possible_old_links_unioned_as_proven":False,"global_registry_closure":lineage["global_external_registry_closure"]},
        "floor":20,"extension_standalone_deficits":{"primary_positive":20,"primary_additional_negative":20,"DATE_complete":20,"DATE_unfinished":20},
        "pre_ancestry_only_hypothetical_standalone_deficits":{"primary_positive":12,"primary_additional_negative":11,"DATE_complete":15,"DATE_unfinished":15,
            "scope":"Diagnostic only if existing ancestry masks were independently resolved in a new version; masks stay in force."},
        "old_V5_lower_bound_additional_eligible_disjoint_support":{"primary_additional_negative":1,"DATE_unfinished":4,
            "condition":"Only after new source/ancestry/schema/feature admission and confirmed disjointness; current V6 contributes zero."},
        "new_parent_admission_required":True,"parent_validation_claimed_complete":False,"cpu_fit_ready":False,
        "all_runtime_outputs_abstain":True,"accepted_outputs":0,"fit_calls":0,"new_DEV_read":False,"GPU_calls":0,
        "human_gold_rows":0,"iid_gold_rows":0,"qualified":False,"payment_authority":False,
        "math_and_collection_request":[
            "Source-adjudicated semantic counts do not establish independent engineering group support; reconcile old/new ancestry without renaming roots.",
            "Current 18 conservative construction components cannot alone supply20 groups/class even before independence masks.",
            "Collect genuinely different source-neutral constructions, not more renamed variants of these18 families; preserve all paired/mixed members.",
            "For each collected unfinished DATE, independently define maximal expression, current role and exact target set before detector join.",
            "Fix unsupported source profiles or detectors only as NEW reviewed versions, then refreeze; never rewrite this corpus or labels to raise counts.",
            "Polarity and linguistic completion remain separate; quoted/negated/conditional expressions are not automatically unfinished.",
            "Resolve input schema/security/source eligibility and aliases, then obtain a fresh exact parent grant; no V7 fitting occurs."]}
    return summary


def write_new(path,value):
    raw=json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode("utf-8")+b"\n"
    with (ROOT/path).open("xb") as f:f.write(raw)
    return alignment.source.sha(raw)


def main():
    started=time.perf_counter()
    historical=checkpoint_v6.verify_history()
    raw,docs,reviews,sources,spans=verify_inputs()
    V6_preserved=verify_V6_freeze(docs)
    joined=alignment.align(docs,sources)
    report=assessment(joined,docs)
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.discover(str(ROOT/"integrations/learned-dialogue"),pattern="test_v7.py")
    tests=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    alignment.source.require(tests.wasSuccessful(),stream.getvalue())
    source_hashes={str(p.relative_to(ROOT)).replace("\\","/"):alignment.source.sha(p.read_bytes()) for p in
        (Path(alignment.__file__),Path(__file__),ROOT/"integrations/learned-dialogue/test_v7.py")}
    original_sources={p:v[0] for p,v in alignment.source.PACKETS.items()}
    joined.update({"input_raw_sha256":{p:alignment.source.sha(b) for p,b in raw.items()},"source_raw_sha256":original_sources,
                  "source_sha256":source_hashes,"review_schema_sha256":alignment.PINS["research/customer-benchmark/semantic-v6-peer-extension/independent-review.schema.json"]})
    alignment_sha=write_new(OUTPUT,joined)
    report.update({"schema_version":alignment.VERSION,"utc":datetime.now(timezone.utc).isoformat(),
        "input_raw_sha256":joined["input_raw_sha256"],"source_raw_sha256":original_sources,"source_sha256":source_hashes,
        "exact_validated_span_occurrences":spans,"historical_preservation":historical,
        "frozen_V6_preservation":V6_preserved,
        "reviewed_alignment_artifact":{"path":OUTPUT,"raw_sha256":alignment_sha},
        "tests":{"passed":tests.testsRun,"failures":len(tests.failures),"errors":len(tests.errors),"log":stream.getvalue()},
        "CPU_seconds":time.perf_counter()-started,
        "role_provenance":"Parent proof records two isolated source reviewers; distinct source adjudicator reads labels. Received proofs bind bytes, not global isolation, semantic correctness or parent CPU authorization."})
    alignment.source.require(checkpoint_v6.verify_history()==historical,"historical_drift_after_alignment")
    alignment.source.require(verify_V6_freeze(docs)==V6_preserved,"V6_drift_after_alignment")
    report_sha=write_new(REPORT,report)
    lines=["V7 reviewed alignment/readiness ONLY; no CPU fit/grant/DEV/GPU.",
        "Primary132 rows:"+json.dumps(report["adjudicated_primary_row_labels"]),
        "DATE101 reviewed annotations against105 actual detector candidates:"+json.dumps(report["annotation_alignment_status"]),
        "Pre-ancestry primary construction support:"+json.dumps(report["primary_pre_ancestry_construction_support"]),
        "Pre-ancestry DATE construction support:"+json.dumps(report["DATE_pre_ancestry_construction_support"]),
        "Post ancestry/schema/privacy masks:0 usable extension primary/DATE groups; all132 ancestry contributions masked.",
        "OldV5 stays separate103rows27positive/19additionalnegative;DATE20complete/16unfinished. No old grant reuse, no additive independent-support claim.",
        "Peer60unknown_schema unchanged; exact target/boundary/current/presence masks retained; no oracle features.",
        f"{tests.testsRun} checks passed; exact adjudicated spans:{spans['adjudicated']}; original review span occurrences:{spans['original_reviews']}.",
        "Alignment SHA256:"+alignment_sha,"Report SHA256:"+report_sha,*report["math_and_collection_request"]]
    txt_path=ROOT/"analysis/night-learned-dialogue.v7-alignment.txt"
    with txt_path.open("x",encoding="utf-8",newline="\n") as f:f.write("\n".join(lines)+"\n")
    freeze={"schema_version":"reviewed_alignment_freeze.v7","source_sha256":source_hashes,
        "artifacts_sha256":{OUTPUT:alignment_sha,REPORT:report_sha,str(txt_path.relative_to(ROOT)).replace("\\","/"):alignment.source.sha(txt_path.read_bytes())},
        "frozen_V6_preparation_sha256":alignment.PINS["analysis/night-learned-dialogue.v6-preparation.json"],
        "historical_preservation":historical,"input_raw_sha256":report["input_raw_sha256"],
        "frozen_V6_preservation":V6_preserved,
        "fit_calls":0,"cpu_authorization_issued":False,"qualified":False}
    freeze_sha=write_new("analysis/night-learned-dialogue.v7-alignment.freeze.json",freeze)
    print(json.dumps({"primary":report["adjudicated_primary_row_labels"],"alignment":report["annotation_alignment_status"],
        "pre_ancestry_primary":report["primary_pre_ancestry_construction_support"],"pre_ancestry_DATE":report["DATE_pre_ancestry_construction_support"],
        "post_all_masks_usable_groups":0,"tests":tests.testsRun,"span_counts":spans,"CPU_seconds":report["CPU_seconds"],
        "alignment_sha256":alignment_sha,"report_sha256":report_sha,"freeze_sha256":freeze_sha}))


if __name__=="__main__":main()
