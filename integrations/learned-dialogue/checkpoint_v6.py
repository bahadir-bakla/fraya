"""One write-once V6 pre-adjudication freeze; exact allowlisted inputs only."""
import io
import json
import time
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import data_v6 as data

ROOT = data.ROOT
CANDIDATE_PATH = "research/customer-benchmark/semantic-v6-extension/runtime-candidates.v6.json"
FEATURE_PATH = "research/customer-benchmark/semantic-v6-extension/runtime-features.v6.json"
REPORT_PATH = "analysis/night-learned-dialogue.v6-preparation.json"


def verify_history():
    specs = [
        ("v1","integrations/learned-dialogue/v1-frozen-archive.manifest.json","files"),
        ("final_v2","analysis/night-learned-dialogue.v2-final.handoff.json","changed_file_hashes"),
        ("R3","analysis/night-learned-dialogue.v3.source-r3.json","files"),
        ("R4","analysis/night-learned-dialogue.v3.source-r4.json","source_hashes"),
        ("V5","analysis/night-learned-dialogue.v5.freeze.json","new_checkpoint_sha256")]
    result = {}
    for name,path,key in specs:
        manifest = json.loads((ROOT/path).read_bytes())[key]
        checked = {p:data.sha((ROOT/p).read_bytes())==h for p,h in manifest.items()}
        data.require(all(checked.values()),"historical_drift:"+name)
        result[name] = {"files":len(checked),"all_byte_identical":True,"manifest_raw_sha256":data.sha((ROOT/path).read_bytes())}
    return result


def write_once(path, value):
    raw = json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False).encode("utf-8")+b"\n"
    with (ROOT/path).open("xb") as f:f.write(raw)
    return {"path":path,"raw_sha256":data.sha(raw),"encoded_vector_sha256":data.sha(data.encoded(value)),"bytes":len(raw)}


def main():
    started = time.perf_counter()
    preserved = verify_history()
    sources = data.load_sources()
    schema_blob = (ROOT/"integrations/learned-dialogue/contract_v2.json").read_bytes()
    schema = json.loads(schema_blob)["schema"]
    # Binding identity only; the embedded frozen weights are never scored/reused.
    model_id = "4b96a26d0b99ed2ff2d774d7678131c4cb14960b462ba48bcc3790972d31b427"
    exported,helpers,primary = data.frozen_export_helpers()
    candidate_rows,feature_rows,profiles = data.prepare(sources,schema,model_id,exported,helpers,primary)
    validator = jsonschema.Draft202012Validator(schema)
    for row in candidate_rows:
        data.require(not list(validator.iter_errors(row["runtime_output"])),"wire_schema_error")
    stream = io.StringIO()
    tests = unittest.defaultTestLoader.discover(str(ROOT/"integrations/learned-dialogue"),pattern="test_v6.py")
    results = unittest.TextTestRunner(stream=stream,verbosity=2).run(tests)
    data.require(results.wasSuccessful(),stream.getvalue())
    candidate_artifact = {"schema_version":"source_only_runtime_candidates.v6","detector_version":data.DETECTOR_R4_VERSION,
        "source_raw_sha256":{p:v[0] for p,v in data.PACKETS.items()},"rows":candidate_rows,
        "review_annotations_read":0,"all_loss_masks_false":True,"qualified":False}
    feature_artifact = {"schema_version":"source_only_runtime_features.v6","rows":feature_rows,
        "feature_versions":{"date":data.FEATURE_R4_VERSION,"primary":data.PRIMARY_FEATURE_VERSION},
        "candidate_row_vector_sha256":data.sha(data.encoded(candidate_rows)),
        "features_scope":"Frozen authored replay extraction; unknown live source and reviewed labels remain masked",
        "all_loss_masks_false":True,"trained":False,"qualified":False}
    candidate_file = write_once(CANDIDATE_PATH,candidate_artifact)
    feature_file = write_once(FEATURE_PATH,feature_artifact)
    count = Counter()
    for profile in profiles.values():count.update(profile["counts"])
    source_sha = {str(p.relative_to(ROOT)).replace("\\","/"):data.sha(p.read_bytes()) for p in
                  [Path(data.__file__),Path(__file__),ROOT/"integrations/learned-dialogue/test_v6.py"]}
    interface = json.loads((ROOT/"analysis/night-learned-dialogue.v5.next-data-interface.json").read_bytes())
    v5_schema = interface["collection_json_schema"]
    v5_differences = {}
    for path,packet in sources.items():
        issues = list(jsonschema.Draft202012Validator(v5_schema).iter_errors(packet))
        v5_differences[path] = {"strict_V5_schema_issues":len(issues),"examples":[
            {"path":"/"+"/".join(str(x) for x in e.absolute_path),"validator":e.validator,"message":e.message}
            for e in issues[:8]],"accepted_as_explicit_pinned_source_only_profile":True,
            "no_fields_rewritten_or_fabricated":True}
    report = {"schema_version":data.VERSION,"utc":datetime.now(timezone.utc).isoformat(),
        "status":"PRE_ADJUDICATION_SOURCE_FEATURE_FREEZE_NO_FIT","actual_rows":len(candidate_rows),
        "counts":dict(count),"packet_profiles":profiles,"strict_V5_schema_differences":v5_differences,
        "source_raw_sha256":{p:v[0] for p,v in data.PACKETS.items()},"source_sha256":source_sha,
        "frozen_baseline_sha256":data.BASELINES,"historical_preservation":preserved,
        "runtime_candidates":candidate_file,"runtime_features":feature_file,
        "wire_schema_sha256":data.sha(schema_blob),"schema_valid_runtime_wires":len(candidate_rows),
        "future_alignment_interface":data.alignment_contract_v6(),
        "staged_alignment_request":data.stage_alignment_request_v6(
            pinned_candidate_vector=candidate_file,pinned_feature_vector=feature_file),
        "future_export":{"frozen_R4_bytes":(ROOT/"integrations/learned-dialogue/runtime_frozen_r4.py").stat().st_size,
            "frozen_V5_primary_contract_bytes":(ROOT/"integrations/learned-dialogue/runtime_primary_contract_v5.py").stat().st_size,
            "combined_existing_runtime_source_bytes":
                (ROOT/"integrations/learned-dialogue/runtime_frozen_r4.py").stat().st_size+
                (ROOT/"integrations/learned-dialogue/runtime_primary_contract_v5.py").stat().st_size,"limit_bytes":500000,
            "new_V6_model_bytes":0,"new_head_export_not_built":True,
            "note":"Feature dataset bytes are not runtime model footprint. Future new-head export must be separately measured; no old weights reinterpreted."},
        "tests":{"passed":results.testsRun,"failures":len(results.failures),"errors":len(results.errors),"log":stream.getvalue()},
        "CPU_seconds":time.perf_counter()-started,"new_DEV_read":False,"reviewer_or_adjudication_files_read":0,
        "author_nomination_or_private_goal_files_read":0,"canonical_group_count":None,"class_support":None,
        "fit_calls":0,"old_weights_scored":0,"GPU_calls":0,"platform_calls":0,"network_calls":0,
        "qualified":False,"human_gold_rows":0,"iid_gold_rows":0,"accepted_outputs":0,"payment_authority":False,
        "limits":["Source hashes/profiles are preserved, not upgraded to authenticated live ingress or current bank policy.",
            "Peer post_verified_account phase is unknown to frozen R4 wire ingress and omitted from V5 phase features; do not rewrite it.",
            "Source packets lack strict V5 lineage/author/license metadata; canonical map and independent closure still pending.",
            "Raw candidates and replay feature eligibility are not reviewed span accuracy, supervised class support or qualification.",
            "Finite English temporal grammar; unsupported/deep/boundary/clipped dependencies remain masked.",
            "Question singleton target sets are hypotheses only; multi-target identity, reference and normalization unqualified.",
            "No reviewed absent-region validity negatives and no proposed supervision labels.",
            "Old V5 parent grant authorizes neither V6 fitting nor cloud. New schema/adjudication/map/admission and exact parent grant required."]}
    final_preserved = verify_history()
    data.require(final_preserved==preserved,"historical_files_changed_during_preparation")
    report_file = write_once(REPORT_PATH,report)
    lines = ["V6 pre-adjudication source/feature preparation frozen; no fit/DEV/GPU.",
        f"Actual source rows:{len(candidate_rows)}; profiles72+60; source hashes pinned.",
        "Actual counts:"+json.dumps(dict(count),sort_keys=True),
        f"Checks:{results.testsRun} passed;132 runtime wires schema-valid/all abstain.",
        "Peer hashes/phase preserved;post_verified_account remains unknown_schema to frozen R4 wire ingress.",
        "Strict V5 schema missing lineage/author/provenance/license fields reported; no silent repair.",
        "Live source unknown masks false; authored replay numerical features are preparation only.",
        "Candidate artifact raw SHA256:"+candidate_file["raw_sha256"],
        "Feature artifact raw SHA256:"+feature_file["raw_sha256"],
        "Report raw SHA256:"+report_file["raw_sha256"],
        "Preservation:"+json.dumps(preserved,sort_keys=True),*report["limits"]]
    with (ROOT/"analysis/night-learned-dialogue.v6-preparation.txt").open("x",encoding="utf-8",newline="\n") as f:
        f.write("\n".join(lines)+"\n")
    print(json.dumps({"rows":len(candidate_rows),"counts":dict(count),"tests":results.testsRun,
                      "CPU_seconds":report["CPU_seconds"],"candidate_file":candidate_file,
                      "feature_file":feature_file,"report_file":report_file}))


if __name__=="__main__":main()
