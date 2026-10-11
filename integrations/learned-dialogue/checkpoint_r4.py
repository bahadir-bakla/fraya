"""Freeze TRAIN-first R4 source/engineering checks. NEW DEV IS NEVER OPENED."""
import ast
import hashlib
import io
import json
import time
import unittest
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
import jsonschema
import test_r4
from test_v3 import BUNDLE,SCHEMA
from build_data import freeze,encoded
from vector_checks_v3 import adapt
from detector_v3 import detect_candidates_v3
from detector_r4 import detect_candidates_r4,DETECTOR_R4_VERSION
from window_r4 import date_features_r4,score_date_r4,FEATURE_R4_VERSION
from alignment_r4 import align_date_r4
from context_r4 import predict_r4
from export_r4 import export_r4

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]
TRAIN_PATH=ROOT/"research/customer-benchmark/semantic-v3-collection/label-free-date-review-packet.json"

def sha(blob): return hashlib.sha256(blob).hexdigest()

def frozen_check_r4():
    count=0
    manifests=[json.loads((HERE/"v1-frozen-archive.manifest.json").read_bytes())["files"],
               json.loads((ROOT/"analysis/night-learned-dialogue.v2-final.handoff.json").read_bytes())["changed_file_hashes"],
               json.loads((ROOT/"analysis/night-learned-dialogue.v3.source-r3.json").read_bytes())["files"]]
    for hashes in manifests:
        for name,digest in hashes.items():
            if sha((ROOT/name).read_bytes())!=digest: raise ValueError("Frozen source drift:"+name)
            count+=1
    return count

def source_from_trusted_r4(t):
    return {"call_local_id":t.call_local_id,"source_event_id":t.source_event_id,"event_ordinal":t.event_ordinal,"text":t.text,
            "complete_transport":True,"question_identity":list(t.question_identity),"target_mapping":[list(x) for x in t.target_mapping]}

def main():
    started=time.perf_counter(); original_preserved=frozen_check_r4()
    docs={str(path.relative_to(ROOT)).replace("\\","/"):sha(path.read_bytes()) for path in [
        ROOT/"analysis/learned-layer-design.checkpoint08-detector.json",
        ROOT/"analysis/learned-layer-design.checkpoint08-detector.txt",
        ROOT/"analysis/learned-layer-design.json",ROOT/"analysis/learned-layer-design.txt",
        ROOT/"research/customer-benchmark/learned-layer-label-spec.json",
        ROOT/"analysis/learned-layer-evaluation-plan.json"]}
    suite=unittest.defaultTestLoader.loadTestsFromModule(test_r4); stream=io.StringIO()
    checks=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    if not checks.wasSuccessful(): raise ValueError(stream.getvalue())
    packet_blob=TRAIN_PATH.read_bytes(); packet=json.loads(packet_blob); train=packet["records"]
    if len(train)!=72 or any("labels" in row or "annotation" in row for row in train): raise ValueError("Label-free TRAIN packet contract mismatch")
    train_obs=[]; counts=Counter(); raw_groups=set(); eligible_groups=set()
    for row in train:
        s=row["input"]; text=s["utterance"]["text"]
        legacy=detect_candidates_v3(text,s["question"]["role"],s["targets"])
        proposed=detect_candidates_r4(text,s["question"]["role"],s["targets"])
        raw_groups.update([row["canonical_group_id"]] if proposed["candidates"] else [])
        counts["R3_rows_with_DATE"]+=int(any(c["kind"]=="date" for c in legacy["candidates"]))
        counts["R4_rows_with_DATE"]+=int(bool(proposed["candidates"]))
        engineering=align_date_r4(s,proposed,[],test_r4.ADMISSION_R4)
        actual_admission=align_date_r4(s,proposed,[],None)
        for aligned in engineering["rows"]:
            counts["syntax:"+aligned["candidate"]["syntax_status"]]+=1
            counts["engineering_window_eligible_candidates"]+=int(aligned["features"]["eligible"])
            if aligned["features"]["eligible"]: eligible_groups.add(row["canonical_group_id"])
        if any(r["completion_mask"] or r["validity_mask"] for r in actual_admission["rows"]): raise ValueError("Review gate accidentally opened")
        train_obs.append({"id":row["example_id"],"canonical_group":row["canonical_group_id"],"raw_source":text,
                          "actual_candidates":proposed["candidates"],"nondate_candidates":proposed.get("nondate_candidates",[]),
                          "engineering_feature_bounds":[r["features"].get("window_bounds") for r in engineering["rows"]],
                          "source_annotations_read":0,"independent_gold":False,"actual_training_masks":False,
                          "candidate_boundary_semantics_unadjudicated":True,"reviewed_exact_span_recall":None})
    exported=export_r4(BUNDLE,SCHEMA); env={}
    exec(compile(exported,"r4-generated-runtime","exec"),env); embedded=env["predict_context_r4_embedded"]
    vectors_path=ROOT/"analysis/learned-layer-design.checkpoint07-vectors.json"
    vectors=json.loads(vectors_path.read_bytes())["vectors"]; vector_obs=[]; parity=0
    semantic=Counter(); validator=jsonschema.Draft202012Validator(SCHEMA)
    with patch("builtins.open",side_effect=AssertionError("I/O")),patch("socket.socket",side_effect=AssertionError("network")),patch("subprocess.Popen",side_effect=AssertionError("process")):
        for vector in vectors:
            s=vector["input_snapshot"]; t,r,p=adapt(vector)
            if t is None:
                try: embedded(s,None,None,r,p)
                except Exception as exc:
                    if type(exc).__name__!="InputRejected": raise
                else: raise ValueError("Absent binding failed to reject")
                vector_obs.append({"id":vector["id"],"guard":"InputRejected","semantic_not_exercised":True}); parity+=1; continue
            # Engineering fixture admission only, not source authentication or
            # reviewed collection admission. No expected annotation enters input.
            native=predict_r4(s,t,r,p,SCHEMA,test_r4.ADMISSION_R4)
            generated=embedded(s,t.binding_context.binding(),source_from_trusted_r4(t),r,p,test_r4.ADMISSION_R4)
            if native!=generated: raise ValueError("Export parity:"+vector["id"])
            parity+=1; wire,side=native
            if list(validator.iter_errors(wire)) or wire["status"]!="abstain": raise ValueError("Wire guard:"+vector["id"])
            proposed=side.get("detector",{}).get("candidates",[])
            assertions=[]
            for truth in vector.get("semantic_expected",{}).get("components",[]):
                if truth.get("component")!="date":
                    semantic["other_component_axes_not_exercised"]+=1; continue
                span=truth["evidence"]; match=next((c for c in proposed if c["kind"]=="date" and (c["start"],c["end"])==(span["start"],span["end"])),None)
                expected=truth.get("linguistic_completion")
                observed=None if match is None else {"closed":"complete","open":"unfinished"}.get(match["syntax_status"])
                # This measures deterministic engineering hint agreement, not
                # learned semantic success or adjudicated TRAIN truth.
                state="match" if observed==expected and observed is not None else ("detector_miss_or_boundary" if match is None else "mismatch_or_unsupported")
                semantic["DATE_syntax_hint:"+state]+=1
                assertions.append({"source_span":span,"expected_spec_completion":expected,"actual_syntax_hint":observed,"state":state,
                                   "polarity_target_reference_normalization_not_exercised":True})
            vector_obs.append({"id":vector["id"],"schema_valid":True,"all_abstain":True,"DATE_semantic_engineering_assertions":assertions,
                               "actual_candidates":proposed,"primary_act_polarity_target_unqualified":True})
        # Same shared function numerical score+eligibility parity using a literal
        # test head; no collection label fit or model replacement.
        s=vectors[0]["input_snapshot"]; t,r,p=adapt(vectors[0])
        candidate=detect_candidates_r4(s["utterance"]["text"],s["question"]["role"])["candidates"][0]
        features=date_features_r4(s,candidate,test_r4.ADMISSION_R4)
        keys=sorted(features["features"])[:3]
        literal_head={"feature_version":FEATURE_R4_VERSION,"detector_version":DETECTOR_R4_VERSION,
                      "vocabulary":keys,"head":{"bias":.125,"weights":{key:.25 for key in keys}}}
        native=predict_r4(s,t,r,p,SCHEMA,test_r4.ADMISSION_R4,literal_head)
        generated=embedded(s,t.binding_context.binding(),source_from_trusted_r4(t),r,p,test_r4.ADMISSION_R4,literal_head)
        if native!=generated: raise ValueError("Numeric shared scorer parity")
        numeric_score=native[1]["date_scores"][0]["raw_score"]
    runtime=HERE/"runtime_frozen_r4.py"; freeze(runtime,exported)
    files=("detector_r4.py","window_r4.py","alignment_r4.py","context_r4.py","export_r4.py","test_r4.py","checkpoint_r4.py","runtime_frozen_r4.py")
    source_hashes={str((HERE/name).relative_to(ROOT)).replace("\\","/"):sha((HERE/name).read_bytes()) for name in files}
    report={"utc":datetime.now(timezone.utc).isoformat(),"status":"TRAIN_FIRST_SOURCE_FREEZE_ALL_ABSTAIN",
            "detector_version":DETECTOR_R4_VERSION,"feature_version":FEATURE_R4_VERSION,"feature_cap":384,"window_each_side_codepoints":48,
            "checks":{"passed":checks.testsRun,"failed":len(checks.failures),"errors":len(checks.errors),"log":stream.getvalue()},
            "CPU_seconds":time.perf_counter()-started,"export_bytes":len(exported),"runtime_imports":["json","re"],
            "vector_native_export_parity":parity,"literal_test_head_numeric_parity":numeric_score,"no_dataset_head_fit":True,
            "source_hashes":source_hashes,"contract_hashes":docs,"wire_schema_sha256":sha((HERE/"contract_v2.json").read_bytes()),
            "frozen_source_preservation":{"v1":26,"final_v2":26,"R3":11,"checked_hashes":original_preserved,"byte_identical":True},
            "TRAIN":{"label_free_packet_sha256":sha(packet_blob),"rows":len(train),"canonical_groups":len({r["canonical_group_id"] for r in train}),
                     "counts":dict(counts),"groups_with_raw_proposed_DATE":len(raw_groups),"groups_with_engineering_eligible_window":len(eligible_groups),
                     "actual_reviewed_CLASS_group_counts":None,"actual_reviewed_completion_masks":0,"actual_source_annotations_read":0,
                     "reviewed_span_recall_precision":None,"raw_candidate_coverage_is_NOT_annotated_recall_or_class_floor":True,"observations":train_obs},
            "spec_vectors":{"sha256":sha(vectors_path.read_bytes()),"rows":len(vectors),"DATE_hint_assertion_counts":dict(semantic),"observations":vector_obs,
                            "scope":"Engineering spec hint assertions only; no qualified learned semantics; remaining axes honestly not exercised"},
            "new_DEV":{"contents_read":False,"evaluated":False,"source_must_freeze_before_separate_declared_diagnostic":True},
            "R4_pilot_preserved":{"report_sha256":sha((HERE/"source_pilot_r4.json").read_bytes()),"source_archive_sha256":sha((HERE/"source_pilot_r4.zip").read_bytes())},
            "R4_guard_pilot_preserved":{"report_sha256":sha((HERE/"source_guards_pilot_r4.json").read_bytes()),"source_archive_sha256":sha((HERE/"source_guards_pilot_r4.zip").read_bytes())},
            "Opus_R3_source_semantic_repairs":{"audit_sha256":sha((ROOT/"analysis/night-opus-learned-v3-r3.json").read_bytes()),
                "unknown_scoped_new_terms_blocks_current_reference":True,"all_wire_readback_candidates_null_until_semantic_producer_qualified":True,
                "security_phase_or_field_masks_surface":True,"cross_clause_candidates_and_clipped_scope_masked":True,"clipping_not_unfinished_label":True,
                "Modal_files_not_changed_or_exercised":True},
            "gate":{"all_abstain":True,"review_admission":False,"TRAIN_fit":False,"GPU_jobs":0,"platform_calls":0,"normalization_capability":False},
            "known_limits":["No actual adjudicated source annotations read: exact-span recall, false candidates and per-class support unavailable",
                            "Temporal grammar finite/English; arbitrary event relations, deep dependency, cross-clause scope unsupported",
                            "Generic temporal nouns/months remain unqualified hypotheses; boundary conventions need independent adjudication",
                            "48codepoint clipping masks scope, source privacy/continuation need independently supplied evidence",
                            "No primary/target/act-completion/polarity/normalization capability added; never reuse old heads with new feature contract"]}
    path=ROOT/"analysis/night-learned-dialogue.v3.source-r4.json"; freeze(path,encoded(report))
    print(json.dumps({"path":str(path),"sha256":sha(path.read_bytes()),"tests":checks.testsRun,"export_bytes":len(exported),
                      "TRAIN":{k:v for k,v in report["TRAIN"].items() if k!="observations"},"spec_counts":dict(semantic)},indent=2))

if __name__=="__main__": main()
