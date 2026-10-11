"""Freeze an offline adapter handoff; never trains, prepares data or calls cloud."""
import ast
import io
import json
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from modal_narrow_core import canonical, digest, admission
from modal_narrow_metadata import sdk_report
from modal_narrow_app import create_app, REMOTE_FILES, PINS
import modal_narrow_tests

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent


def main():
    v1=json.loads((HERE/"v1-frozen-archive.manifest.json").read_text())
    final=json.loads((ROOT/"analysis/night-learned-dialogue.v2-final.handoff.json").read_text())
    preservation={"v1":{},"v2_final":{}}
    for family, hashes in (("v1",v1["files"]),("v2_final",final["changed_file_hashes"])):
        for name, expected in hashes.items():
            actual=digest((ROOT/name).read_bytes())
            if actual != expected: raise ValueError("Frozen file drift: "+name)
            preservation[family][name]=actual
    archive=digest((HERE/"v1-frozen-archive.zip").read_bytes())
    if archive != v1["archive_sha256"]: raise ValueError("Archive drift")
    stream=io.StringIO()
    suite=unittest.defaultTestLoader.loadTestsFromModule(modal_narrow_tests)
    started=time.perf_counter()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    elapsed=time.perf_counter()-started
    if not result.wasSuccessful(): raise ValueError(stream.getvalue())
    paths=sorted(HERE.glob("modal_narrow*"))
    for path in paths:
        if path.suffix==".py": ast.parse(path.read_text())
    app,function=create_app(120)
    if app.app_id is not None: raise ValueError("Unexpected remote app identity")
    budget_path=ROOT/"local-runs/autonomous-rd/modal-budget.json"
    budget_blob=budget_path.read_bytes()
    budget=json.loads(budget_blob.decode("utf-8-sig"))
    design_blob=(ROOT/"analysis/learned-layer-design.json").read_bytes()
    design=json.loads(design_blob.decode("utf-8-sig"))
    counts=design["v3_lineage_review_contract"]["counts"]
    model_blob=(HERE/"modal_narrow_model.json").read_bytes()
    report={"utc":datetime.now(timezone.utc).isoformat(),"status":"OFFLINE_ADAPTER_COMPLETE; ACTUAL_DATA_AND_CLOUD_NO_GO",
            "checks":{"passed":result.testsRun,"failed":len(result.failures),"errors":len(result.errors),"seconds":elapsed,"output":stream.getvalue()},
            "sdk":sdk_report(),"real_sdk_app_constructed_offline":True,"remote_app_id":None,"remote_cloud_calls":0,
            "teacher":{"implemented":"pinned frozen multilingual E5, masked group-average binary head; TRAIN-only probabilities",
                       "trained_on_actual_data":False,"train_metrics":None,"dev_metrics":None,"qualification_metrics":None,
                       "encoder_fine_tuning":False,"reason":"Checkpoint05 first hypothesis forbids encoder fine tuning", "weights_downloaded":False,
                       "CPU_feasibility_measured":False,"CPU_first_utility":"modal_narrow_cpu_trial.py; full corpus <=300s prefers CPU/skip GPU"},
            "current_data_readiness":counts,"user_strict_adapter_class_floor":{"positive":21,"additional_negative":20,"engineering_only":True},
            "review_gate":"Two verified blind non-author annotations per closure member plus independently evidenced parent adjudication; canonical unions and TRAIN/dev disjointness",
            "current_missing_gates":["82-row canonical closure includes missing CSv2-E-0073", "verified two-blind-review evidence and final parent adjudication overlay", ">=21 reviewed canonical positive groups and >=20 additional negatives", "frozen reviewed dev plus exact CPU/phase comparisons", "v3 reference/detector controls; current frozen v2 failures cannot pass", "CPU encoder cost/benefit measurement", "parent reviewed dependency image and authenticated cancellation/stop evidence", "parent atomic <=$10 reservation bound to global ledger and exact payload/code"],
            "sources":{"model_manifest_sha256":digest(model_blob),"model":json.loads(model_blob),
                       "designer_version":design["document_version"],"designer_sha256":digest(design_blob),
                       "original_train_sha256":digest((HERE/"v2-final-data/train.json").read_bytes()),
                       "dev_uploaded":False,"holdout_read_or_uploaded":False,"new_annotation_authored":False},
            "image_allowlist":list(REMOTE_FILES),"dependencies":list(PINS),"dependency_versions_verified_on_official_pypi":True,
            "resources":{"gpu":"H100; automatic H200 upgrade same H100 price", "gpu_source":"https://modal.com/docs/guide/gpu",
                         "max_gpus":1,"cpu_request_limit":2,"host_memory_request_limit_mib":16384,"VRAM_process_cap_gib":24,"ephemeral_disk_mib":2048,
                         "automatic_retries":0,"max_containers":1,"min_and_buffer_containers":0,"single_use":True,"services_secrets_volumes_cron":False,
                         "startup_seconds":240,"shutdown_reserve_seconds":60,"compute_cap_smoke_primary": [120,1800],
                         "total_wall_smoke_primary": [420,2100],"absolute_stop_utc":"2026-10-11T06:13:01Z",
                         "function_timeout_not_total_wall":"https://modal.com/docs/guide/timeouts",
                         "posted_conservative_resource_usd_per_second":.001261+2*.0000131+16*.00000222,
                         "all_three_invocation_4620s_illustration_usd":4620*(.001261+2*.0000131+16*.00000222),
                         "reservation_usd":10,"build_storage_egress_other_reserve_minimum_usd":1,
                         "effective_account_rates_require_parent":True,"global_target_hard_usd":[30,35],
                         "credit_balance_claimed":False},
            "cancel":"Bounded exact fc-ID cancel with terminate_containers + CLI stop exact ap-ID; separately parse CLI app list state=stopped/tasks=0. Unknown/missing/stopping never stop proof. Parent confirms/reconciles before releasing reservation.",
            "global_budget":{"raw_snapshot_sha256":digest(budget_blob),"actual_task_cost_usd":budget["actual_task_cost_usd"],"reservations":len(budget["reservations"]),"invocations":len(budget["invocations"]),"modified":False},
            "closed_dry_run":admission(b"",budget,{},datetime.now(timezone.utc)),
            "preservation":{"v1_files":len(preservation["v1"]),"v2_final_files":len(preservation["v2_final"]),"all_byte_identical":True,"v1_archive_sha256":archive},
            "changed_files":{str(p.relative_to(ROOT)).replace('\\','/'):digest(p.read_bytes()) for p in paths if p.is_file()},
            "no_live_Freya_permission_runtime_policy_or_platform_changes":True}
    if digest(budget_path.read_bytes()) != digest(budget_blob): raise ValueError("Parent ledger changed during checkpoint; retry read only")
    report["supersedes_historical_adapter_report"]="analysis/night-learned-dialogue.v3.modal-adapter.json"
    report["source_view_corrections"]={"actual_targets_index_nested_pending":True,"lexical_delex_before_typed_serialization":True,
                                       "reviewed_value_free_admission_before_text_hash":True,"source_maps_original_unicode_offsets":True,
                                       "exact_TRAIN_logits_for_distillation":True,"reference_presence_is_unqualified_feature":True}
    output=ROOT/"analysis/night-learned-dialogue.v3.modal-adapter-r2.json"
    with output.open("xb") as handle: handle.write(canonical(report))
    text=("Offline narrow-v3 Modal adapter complete. No actual TRAIN fit, model-weight download, remote call or budget mutation.\n"
          +str(result.testsRun)+" offline tests pass; real SDK1.5.1 app constructed without app ID.\n"
          +"Current canonical review closure82 rows/38 groups; missing0073; proposed masked positives18, no adjudicated gold. Gate closed.\n"
          +"Teacher frozen E5 revision614241f622f53c4eeff9890bdc4f31cfecc418b3; MIT declared by pinned model card, no standalone LICENSE.\n"
          +"Student group objective (1-alpha)CE+alpha*T^2*KL; T2 alpha.25 plus gold-only control; all outputs abstain.\n"
          +"CPU-first measurement utility exists; pinned470MB weights absent, no measured CPU-versus-GPU claim.\n"
          +"Parent-only prepare/dry-run/launch/cancel; exact TRAIN payload <=1MB, tokenizer256 overflow rejects; explicit four-file image allowlist.\n"
          +"1H100, no retries/services/mincontainers; compute120/1800, startup240, shutdown60, absolute06:13:01Z. Parent$10 reservation/global30target35hard.\n"
          +"V1 "+str(len(preservation['v1']))+" files and finalV2 "+str(len(preservation['v2_final']))+" files verified unchanged.\n")
    with (ROOT/"analysis/night-learned-dialogue.v3.modal-adapter-r2.txt").open("x",encoding="utf-8") as handle: handle.write(text)
    print(json.dumps({"report":str(output),"sha256":digest(output.read_bytes()),"tests":result.testsRun,"actual_data_ready":False,"remote_calls":0,"preservation":report['preservation']},indent=2))


if __name__ == "__main__": main()
