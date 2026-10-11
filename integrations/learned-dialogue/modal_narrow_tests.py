"""Offline tests use invented in-memory protocol fixtures, never new gold data."""
import copy
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import modal_narrow_core as core
from modal_narrow_app import create_app, REMOTE_FILES
from modal_narrow_review import assess_reviews_v3
from modal_narrow_runner import dry_run, cancel_parent, stopped_from_listing, stop_commands
from modal_narrow_teacher import group_weights, check_token_lengths, verify_model
from modal_narrow_student import fit_student, propose
from modal_narrow_student import export_student, sigmoid
from modal_narrow_cpu_trial import cost_decision


def fixture():
    rows = [{"id":"fixture-"+str(i), "group":"root-"+str(i), "split":"train", "fictional":True,
             "input_sha256":"a"*64, "text":"query: context: {}\nlatest_user: "+("I propose payment." if i < 21 else "I ask a question."), "y":int(i < 21)} for i in range(41)]
    for row in rows:
        row["source_segments"]=[{"kind":"latest_user","source_event_id":"fixture-event","start":0,"end":5,"transformation":"literal"}]
        row["privacy_evidence_sha256"]="a"*64
        row["view_sha256"]=core.digest(core.canonical({k:row[k] for k in ("text","source_segments","privacy_evidence_sha256")}))
    sources = dict.fromkeys(core.SOURCE_KEYS, "a"*64)
    sources["adapter_contract_sha256"] = core.digest(core.canonical(core.CONTRACT))
    return {"format":core.FORMAT, "task":core.TASK, "rows":rows, "sources":sources,
            "row_manifest":{r["id"]:core.digest(core.canonical(r)) for r in rows}, "contract":copy.deepcopy(core.CONTRACT)}


def grant_fixture(payload):
    budget = {"profile":core.PROFILE,"single_job_at_a_time":True,"max_gpus_per_job":1,
              "actual_task_cost_usd":0,"actual_task_cost_verified":True,"target_usd":30,"hard_cap_usd":35,
              "cloud_stop_utc":core.ABSOLUTE_STOP,"invocations":[],
              "reservations":[{"reservation_id":"fixture-reservation","reserved_usd":10,"status":"reserved","authorized_by_parent":True}]}
    grant = {k:True for k in ("parent_authorized_launch", "reviewed_data_gate", "independent_annotations_verified", "parent_adjudication_verified", "effective_rates_verified", "sdk_and_stop_capabilities_verified", "independent_watchdog_armed", "dependency_image_reviewed", "gpu_benefit_over_cpu_verified", "canonical_lineage_closure_verified", "reviewed_dev_frozen", "sparse_cpu_and_phase_controls_complete", "v3_source_reference_controls_passed", "actual_detector_false_candidate_audit_passed")}
    grant.update({"payload_sha256":core.digest(payload),"profile":core.PROFILE,"reservation_id":"fixture-reservation",
                  "budget_snapshot_sha256":core.digest(core.canonical(budget)),"mode":"smoke","compute_seconds":120,
                  "startup_seconds":240,"shutdown_seconds":60,"cloud_stop_utc":core.ABSOLUTE_STOP,
                  "effective_resource_rate_usd_per_second":.0014,"build_storage_egress_reserve_usd":2,
                  "automatic_retries":0,"gpu":"H100","invocation_ordinal":1})
    return budget, grant


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.p = fixture()
    def reject(self, mutator):
        mutator(self.p)
        with self.assertRaises((ValueError, TypeError, KeyError)):
            core.validate_payload(core.canonical(self.p))
    def test_roundtrip_exact(self):
        blob = core.canonical(self.p)
        self.assertEqual(core.canonical(core.validate_payload(blob,core.digest(blob))),blob)
    def test_tampered_label(self):
        self.reject(lambda p:p["rows"][0].update(y=0))
    def test_holdout_upload_forbidden(self):
        self.reject(lambda p:p["rows"][0].update(split="holdout"))
    def test_dev_upload_forbidden(self):
        self.reject(lambda p:p["rows"][0].update(split="dev"))
    def test_real_customer_forbidden(self):
        self.reject(lambda p:p["rows"][0].update(fictional=False))
    def test_permission_field_forbidden(self):
        self.reject(lambda p:p.update(tool_request="transfer"))
    def test_oracle_span_field_forbidden(self):
        self.reject(lambda p:p["rows"][0].update(oracle_span=[0,1]))
    def test_duplicate_id(self):
        self.reject(lambda p:p["rows"][1].update(id=p["rows"][0]["id"]))
    def test_below_positive_floor(self):
        self.p["rows"] = self.p["rows"][1:]
        self.p["row_manifest"] = {r["id"]:core.digest(core.canonical(r)) for r in self.p["rows"]}
        with self.assertRaisesRegex(ValueError,"floor"):
            core.validate_payload(core.canonical(self.p))
    def test_overlapping_groups_not_additional_negative(self):
        for i in range(21,41):
            self.p["rows"][i]["group"] = "root-0"
        self.p["row_manifest"] = {r["id"]:core.digest(core.canonical(r)) for r in self.p["rows"]}
        with self.assertRaisesRegex(ValueError,"floor"):
            core.validate_payload(core.canonical(self.p))
    def test_oversize_bytes(self):
        with self.assertRaises(ValueError): core.validate_payload(b" "*(core.MAX_BYTES+1))
    def test_duplicate_json_keys(self):
        with self.assertRaises(ValueError): core.load(b'{"a":1,"a":2}')
    def test_nonfinite(self):
        with self.assertRaises(ValueError): core.load(b'{"a":NaN}')
    def test_fine_tune_not_enabled_by_payload(self):
        self.reject(lambda p:p["contract"].update(fine_tune=True))


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.blob = core.canonical(fixture())
        self.b,self.g = grant_fixture(self.blob)
        self.now = datetime(2026,10,11,2,0,tzinfo=timezone.utc)
    def check(self): return dry_run(self.blob,self.b,self.g,self.now)
    def test_fixture_admission_is_only_dryrun(self):
        d = self.check(); self.assertTrue(d["admitted"]); self.assertEqual(d["cloud_actions"],0)
    def test_no_reservation(self):
        self.b["reservations"] = []; self.assertFalse(self.check()["admitted"])
    def test_budget_drift(self):
        self.b["actual_task_cost_usd"] = 1; self.assertFalse(self.check()["admitted"])
    def test_other_job_active(self):
        self.b["invocations"] = [{"status":"running"}]; self.assertFalse(self.check()["admitted"])
    def test_missing_watchdog(self):
        self.g["independent_watchdog_armed"] = False; self.assertFalse(self.check()["admitted"])
    def test_retry_rejected(self):
        self.g["automatic_retries"] = 1; self.assertFalse(self.check()["admitted"])
    def test_cloud_deadline(self):
        self.now = datetime(2026,10,11,6,12,tzinfo=timezone.utc); self.assertFalse(self.check()["admitted"])
    def test_timeout_extension_rejected(self):
        self.g["compute_seconds"] = 1801; self.assertFalse(self.check()["admitted"])
    def test_malformed_timeout_closed(self):
        self.g["compute_seconds"] = "1800"; self.assertFalse(self.check()["admitted"])
    def test_rate_credit_does_not_pass(self):
        self.g["effective_resource_rate_usd_per_second"] = 0; self.assertFalse(self.check()["admitted"])
    def test_target_cap(self):
        self.b["actual_task_cost_usd"] = 21; self.g["budget_snapshot_sha256"] = core.digest(core.canonical(self.b)); self.assertFalse(self.check()["admitted"])
    def test_missing_detector_gate(self):
        self.g["actual_detector_false_candidate_audit_passed"] = False; self.assertFalse(self.check()["admitted"])


class ModelTests(unittest.TestCase):
    def test_builtin_exp_parity(self):
        import math
        for index in range(-640,641):
            z=index/20
            self.assertAlmostEqual(sigmoid(z),1/(1+math.exp(-z)),places=14)
    def test_export_pure_parity_no_side_effects(self):
        import ast
        m={"weights":{"w1:payment":1.},"bias":-.5}
        blob=export_student(m)
        tree=ast.parse(blob)
        self.assertEqual({n.names[0].name for n in ast.walk(tree) if isinstance(n,ast.Import)},{"json","re"})
        scope={}
        exec(compile(tree,"offline-student-export","exec"),scope)
        with patch("builtins.open",side_effect=AssertionError("I/O forbidden")),patch("socket.socket",side_effect=AssertionError("socket forbidden")),patch("subprocess.Popen",side_effect=AssertionError("process forbidden")):
            for text in ("payment","question","no payment",None,"", "x"*8193):
                self.assertEqual(scope["predict"](text),propose(text,m))
                self.assertEqual(scope["predict"](text)["decision"],"abstain")
    def test_cpu_cost_decision_requires_actual_complete_run(self):
        self.assertFalse(cost_decision({})["measured_cpu_feasible"])
        self.assertTrue(cost_decision({"elapsed_seconds":120.,"training_rows":41,"encoder_frozen":True})["measured_cpu_feasible"])
        self.assertFalse(cost_decision({"elapsed_seconds":301.,"training_rows":41,"encoder_frozen":True})["measured_cpu_feasible"])
    def test_group_descendants_share_weight(self):
        weights = group_weights([{"group":"a"},{"group":"a"},{"group":"b"}])
        self.assertEqual(weights,[.25,.25,.5]); self.assertEqual(sum(weights),1.)
    def test_tokenizer_does_not_truncate(self):
        calls = []
        def tokenizer(texts, **kwargs):
            calls.append(kwargs); return {"input_ids":[list(range(257))]}
        with self.assertRaisesRegex(ValueError,"overflow"): check_token_lengths(tokenizer,["suffix"])
        self.assertFalse(calls[0]["truncation"])
    def test_public_model_tamper_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,"config.json").write_bytes(b"changed")
            m = {"model_id":"intfloat/multilingual-e5-small","revision":"614241f622f53c4eeff9890bdc4f31cfecc418b3","declared_license":"mit",
                 "files":{"config.json":{"size":7,"sha256":"a"*64}}}
            with self.assertRaisesRegex(ValueError,"hash mismatch"): verify_model(directory,m)
    def test_student_train_only_and_persistence(self):
        blob = core.canonical(fixture())
        r = {"format":"narrow_frozen_teacher_result.v3","payload_sha256":core.digest(blob),
             "train_only_soft_targets":[{"id":row["id"],"group":row["group"],"logit":1.38629436112 if row["y"] else -1.38629436112} for row in fixture()["rows"]]}
        m = fit_student(blob,r,alpha=.25)
        n = core.load(core.canonical(m))
        self.assertEqual(propose("query: I propose payment",m),propose("query: I propose payment",n))
        self.assertEqual(propose("arbitrary input",m)["decision"],"abstain")
        self.assertLess(len(core.canonical(m)),500000)
    def test_student_foreign_soft_target_rejected(self):
        blob = core.canonical(fixture())
        r = {"format":"narrow_frozen_teacher_result.v3","payload_sha256":core.digest(blob),"train_only_soft_targets":[]}
        with self.assertRaises(ValueError): fit_student(blob,r)
    def test_student_no_adaptive_alpha_sweep(self):
        blob=core.canonical(fixture())
        r={"format":"narrow_frozen_teacher_result.v3","payload_sha256":core.digest(blob)}
        with self.assertRaises(ValueError): fit_student(blob,r,alpha=.5)


class SourceViewTests(unittest.TestCase):
    def snapshot(self):
        return {"turn_id":"user-independent","utterance":{"source":"authored_fixture","source_turn_id":"user-independent","complete_transport":True,"text":"I can pay 1200."},
                "phase":"payment","question":{"role":"offer","target_indices":[0],"text":"Would payment work?","spoken_turn_id":"assistant-independent","spoken_offer_id":"offer-independent"},
                "targets":[{"index":0,"type":"credit_card","label":"card ending 4628","product_id":"bank-id"},{"index":1,"type":"loan"}],
                "pending":[{"target_index":0,"components":{"amount":{"status":"validated","revision":"opaque-r1","value":"137"},"date":{"status":"unfinished","revision":"opaque-r2"}},"unresolved_components":["date"]},
                           {"target_index":1,"components":{"amount":{"status":"missing","revision":"opaque-other"}},"unresolved_components":["amount"]}],"active_readback":None}
    def privacy(self):
        return {"whole_turn_and_question_nonsecurity_value_free":True,"no_account_identifiers":True,"parent_evidence_sha256":"a"*64}
    def test_actual_nested_shape_and_no_value_revision_features(self):
        v=core.source_view(self.snapshot(),self.privacy()); t=v["text"]
        self.assertIn('"amount":"validated"',t); self.assertIn('"date":"unfinished"',t)
        self.assertNotIn("opaque-r1",t); self.assertNotIn("bank-id",t); self.assertNotIn("4628",t); self.assertNotIn("137",t)
        self.assertIn("I can pay <number>.",t)
    def test_target_permutation_and_renaming_invariance(self):
        s=self.snapshot(); original=core.role_text(s,self.privacy())
        s["targets"].reverse(); s["pending"].reverse()
        for target in s["targets"]: target["index"] += 10
        for pending in s["pending"]: pending["target_index"] += 10
        s["question"]["target_indices"]=[10]
        self.assertEqual(core.role_text(s,self.privacy()),original)
    def test_target_specific_pending_not_union(self):
        s=self.snapshot(); original=core.role_text(s,self.privacy())
        s["question"]["target_indices"]=[1]
        self.assertNotEqual(core.role_text(s,self.privacy()),original)
    def test_missing_privacy_evidence_rejects_before_hashing(self):
        with self.assertRaises(ValueError): core.source_view(self.snapshot(),{})
    def test_security_turn_rejected_even_with_fixture_privacy_flag(self):
        s=self.snapshot(); s["question"]["role"]="security"
        with self.assertRaises(ValueError): core.source_view(s,self.privacy())
    def test_source_map_preserves_original_unicode_offsets(self):
        s=self.snapshot(); s["utterance"]["text"]="😀 pay 1200."
        view=core.source_view(s,self.privacy())
        marker=next(segment for segment in view["source_segments"] if segment["kind"]=="latest_user" and segment["transformation"]=="number_marker")
        self.assertEqual(s["utterance"]["text"][marker["start"]:marker["end"]],"1200")
    def test_duplicate_target_rejected(self):
        s=self.snapshot(); s["targets"][1]["index"]=0
        with self.assertRaises(ValueError): core.source_view(s,self.privacy())


class AppTests(unittest.TestCase):
    def test_no_directory_upload_and_bounded_single_function(self):
        files, options = [], {}
        class Image:
            @classmethod
            def debian_slim(cls, **kwargs): return cls()
            def pip_install(self,*args): return self
            def env(self,values): return self
            def add_local_file(self,path,remote_path): files.append((Path(path).name,remote_path)); return self
        class App:
            def __init__(self,*args,**kwargs): self.include_source=kwargs["include_source"]
            def function(self,**kwargs): options.update(kwargs); return lambda f:f
        app, function = create_app(120,SimpleNamespace(Image=Image,App=App))
        self.assertFalse(app.include_source)
        self.assertEqual({f[0] for f in files},set(REMOTE_FILES))
        self.assertEqual(options["gpu"],"H100")
        self.assertEqual(options["cpu"],(2,2)); self.assertEqual(options["memory"],(16384,16384))
        self.assertEqual(options["max_containers"],1); self.assertEqual(options["min_containers"],0)
        self.assertEqual(options["retries"],0); self.assertEqual(options["startup_timeout"],240)
        self.assertTrue(options["single_use_containers"])
        self.assertEqual(options["secrets"],[]); self.assertEqual(options["volumes"],{})
        self.assertIsNone(options["schedule"])
    def test_no_import_side_effect_cloud(self):
        with patch("subprocess.Popen", side_effect=AssertionError("process forbidden")), patch("socket.socket",side_effect=AssertionError("network forbidden")):
            d=dry_run(core.canonical(fixture()),*grant_fixture(core.canonical(fixture())),datetime(2026,10,11,2,tzinfo=timezone.utc))
            self.assertEqual(d["cloud_actions"],0)
    def test_app_timeout_invalid(self):
        with self.assertRaises(ValueError): create_app(1801)


class CancelTests(unittest.TestCase):
    def test_exact_id_only(self):
        with self.assertRaises(ValueError): stop_commands("learned*")
    def test_missing_app_is_not_stop_proof(self):
        self.assertFalse(stopped_from_listing(b"[]","ap-fixture"))
    def test_stopping_not_stopped(self):
        self.assertFalse(stopped_from_listing(core.canonical([{"app_id":"ap-fixture","state":"stopping...","tasks":"0"}]),"ap-fixture"))
    def test_tasks_running_is_not_stop_proof(self):
        self.assertFalse(stopped_from_listing(core.canonical([{"app_id":"ap-fixture","state":"stopped","tasks":"1"}]),"ap-fixture"))
    def test_cancel_and_independent_cli_observation(self):
        calls=[]
        def run(command,**kwargs):
            calls.append((command,kwargs))
            return SimpleNamespace(returncode=0,stdout=core.canonical([{"app_id":"ap-fixture","state":"stopped","tasks":"0"}]))
        result=cancel_parent("ap-fixture","fc-fixture",run)
        self.assertTrue(result["remote_stop_verified"]); self.assertFalse(result["reservation_release_allowed"])
        self.assertEqual(len(calls),3); self.assertIn("terminate_containers=True",calls[0][0][3])
        self.assertTrue(all(c[1]["timeout"] <= 15 for c in calls))
    def test_network_failure_no_false_stop(self):
        def run(command,**kwargs): raise subprocess.TimeoutExpired(command,kwargs["timeout"])
        result=cancel_parent("ap-fixture","fc-fixture",run)
        self.assertFalse(result["remote_stop_verified"])


class ReviewTests(unittest.TestCase):
    def fixtures(self):
        snapshots={"utterance":{"text":"invented fixture","source":"authored_fixture","source_turn_id":"turn","complete_transport":True},"turn_id":"turn","phase":"payment","targets":[],"pending":[]}
        records=[{"example_id":r["id"],"lineage_group_id":r["group"],"input":snapshots,"split":"train"} for r in fixture()["rows"]]
        packet={"records":[{"example_id":r["example_id"],"lineage_group_id":r["lineage_group_id"],"input":r["input"]} for r in records]}
        overlay={"canonical_map":{r["lineage_group_id"]:r["lineage_group_id"] for r in records},"semantic_axes_version":"fixture-axes"}
        reviews={"records":[{"example_id":r["id"],"input_sha256":core.digest(core.canonical(snapshots)),
                             "annotations":[{"reviewer_id":"reviewer-a","label":"positive" if r["y"] else "negative"},{"reviewer_id":"reviewer-b","label":"positive" if r["y"] else "negative"}],
                             "adjudication":{"status":"adjudicated","label":"positive" if r["y"] else "negative","parent_evidence_sha256":"a"*64}} for r in fixture()["rows"]]}
        auth={"packet_sha256":"a"*64,"reviews_sha256":"b"*64,"source_manifest_sha256":core.digest(b"fixture-source"),
              "lineage_overlay_sha256":core.digest(core.canonical(overlay)),"semantic_axes_version":"fixture-axes",
              "parent_verified_blind_independence":True,"parent_adjudication_verified":True,"closure_supplement_delivered_verified":True,
              "reviewer_registry":{name:{"verified_independent_blind":True,"is_original_author":False,"parent_evidence_sha256":"a"*64} for name in ("reviewer-a","reviewer-b")}}
        return packet,reviews,auth,{"records":records},{"records":[]},b"fixture-source",overlay
    def test_protocol_fixture_ready_not_actual_gold(self):
        r=assess_reviews_v3(*self.fixtures()); self.assertTrue(r["admitted"]); self.assertFalse(r["qualified"])
    def test_merged_roots_reduce_class_count(self):
        args=list(self.fixtures()); args[-1]["canonical_map"]["root-1"]="root-0"; args[2]["lineage_overlay_sha256"]=core.digest(core.canonical(args[-1]))
        r=assess_reviews_v3(*args); self.assertFalse(r["admitted"]); self.assertEqual(r["canonical_positive_groups"],20)
    def test_missing_closure_member(self):
        args=list(self.fixtures()); new=copy.deepcopy(args[3]["records"][0]); new["example_id"]="closure-supplement"; args[3]["records"].append(new)
        r=assess_reviews_v3(*args); self.assertFalse(r["admitted"]); self.assertIn("closure-supplement",r["missing_closure_ids"])
    def test_cross_split_canonical_overlap(self):
        args=list(self.fixtures()); args[4]["records"]=[copy.deepcopy(args[3]["records"][0])]
        r=assess_reviews_v3(*args); self.assertFalse(r["admitted"]); self.assertIn("canonical_train_dev_overlap_quarantine_required",r["reasons"])
    def test_author_not_independent(self):
        args=list(self.fixtures()); args[2]["reviewer_registry"]["reviewer-a"]["is_original_author"]=True
        self.assertFalse(assess_reviews_v3(*args)["admitted"])
    def test_conflict_needs_independent_adjudicator(self):
        args=list(self.fixtures()); args[1]["records"][0]["annotations"][0]["label"]="negative"
        self.assertFalse(assess_reviews_v3(*args)["admitted"])
    def test_changed_input_rejected(self):
        args=list(self.fixtures()); args[1]["records"][0]["input_sha256"]="b"*64
        self.assertFalse(assess_reviews_v3(*args)["admitted"])


if __name__ == "__main__": unittest.main(verbosity=2)
