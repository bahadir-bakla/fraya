"""Local admission tests. Authorization receipts below are in-memory unit doubles.

They are never saved or represented as real parent permission. No trainer,
development labels, other agents, cloud, network or secrets are accessed.
"""
import copy
import unittest
from collections import Counter
from unittest.mock import patch

import narrow_review_v4 as admission


class ReviewedAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = admission.load_allowed_inputs()
        cls.documents = {p: admission.strict_json(raw) for p, raw in cls.raw.items()}
        cls.validated = admission.validate_reviewed_inputs(cls.raw)
        cls.splits = [{"group_id": group, "split": "train"}
                      for group in sorted(set(cls.validated["aliases"].values()))]
        # Exact match double for a detector; does not certify actual detections.
        cls.candidates = [{"id": "unit-detector:" + row["id"], "example_id": row["example_id"],
                           "target_indices": row["target_indices"], "source_span": row["source_span"],
                           "candidate_role": "current"} for row in cls.validated["date_annotations"]]

    def receipt_double(self, heads=("primary",), candidates=None, splits=None):
        """Simulated trusted test boundary only; never a real approval artifact."""
        splits = self.splits if splits is None else splits
        baseline = admission.assess_admission(self.raw, candidates=candidates, split_assignments=splits)
        receipt = {"schema_version": "parent_cpu_engineering_authorization.v4", "issuer": "parent",
                   "cpu_only": True, "gpu_authorized": False, "qualified": False, "payment_authority": False,
                   "source_raw_sha256": admission.PINNED_SHA256,
                   "definitions_sha256": baseline["definitions_sha256"],
                   "source_vectors_sha256": baseline["source_vectors_sha256"],
                   "candidate_vector_sha256": baseline["candidate_vector_sha256"],
                   "split_assignments_sha256": baseline["split_assignments_sha256"],
                   "historical_immutability_required": False,
                   "acknowledges_unknown_reviewer_a_history": True,
                   "heads": list(heads),
                   "reviewer_registry": {rid: {"thread_id": thread,
                       "parent_verified_isolated_blind_source_review": True,
                       "is_original_author": False} for rid, thread in zip(admission.REVIEWER_IDS,
                           sorted(admission.EXPECTED_REVIEW_THREAD_IDS) + [admission.EXPECTED_ADJUDICATOR_THREAD_ID])}}
        raw = admission.encoded(receipt)
        return {"authorization_raw": raw, "trusted_authorization_sha256": admission.sha(raw),
                "split_assignments": splits, "candidates": candidates}

    def mutated_documents(self):
        return copy.deepcopy(self.documents)

    def test_real_inputs_pass_structural_validation_without_authorization(self):
        result = admission.assess_admission(self.raw)
        self.assertTrue(result["data_validated"])
        self.assertFalse(result["admitted"])
        self.assertFalse(result["cpu_authorized"])
        self.assertFalse(result["gpu_authorized"])
        self.assertEqual(result["mask_counts"], {"primary": 11, "date_whole_row": 3})
        self.assertEqual(result["support"]["primary"]["positive_groups"], 27)
        self.assertEqual(result["support"]["primary"]["additional_negative_groups"], 21)
        self.assertEqual(result["support"]["date_whole_row"]["negative_groups"], 19)
        self.assertFalse(result["support"]["date_whole_row"]["floors_met"])
        self.assertEqual(result["annotated_candidate_support"]["negative_groups"], 20)
        self.assertEqual(result["support"]["date_scoped_candidate"]["positive_groups"], 0)
        self.assertTrue(all(not rows for rows in result["eligible_rows"].values()))

    def test_received_hash_does_not_certify_historical_immutability(self):
        result = admission.assess_admission(self.raw, require_historical_immutability=True)
        self.assertIn("historical_reviewer_a_immutability_unverifiable", result["reasons"])
        self.assertIn("unknown", result["historical_reviewer_a_immutability"])
        args = self.receipt_double()
        receipt = admission.strict_json(args["authorization_raw"])
        receipt["historical_immutability_required"] = True
        args["authorization_raw"] = admission.encoded(receipt)
        args["trusted_authorization_sha256"] = admission.sha(args["authorization_raw"])
        self.assertFalse(admission.assess_admission(self.raw, **args)["admitted"])

    def test_all_five_raw_hash_changes_fail_closed(self):
        for path in self.raw:
            with self.subTest(path=path):
                changed = dict(self.raw)
                changed[path] += b"\n"
                result = admission.assess_admission(changed)
                self.assertIn("input_raw_hash_mismatch:" + path, result["reasons"])
                self.assertFalse(result["admitted"])

    def test_missing_0073_and_new_lineage_0109_are_not_optional(self):
        for example_id in ("CSv2-E-0073", "CSv2-E-0109"):
            with self.subTest(example_id=example_id):
                documents = self.mutated_documents()
                rows = documents[admission.PATHS["reviewer-a"]]["primary_records"]
                self.assertTrue(any(row["example_id"] == example_id for row in rows))
                rows[:] = [row for row in rows if row["example_id"] != example_id]
                with self.assertRaisesRegex(admission.AdmissionError, "review_all_members_ordered_exactly_once"):
                    admission._validate_documents(documents)
        ids = {item["example_id"] for item in self.validated["source_vectors"]["primary"]}
        self.assertIn("CSv2-E-0109", ids)

    def test_changed_0109_lineage_is_rejected(self):
        documents = self.mutated_documents()
        row = next(r for r in documents[admission.PATHS["reviewer-b"]]["primary_records"] if r["example_id"] == "CSv2-E-0109")
        row["lineage_group_id"] = "invented-old-root"
        with self.assertRaisesRegex(admission.AdmissionError, "source_identity_or_lineage_mismatch"):
            admission._validate_documents(documents)

    def test_packet_duplicate_and_missing_selected_root_rejected(self):
        documents = self.mutated_documents()
        packet = documents[admission.PATHS["primary"]]
        packet["records"][1] = copy.deepcopy(packet["records"][0])
        with self.assertRaisesRegex(admission.AdmissionError, "packet_duplicate_member"):
            admission._validate_documents(documents)
        documents = self.mutated_documents()
        documents[admission.PATHS["primary"]]["selected_canonical_groups"].pop()
        with self.assertRaisesRegex(admission.AdmissionError, "packet_selected_group_closure"):
            admission._validate_documents(documents)

    def test_unknown_labels_and_source_spans_rejected(self):
        documents = self.mutated_documents()
        documents[admission.PATHS["reviewer-a"]]["primary_records"][0]["label"] = "payment_permission"
        with self.assertRaisesRegex(admission.AdmissionError, "unknown_annotation_label"):
            admission._validate_documents(documents)
        for change, message in (({"raw_field_path": "/records/0/input/missing/text"}, "unknown_span_pointer"),
                                ({"text": "invented meaning"}, "span_exact_text_mismatch"),
                                ({"raw_field_path": "/records/1/input/utterance/text"}, "span_outside_source_member"),
                                ({"offset_unit": "utf16"}, "unknown_span_unit"),
                                ({"utf8_byte_end": 1}, "span_utf8_mismatch")):
            with self.subTest(change=change):
                documents = self.mutated_documents()
                span = documents[admission.PATHS["adjudication"]]["primary_records"][0]["adjudication"]["evidence_spans"][0]
                span.update(change)
                with self.assertRaisesRegex(admission.AdmissionError, message):
                    admission._validate_documents(documents)

    def test_annotation_source_input_hash_and_snapshot_rejected(self):
        documents = self.mutated_documents()
        documents[admission.PATHS["adjudication"]]["primary_records"][0]["source_input_json_sha256"] = "0" * 64
        with self.assertRaisesRegex(admission.AdmissionError, "source_input_hash_mismatch"):
            admission._validate_documents(documents)
        documents = self.mutated_documents()
        documents[admission.PATHS["reviewer-a"]]["primary_records"][0]["source_input"]["utterance"]["text"] = "changed"
        with self.assertRaisesRegex(admission.AdmissionError, "source_input_snapshot_mismatch"):
            admission._validate_documents(documents)

    def test_agreement_cannot_be_changed_and_third_party_required(self):
        documents = self.mutated_documents()
        documents[admission.PATHS["adjudication"]]["adjudicator_id"] = "reviewer-a"
        with self.assertRaisesRegex(admission.AdmissionError, "third_party_adjudicator_required"):
            admission._validate_documents(documents)
        documents = self.mutated_documents()
        decision = documents[admission.PATHS["adjudication"]]["primary_records"][0]["adjudication"]
        decision.update(finalLabel="negative", binary_value=False)
        with self.assertRaisesRegex(admission.AdmissionError, "adjudication_changed_agreement"):
            admission._validate_documents(documents)

    def test_fabricated_self_authorization_has_no_trusted_parent_anchor(self):
        args = self.receipt_double()
        del args["trusted_authorization_sha256"]
        result = admission.assess_admission(self.raw, **args)
        self.assertFalse(result["admitted"])
        self.assertIn("externally_trusted_exact_hash_parent_authorization_missing", result["reasons"])
        args = self.receipt_double()
        args["trusted_authorization_sha256"] = "0" * 64
        self.assertIn("external_parent_authorization_hash_mismatch", admission.assess_admission(self.raw, **args)["reasons"])
        args = self.receipt_double()
        receipt = admission.strict_json(args["authorization_raw"])
        receipt["issuer"] = "narrow_review_v4"
        args["authorization_raw"] = admission.encoded(receipt)
        args["trusted_authorization_sha256"] = admission.sha(args["authorization_raw"])
        self.assertFalse(admission.assess_admission(self.raw, **args)["admitted"])

    def test_parent_binding_and_roster_fail_closed(self):
        for field, value in (("source_raw_sha256", {}), ("definitions_sha256", "0" * 64),
                             ("reviewer_registry", {}), ("gpu_authorized", True)):
            with self.subTest(field=field):
                args = self.receipt_double()
                receipt = admission.strict_json(args["authorization_raw"])
                receipt[field] = value
                args["authorization_raw"] = admission.encoded(receipt)
                args["trusted_authorization_sha256"] = admission.sha(args["authorization_raw"])
                self.assertFalse(admission.assess_admission(self.raw, **args)["admitted"])

    def test_trusted_boundary_double_builds_only_reviewed_primary_rows(self):
        args = self.receipt_double()
        with patch("builtins.open", side_effect=AssertionError("unexpected I/O")):
            rows = admission.build_cpu_training_rows(self.raw, "primary", **args)
        self.assertEqual(len(rows), 108)
        self.assertEqual(Counter(row["y"] for row in rows), {1: 71, 0: 37})
        self.assertTrue(all(row["mask"] and row["split"] == "train" for row in rows))
        self.assertTrue(all(row["group"] == row["source_binding"]["canonical_group_id"] for row in rows))
        self.assertTrue(all("permission" not in row and "payment_authority" not in row for row in rows))

    def test_whole_date_floor_cannot_be_replaced_by_candidate_floor(self):
        args = self.receipt_double(("date_whole_row",), self.candidates)
        result = admission.assess_admission(self.raw, **args)
        self.assertFalse(result["admitted"])
        self.assertIn("adjudicated_aligned_group_floor_unmet", result["reasons"])
        with self.assertRaises(admission.AdmissionError):
            admission.build_cpu_training_rows(self.raw, "date_whole_row", **args)

    def test_actual_candidate_alignment_required_not_row_count(self):
        args = self.receipt_double(("date_scoped_candidate",))
        self.assertFalse(admission.assess_admission(self.raw, **args)["admitted"])
        args = self.receipt_double(("date_scoped_candidate",), self.candidates)
        result = admission.assess_admission(self.raw, **args)
        self.assertTrue(result["admitted"])
        self.assertEqual(result["alignment"], {"provided": True, "matched": 74, "unmatched": 0, "masked": 1})
        self.assertEqual(result["support"]["date_scoped_candidate"]["negative_groups"], 20)
        rows = admission.build_cpu_training_rows(self.raw, "date_scoped_candidate", **args)
        self.assertEqual(len(rows), 74)
        self.assertTrue(all(row["label"] != "ambiguous" and row["source_span"] for row in rows))

    def test_insufficient_aligned_group_support_cannot_admit(self):
        extra_root = "SV3-G-5788dc9debc768037ce9"
        remove = {r["example_id"] for r in self.validated["date_annotations"] if r["group"] == extra_root}
        candidates = [c for c in self.candidates if c["example_id"] not in remove]
        result = admission.assess_admission(self.raw, **self.receipt_double(("date_scoped_candidate",), candidates))
        self.assertFalse(result["admitted"])
        self.assertEqual(result["support"]["date_scoped_candidate"]["negative_groups"], 19)
        # Repetition never inflates support; duplicates are rejected outright.
        candidates = copy.deepcopy(self.candidates)
        duplicate = copy.deepcopy(candidates[0])
        duplicate["id"] += ":copy"
        candidates.append(duplicate)
        with self.assertRaisesRegex(admission.AdmissionError, "duplicate_detector_candidate_scope"):
            admission.align_date_candidates(candidates, self.validated)

    def test_wrong_scope_candidate_does_not_acquire_label(self):
        candidates = copy.deepcopy(self.candidates)
        candidates[0]["source_span"]["char_start"] += 1
        candidates[0]["source_span"]["text"] = candidates[0]["source_span"]["text"][1:]
        candidates[0]["source_span"]["utf8_byte_start"] += 1
        aligned, status = admission.align_date_candidates(candidates, self.validated)
        self.assertEqual(status["unmatched"], 1)
        self.assertEqual(len(aligned), 73)
        candidates = copy.deepcopy(self.candidates)
        candidates[0]["label"] = "complete"
        with self.assertRaisesRegex(admission.AdmissionError, "detector_must_not_supply_supervision"):
            admission.align_date_candidates(candidates, self.validated)
        candidates = copy.deepcopy(self.candidates)
        candidates[0]["target_indices"] = [999]
        with self.assertRaisesRegex(admission.AdmissionError, "candidate_target_scope_unknown"):
            admission.align_date_candidates(candidates, self.validated)

    def test_group_train_dev_aliases_are_rejected(self):
        aliases = self.validated["aliases"]
        alias = next(a for a, root in aliases.items() if a != root)
        declarations = self.splits + [{"group_id": alias, "split": "dev"}]
        with self.assertRaisesRegex(admission.AdmissionError, "group_train_dev_or_holdout_alias_leakage"):
            admission.validate_split_assignments(declarations, aliases)
        result = admission.assess_admission(self.raw, **self.receipt_double(splits=declarations))
        self.assertFalse(result["admitted"])

    def test_no_extra_inputs_and_duplicate_json_keys(self):
        raw = {**self.raw, "unrequested-source": b"{}"}
        self.assertIn("exact_allowed_input_set_required", admission.assess_admission(raw)["reasons"])
        with self.assertRaisesRegex(admission.AdmissionError, "duplicate_json_key"):
            admission.strict_json(b'{"issuer":"parent","issuer":"self"}')


if __name__ == "__main__":
    unittest.main()
