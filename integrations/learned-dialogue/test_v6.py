"""Source-only actual packet checks; no supervision/authorization doubles."""
import copy
import json
import socket
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import data_v6 as data
from detector_r4 import date_expressions_r4
from window_r4 import date_features_r4


class SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources=data.load_sources()
        exported,cls.helpers,primary=data.frozen_export_helpers()
        cls.exported=staticmethod(exported);cls.primary=staticmethod(primary)
        cls.schema=json.loads((data.ROOT/"integrations/learned-dialogue/contract_v2.json").read_bytes())["schema"]
        cls.model_id="4b96a26d0b99ed2ff2d774d7678131c4cb14960b462ba48bcc3790972d31b427"
        cls.candidates,cls.features,cls.profiles=data.prepare(cls.sources,cls.schema,cls.model_id,
            cls.exported,cls.helpers,cls.primary)

    def source(self):return copy.deepcopy(next(iter(self.sources.values()))["records"][0]["input"])

    def test_exact_132_source_rows(self):
        self.assertEqual([len(p["records"]) for p in self.sources.values()],[72,60])
        self.assertEqual(len(self.candidates),132)

    def test_schema_missing_provenance_not_fabricated(self):
        for packet in self.sources.values():
            self.assertNotIn("author_id",packet)
            self.assertNotIn("license",packet)
            for r in packet["records"]:
                self.assertEqual(set(r),{"example_id","input"})

    def test_peer_phase_and_hashes_preserved(self):
        peer=list(self.sources)[1]
        self.assertEqual(self.profiles[peer]["phase_counts"],{"post_verified_account":60})
        self.assertEqual(self.profiles[peer]["counts"]["wire_ingress_reason:unknown_schema"],60)
        for r in self.candidates[72:]:
            self.assertEqual(r["runtime_output"]["binding"]["policy_hash"],"d2daa6b1ae68ca75fd3dbe777ab1ace8bf0f9fa980b3951a277d41afca55f115")

    def test_raw_source_not_mutated(self):
        for path,p in self.sources.items():
            self.assertEqual(p,data.strict_json((data.ROOT/path).read_bytes()))

    def test_all_masks_unobserved(self):
        for r in self.features:
            self.assertFalse(r["loss_mask"])
            self.assertIsNone(r["label"])
        for r in self.candidates:
            self.assertIsNone(r["reviewed_canonical_group"])
            for c in r["candidates"]:
                for key in ("target_binding_reviewed","candidate_role_reviewed","validity_mask","completion_mask","reference_mask","normalization_mask"):
                    self.assertFalse(c[key])

    def test_exact_codepoint_utf8_actual_candidates(self):
        count=0
        for r in self.candidates:
            for c in r["candidates"]:
                data.check_span(c["source_span"],self.sources[r["source_packet"]]);count+=1
        self.assertGreater(count,0)

    def test_utf8_multibyte_without_normalization(self):
        packet={"records":[{"input":{"utterance":{"text":"é… Friday"}}}]}
        span=data.span_binding("unit","0"*64,0,"é… Friday",3,9)
        self.assertEqual(span["utf8_byte_start"],6)
        data.check_span(span,packet)
        span["utf8_byte_start"]-=1
        with self.assertRaises(data.SourceRejected):data.check_span(span,packet)

    def test_invalid_span_no_nearest(self):
        s=self.candidates[0]
        if not s["candidates"]:s=next(r for r in self.candidates if r["candidates"])
        span=copy.deepcopy(s["candidates"][0]["source_span"])
        span["char_end"]-=1
        with self.assertRaises(data.SourceRejected):data.check_span(span,self.sources[s["source_packet"]])

    def test_duplicates_and_nonfinite_json_rejected(self):
        for text in ('{"x":1,"x":2}','{"x":NaN}','{"x":Infinity}'):
            with self.assertRaises(data.SourceRejected):data.strict_json(text)

    def test_bool_revision_rejected(self):
        s=self.source();s["state_revision"]=True
        with self.assertRaises(data.SourceRejected):data.validate_snapshot(s)

    def test_unknown_target_rejected_not_mapped(self):
        s=self.source();s["question"]["target_indices"]=[999]
        with self.assertRaises(data.SourceRejected):data.validate_snapshot(s)

    def test_source_turn_mismatch_rejected(self):
        s=self.source();s["utterance"]["source_turn_id"]="unrelated"
        with self.assertRaises(data.SourceRejected):data.validate_snapshot(s)

    def test_unknown_live_source_masks_all_DATE_features(self):
        for row in self.features:
            if row["head"]=="date_completion":
                self.assertFalse(row["unknown_live_source_features"]["eligible"])
                self.assertEqual(row["unknown_live_source_features"]["features"],{})

    def test_security_phase_role_field_and_keyword_mask(self):
        for variant in ("phase","role","field","keyword"):
            s=self.source();s["utterance"]["text"]="Friday"
            if variant=="phase":s["phase"]="security"
            if variant=="role":s["question"]["role"]="security"
            if variant=="field":s["question"]["security_field"]="verification"
            if variant=="keyword":s["utterance"]["text"]="Friday password"
            c=date_expressions_r4(s["utterance"]["text"],"date")["candidates"][0]
            admitted=data.replay_surface_admission(s)
            self.assertFalse(date_features_r4(s,c,admitted)["eligible"])
            self.assertFalse(data.primary_features(s)["eligible"])

    def test_actual_wire_no_authority(self):
        for row in self.candidates:
            wire=row["runtime_output"]
            self.assertEqual(wire["status"],"abstain")
            self.assertIsNone(wire["primary"])
            self.assertIsNone(wire["consent_signal"]["candidate_readback_id"])
            self.assertEqual(wire["consent_signal"]["decision"],"descriptive_only")

    def test_packet_has_no_offer_or_readback(self):
        for packet in self.sources.values():
            for r in packet["records"]:
                self.assertEqual(r["input"]["spoken_offers"],[])
                self.assertIsNone(r["input"]["active_readback"])

    def test_forbidden_io_pure_prepare_and_no_input_change(self):
        before=data.encoded(self.sources)
        with patch("builtins.open",side_effect=AssertionError("I/O")), \
             patch.object(socket,"socket",side_effect=AssertionError("network")), \
             patch.object(subprocess,"Popen",side_effect=AssertionError("process")):
            actual=data.prepare(self.sources,self.schema,self.model_id,self.exported,self.helpers,self.primary)
        self.assertEqual(before,data.encoded(self.sources))
        self.assertEqual(actual[0],self.candidates)

    def test_features_never_include_policy_api_target_ids_values(self):
        for row in self.features:
            keys=row["replay_features"]["features"]
            self.assertFalse(any("policy_hash" in k or "api_hash" in k or "product_id" in k or "revision" in k for k in keys))

    def test_no_unsupported_phase_feature_added(self):
        for row in self.features:
            if row["source_packet"]==list(self.sources)[1] and row["head"]=="primary_is_payment_proposal":
                self.assertFalse(any("post_verified_account" in k for k in row["replay_features"]["features"]))

    def test_future_interface_is_closed(self):
        c=data.alignment_contract_v6()
        self.assertEqual(c["status"],"no_alignment_before_parent_admission")
        self.assertIn("exact_target_set",c["join_key"])
        self.assertIn("NEW_actual_parent_admission_receipt_and_independently_supplied_trust_anchor",c["required_arguments"])

    def test_staged_alignment_missing_reviews_cannot_enable_masks(self):
        r=data.stage_alignment_request_v6()
        self.assertFalse(r["admitted"]);self.assertFalse(r["loss_masks_enabled"])
        self.assertFalse(r["annotation_contents_consumed"])
        self.assertIn("new_parent_admission_pin",r["missing_bindings"])

    def test_unknown_source_is_not_semantic_absence(self):
        for r in self.candidates:
            self.assertFalse(r["absence_established"])
            self.assertFalse(r["live_ingress_authenticated"])

    def test_all_native_export_paths_actually_executed(self):
        counts={}
        for p in self.profiles.values():
            for k,v in p["counts"].items():counts[k]=counts.get(k,0)+v
        self.assertEqual(counts["detector_native_export_rows"],132)
        self.assertEqual(counts["primary_native_export_feature_rows"],132)
        self.assertEqual(counts["wire_native_export_rows"],132)
        self.assertEqual(counts["DATE_native_export_feature_pairs"],210)
        self.assertEqual(counts["syntax:unsupported"],4)
        self.assertEqual(counts["DATE_mask:unsupported_dependency"],4)

    def test_clipped_window_not_relabelled_unfinished(self):
        clipped=[r for r in self.features if r["head"]=="date_completion" and
                 r["replay_features"]["reason"]=="window_scope_clipped"]
        self.assertEqual(len(clipped),23)
        for r in clipped:
            self.assertIsNone(r["label"]);self.assertFalse(r["loss_mask"])

    def test_unicode_source_packet_hash_change_fails_closed(self):
        first=next(iter(data.PACKETS))
        original=(data.ROOT/first).read_bytes()
        with patch.object(Path,"read_bytes",return_value=original+b" "):
            with self.assertRaises(data.SourceRejected):data.load_sources()

    def test_strict_parser_profile_keeps_unknown_phase_literal(self):
        s=self.source();s["phase"]="post_verified_account"
        data.validate_snapshot(s)
        self.assertEqual(s["phase"],"post_verified_account")


if __name__=="__main__":unittest.main()
