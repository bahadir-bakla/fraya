"""Actual TRAIN exact-alignment and isolated toy mathematical controls."""
import copy
import json
import socket
import subprocess
import unittest
from unittest.mock import patch

import alignment_v5 as alignment
import narrow_review_v4 as admission
import primary_cpu_v5 as cpu
from window_r4 import date_features_r4


class AlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = admission.load_allowed_inputs()
        cls.valid = admission.validate_reviewed_inputs(cls.raw)
        cls.report = alignment.analyze(cls.raw)

    def test_pinned_inputs(self):
        self.assertEqual(self.report["source_raw_sha256"], admission.PINNED_SHA256)
        self.assertEqual(len(self.valid["rows"]["primary"]), 119)
        self.assertEqual(len(self.valid["rows"]["date_whole_row"]), 72)

    def test_no_annotation_feedback_into_candidates(self):
        original = alignment.make_actual_vector(self.valid)
        changed = copy.deepcopy(self.valid)
        changed["date_annotations"] = []
        for r in changed["rows"]["date_whole_row"]:
            r["label"] = "ambiguous"
        self.assertEqual(original, alignment.make_actual_vector(changed))

    def test_vector_no_supervision(self):
        for row in self.report["candidate_vector"]:
            self.assertNotIn("label", row)
            self.assertNotIn("y", row)
            self.assertEqual(len(row["target_indices"]), 1)

    def test_actual_boundary_and_target_gaps_remain_masked(self):
        counts = self.report["date"]["annotation_status_counts"]
        self.assertEqual(counts["boundary_mismatch"], 5)
        self.assertEqual(counts["exact_span_scope_unresolved"], 6)
        self.assertEqual(counts["exact_scope"], 64)
        self.assertFalse(self.report["date"]["completion_floor_met"])
        eligible = self.report["date"]["actual_feature_eligible_observed_support"]
        self.assertEqual(eligible["complete"]["groups"], 20)
        self.assertEqual(eligible["unfinished"]["groups"], 16)

    def test_no_reference_or_normalization_promotion(self):
        for d in self.report["date"]["candidate_diagnostics"]:
            self.assertFalse(d["reference_eligible"])
            self.assertFalse(d["normalization_eligible"])

    def test_mutated_span_rejected_not_nearest(self):
        vector = copy.deepcopy(self.report["candidate_vector"])
        vector[0]["source_span"]["char_end"] -= 1
        with self.assertRaises(admission.AdmissionError):
            admission.align_date_candidates(vector, self.valid)

    def test_exact_alignment_not_authorization(self):
        result = admission.assess_admission(self.raw, candidates=self.report["candidate_vector"])
        self.assertFalse(result["admitted"])
        self.assertFalse(any(result["eligible_rows"].values()))
        self.assertIn("externally_trusted_exact_hash_parent_authorization_missing", result["reasons"])

    def test_actual_fit_stops_before_math_without_authorization(self):
        with patch.object(cpu, "fit", side_effect=AssertionError("fit must not run")):
            with self.assertRaises(cpu.admission.AdmissionError):
                cpu.authorized_experiment(self.raw, None, None, self.report["candidate_vector"], None)

    def test_analysis_has_no_external_side_effects(self):
        with patch.object(socket, "socket", side_effect=AssertionError("socket")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            result = alignment.analyze(self.raw)
        self.assertFalse(result["trained"])
        self.assertFalse(result["qualified"])

    def test_security_masks_shared(self):
        row = copy.deepcopy(self.valid["rows"]["date_whole_row"][0])
        candidate = self.report["date"]["candidate_diagnostics"][0]["candidate"]
        for where in ("phase", "role", "field", "text"):
            s = copy.deepcopy(row["snapshot"])
            if where == "phase": s["phase"] = "security"
            if where == "role": s["question"]["role"] = "security"
            if where == "field": s["question"]["security_field"] = "verification"
            if where == "text": s["utterance"]["text"] += " password"
            a = alignment.replay_surface_admission(s)
            self.assertFalse(a["nonsecurity_value_free"])
            self.assertFalse(cpu.features(s)["eligible"])
            self.assertFalse(date_features_r4(s, candidate, a)["eligible"])

    def test_no_new_dev_and_no_gold_claim(self):
        self.assertFalse(self.report["new_dev_read"])
        self.assertEqual(self.report["human_gold_rows"], 0)
        self.assertEqual(self.report["iid_gold_rows"], 0)
        self.assertFalse(self.report["payment_authority"])


class MathControls(unittest.TestCase):
    def snapshot(self, text="I can pay next Friday"):
        return {"turn_id":"unit-user", "phase":"payment", "question":{"role":"date", "target_indices":[0]},
                "targets":[{"index":0}], "pending":[], "utterance":{"text":text,
                 "source_turn_id":"unit-user", "complete_transport":True, "offset_unit":"python_unicode_codepoints"}}

    def toy_rows(self):
        return [{"id":str(i),"group":"g"+str(i//2),"snapshot":self.snapshot("pay Friday" if i%2 else "please stop calling"),
                 "y":i%2} for i in range(8)]

    def test_group_mean_not_row_mean(self):
        rows = [{"group":"a"}, {"group":"a"}, {"group":"a"}, {"group":"b"}]
        self.assertEqual(cpu.group_weights(rows), [1/6, 1/6, 1/6, 1/2])

    def test_duplicate_group_members_do_not_change_gradient(self):
        rows = self.toy_rows()
        a = cpu.fit(rows)
        b = cpu.fit(rows + [r for r in rows if r["group"] == "g0"])
        self.assertAlmostEqual(a["bias"], b["bias"], places=12)
        self.assertEqual(set(a["weights"]), set(b["weights"]))
        for k in a["weights"]:
            self.assertAlmostEqual(a["weights"][k], b["weights"][k], places=12)

    def test_persistence_and_runtime_feature_parity(self):
        bundle = cpu.fit(self.toy_rows())
        restored = json.loads(json.dumps(bundle, allow_nan=False))
        for row in self.toy_rows():
            prediction = cpu.predict(row["snapshot"], bundle)
            self.assertEqual(prediction, cpu.predict(row["snapshot"], restored))
            f = cpu.features(row["snapshot"], bundle["mode"])["features"]
            z = bundle["bias"] + sum(v*f.get(k,0) for k,v in bundle["weights"].items())
            self.assertEqual(z, prediction["raw_score"])
            self.assertEqual(prediction["decision"], "abstain")
        self.assertLess(len(json.dumps(bundle).encode()), 500000)

    def test_no_context_ablation_removes_all_context_paths(self):
        s = self.snapshot()
        changed = copy.deepcopy(s)
        changed["phase"] = "callback"
        changed["question"]["role"] = "amount"
        self.assertEqual(cpu.features(s, "text_only"), cpu.features(changed, "text_only"))
        self.assertNotEqual(cpu.features(s), cpu.features(changed))

    def test_ids_hashes_values_not_feature_keys(self):
        s = self.snapshot()
        s["turn_id"] = "different-id"
        s["utterance"]["source_turn_id"] = s["turn_id"]
        s["policy_hash"] = "secret-policy"
        s["pending"] = [{"target_index":0,"components":{"amount":{"status":"complete","value":91231}}}]
        keys = cpu.features(s)["features"]
        self.assertFalse(any("different-id" in k or "secret-policy" in k or "91231" in k for k in keys))

    def test_fixed_folds_keep_siblings(self):
        for row in self.toy_rows():
            self.assertEqual(cpu.fold(row["group"]), cpu.fold(row["group"]))
        self.assertTrue(all(0 <= cpu.fold("g"+str(i)) < 5 for i in range(20)))

    def test_group_shuffle_deterministic_without_input_mutation(self):
        rows = self.toy_rows()
        original = copy.deepcopy(rows)
        self.assertEqual(cpu.shuffle_group_targets(rows), cpu.shuffle_group_targets(rows))
        self.assertEqual(rows, original)

    def test_feature_version_and_malformed_bundle_reject(self):
        with self.assertRaises(ValueError):
            cpu.predict(self.snapshot(), {"schema_version":"old"})
        b = cpu.fit(self.toy_rows())
        b["bias"] = float("nan")
        with self.assertRaises(ValueError):
            cpu.predict(self.snapshot(), b)

    def test_unavailable_raw_source_masks(self):
        for s in ({}, {"utterance":{"text":"Friday"}}, self.snapshot("a"*513)):
            self.assertFalse(cpu.features(s)["eligible"])


if __name__ == "__main__":
    unittest.main()
