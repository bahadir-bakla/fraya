"""Actual reviewed-source join tests. No fitting or authorization doubles."""
import copy
import socket
import subprocess
import unittest
from unittest.mock import patch

import alignment_v7 as alignment
import readiness_v7 as readiness


class ReviewedAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw,cls.docs,cls.reviews,cls.sources,cls.spans=readiness.verify_inputs()
        cls.joined=alignment.align(cls.docs,cls.sources)
        cls.assessment=readiness.assessment(cls.joined,cls.docs)

    def test_exact_source_and_review_validation_counts(self):
        self.assertEqual(self.spans,{"adjudicated":233,"original_reviews":440})
        self.assertEqual(self.assessment["adjudicated_primary_row_labels"],{"negative":78,"positive":48,"ambiguous":6})

    def test_actual_alignment_offsets_targets(self):
        self.assertEqual(self.assessment["annotation_alignment_status"],{
            "boundary_mismatch":60,"exact_span_and_target":20,"missing":19,"exact_span_target_unresolved_or_mismatch":2})
        self.assertEqual(len(self.joined["actual_date_candidate_rows"]),105)
        self.assertEqual(len(self.joined["reviewed_date_annotation_rows"]),101)

    def test_no_nearest_span_supervision(self):
        for r in self.joined["actual_date_candidate_rows"]:
            if "no_exact_reviewed_boundary" in r["mask_reasons"]:
                self.assertIsNone(r["label"]);self.assertIsNone(r["reviewed_axes"])
                self.assertFalse(r["pre_ancestry_eligible"])

    def test_exact_match_reproduces_original_full_span(self):
        for row in self.joined["actual_date_candidate_rows"]:
            if row["reviewed_axes"]:
                self.assertEqual(alignment.span_key(row["source_span"]),alignment.span_key(row["reviewed_axes"]["source_span"]))
                self.assertEqual(set(row["actual_target_hypothesis"]),set(row["reviewed_axes"]["target_indices"]))

    def test_false_absence_not_derived_from_empty_annotation(self):
        for r in self.joined["actual_date_candidate_rows"]:
            if r["label"] is None:self.assertFalse(r["loss_mask"])

    def test_peer_unknown_schema_not_rewritten_or_admitted(self):
        peer=list(self.sources)[1]
        peer_ids={r["example_id"] for r in self.sources[peer]["records"]}
        for r in self.joined["primary_rows"]:
            if r["example_id"] in peer_ids:
                self.assertIn("runtime_schema_profile_unqualified",r["mask_reasons"])
                self.assertFalse(r["pre_ancestry_eligible"])

    def test_all_independent_support_masked(self):
        for r in self.joined["primary_rows"]+self.joined["actual_date_candidate_rows"]:
            self.assertIn("independent_ancestry_support_unresolved",r["mask_reasons"])
            self.assertFalse(r["post_ancestry_eligible"]);self.assertFalse(r["loss_mask"])

    def test_pre_ancestry_diagnostic_support_not_admission(self):
        p=self.assessment["primary_pre_ancestry_construction_support"]
        self.assertEqual(p["positive"]["rows"],29);self.assertEqual(p["positive"]["construction_components"],8)
        self.assertEqual(p["negative"]["rows"],42);self.assertEqual(p["additional_negative_components"],9)
        d=self.assessment["DATE_pre_ancestry_construction_support"]
        self.assertEqual(d["complete"]["rows"],5);self.assertEqual(d["unfinished"]["rows"],5)
        self.assertEqual(d["complete"]["component_ids"],d["unfinished"]["component_ids"])

    def test_current_role_required_separate_from_completion(self):
        for r in self.joined["actual_date_candidate_rows"]:
            if r["reviewed_axes"] and r["reviewed_axes"]["candidate_role"]!="current":
                self.assertIn("superseded_or_uncertain_candidate",r["mask_reasons"])
                self.assertFalse(r["pre_ancestry_eligible"])

    def test_polarity_reference_normalization_not_permission(self):
        for r in self.joined["actual_date_candidate_rows"]:
            self.assertFalse(r["polarity_training_mask"])
            self.assertFalse(r["reference_mask"]);self.assertFalse(r["normalization_mask"])
            self.assertFalse(r["parent_authorized"])

    def test_preserved_explicit_replacement_revision_spans(self):
        rows=self.joined["reviewed_date_annotation_rows"]
        for example,a,b in (("1423a99b664423b3e37ce706",51,63),("d21f2cd0bce809acfcc27f75",57,77)):
            matches=[r for r in rows if r["example_id"]==example and
                     r["source_span"]["char_start"]==a and r["source_span"]["char_end"]==b]
            self.assertEqual(len(matches),1)

    def test_feature_values_never_rebuilt_from_annotations(self):
        before=alignment.source.encoded(self.docs["research/customer-benchmark/semantic-v6-extension/runtime-features.v6.json"])
        altered=copy.deepcopy(self.docs)
        for p in ("analysis/night-v6-adjudication.primary-packet.json","analysis/night-v6-adjudication.peer-packet.json"):
            for r in altered[p]["records"]:
                for c in r["date_candidates"]:c["completion"]="ambiguous";c["completion_observed"]=False
        joined=alignment.align(altered,self.sources)
        self.assertFalse(any(r["pre_ancestry_eligible"] for r in joined["actual_date_candidate_rows"]))
        self.assertEqual(before,alignment.source.encoded(altered["research/customer-benchmark/semantic-v6-extension/runtime-features.v6.json"]))

    def test_lineage_root_closure_detects_missing_member(self):
        lineage=copy.deepcopy(self.docs["research/customer-benchmark/semantic-v6-extension/source-adjudicated-lineage.json"])
        lineage["canonical_roots"][0]["members"].pop()
        candidates={r["example_id"]:r for r in self.docs["research/customer-benchmark/semantic-v6-extension/runtime-candidates.v6.json"]["rows"]}
        with self.assertRaises(alignment.source.SourceRejected):alignment.validate_lineage(lineage,candidates)

    def test_lineage_source_identity_mismatch_rejected(self):
        lineage=copy.deepcopy(self.docs["research/customer-benchmark/semantic-v6-extension/source-adjudicated-lineage.json"])
        lineage["member_source_bindings"][0]["source_input_json_sha256"]="0"*64
        candidates={r["example_id"]:r for r in self.docs["research/customer-benchmark/semantic-v6-extension/runtime-candidates.v6.json"]["rows"]}
        with self.assertRaises(alignment.source.SourceRejected):alignment.validate_lineage(lineage,candidates)

    def test_review_span_mutation_rejected(self):
        name="analysis/night-v6-adjudication.primary-packet.json"
        review=copy.deepcopy(self.docs[name]);review["records"][0]["evidence_spans"][0]["char_end"]-=1
        schema=self.docs["research/customer-benchmark/semantic-v6-peer-extension/independent-review.schema.json"]
        path=next(iter(self.sources))
        with self.assertRaises(alignment.source.SourceRejected):alignment.validate_review_packet(review,self.sources[path],path,schema)

    def test_review_order_must_match_all_source_members(self):
        review=copy.deepcopy(self.docs["analysis/night-v6-adjudication.primary-packet.json"])
        review["records"][0],review["records"][1]=review["records"][1],review["records"][0]
        schema=self.docs["research/customer-benchmark/semantic-v6-peer-extension/independent-review.schema.json"]
        path=next(iter(self.sources))
        with self.assertRaises(alignment.source.SourceRejected):alignment.validate_review_packet(review,self.sources[path],path,schema)

    def test_frozen_feature_candidate_vector_binding_required(self):
        altered=copy.deepcopy(self.docs)
        altered["research/customer-benchmark/semantic-v6-extension/runtime-features.v6.json"]["candidate_row_vector_sha256"]="0"*64
        with self.assertRaises(alignment.source.SourceRejected):alignment.align(altered,self.sources)

    def test_old_V5_grant_not_borrowed_or_groups_added(self):
        old=self.assessment["old_V5_separate"]
        self.assertEqual(old["primary_rows"],103);self.assertEqual(old["primary_additional_negative_groups"],19)
        self.assertFalse(old["old_grant_reused"]);self.assertFalse(old["combined_support_computed"])
        self.assertEqual(old["new_groups_added"],0)

    def test_pure_alignment_forbidden_side_effects(self):
        before=alignment.source.encoded(self.docs)
        with patch("builtins.open",side_effect=AssertionError("I/O")), \
             patch.object(socket,"socket",side_effect=AssertionError("network")), \
             patch.object(subprocess,"Popen",side_effect=AssertionError("process")):
            actual=alignment.align(self.docs,self.sources)
        self.assertEqual(actual,self.joined);self.assertEqual(before,alignment.source.encoded(self.docs))

    def test_no_fit_or_golden_safety_claim(self):
        self.assertEqual(self.assessment["fit_calls"],0);self.assertFalse(self.assessment["cpu_fit_ready"])
        self.assertFalse(self.assessment["qualified"]);self.assertFalse(self.assessment["new_DEV_read"])
        self.assertEqual(self.assessment["human_gold_rows"],0);self.assertEqual(self.assessment["iid_gold_rows"],0)
        self.assertEqual(self.assessment["floor"],20)


if __name__=="__main__":unittest.main()
