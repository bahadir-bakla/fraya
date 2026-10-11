"""In-memory fixture tests only: not dataworker labels or qualification data."""
import copy
import hashlib
import json
import socket
import subprocess
import unittest
from unittest.mock import patch

from context_v2 import (BindingContext, InputRejected, binding_v2, candidate_spans_v2, check_deferred_refusal_v2,
                        feature_v2, predict_v2, reference_candidate_v2)
from export_v2 import export_v2
from train_v2 import fit_v2, prepare_examples, strict_json
from validate_v2 import freeze_contract_v2, validate_v2


def fixture_snapshot(text="Yes.", role="offer"):
    return {"schema_version": "semantic_input.v1", "call_local_id": "unit-fixture", "turn_id": "turn-unit", "state_revision": 9,
            "policy_hash": hashlib.sha256(b"fictional-test-policy").hexdigest(), "api_hash": hashlib.sha256(b"fictional-test-api").hexdigest(),
            "utterance": {"text": text, "source": "authored_fixture", "source_turn_id": "turn-unit", "complete_transport": True, "offset_unit": "python_unicode_codepoints"},
            "phase": role, "question": {"role": role, "spoken_offer_id": "unit-offer-1"}, "targets": [{"index": 0, "type": "fictional_card"}],
            "pending": [{"target_index": 0, "component_revision": 4, "spoken_offer_id": "unit-offer-1", "components": {}}],
            "spoken_offers": [{"offer_id": "unit-offer-1", "state_revision": 8, "spoken_turn_id": "prior-unit-turn", "superseded": False}],
            "active_readback": {"readback_id": "unit-readback-1", "state_revision": 9, "valid": True, "completed_speech": True}}


def unit_training_records():
    labels = {"recipient": "recipient_self", "offer": "offer_acceptance", "readback": "readback_affirmation",
              "support": "support_acceptance", "security": "unknown", "none": "unknown"}
    return [{"example_id": f"unit-only-{i}-{j}", "lineage_group_id": "unit-only-no-independence-claim", "split": "train",
             "input": fixture_snapshot(text, role), "source": {"fictional": True},
             "labels": {"primary_intent": {"value": label, "observed": True},
                        "secondary_intents": {"value": [], "observed": True}, "components": []},
             "annotation": {"status": "unreviewed", "reviewer_ids": []}}
            for i, (role, label) in enumerate(labels.items()) for j, text in enumerate(("Yes.", "Yes, please."))]


class ContextV2Smoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        freeze_contract_v2()
        examples, cls.prepared = prepare_examples(unit_training_records(), "train")
        cls.model, _ = fit_v2(examples, epochs=120, max_features=128)
        cls.bundle = {"model_id": hashlib.sha256(json.dumps(cls.model, sort_keys=True).encode()).hexdigest(), "model": cls.model}
        cls.source, cls.export = export_v2(cls.bundle)
        cls.namespace = {}
        exec(compile(cls.source, "v2-unit-export", "exec"), {"__builtins__": __builtins__}, cls.namespace)

    def run_fixture(self, snapshot):
        context = BindingContext(binding_v2(snapshot), self.bundle["model_id"])
        result = predict_v2(snapshot, self.bundle, context)
        validate_v2(result, snapshot, self.bundle, context)
        return result

    def test_context_conditions_same_utterance(self):
        observed = {role: self.run_fixture(fixture_snapshot("Yes.", role))["primary"]["label"]
                    for role in ("recipient", "offer", "readback", "support", "none")}
        self.assertEqual(observed, {"recipient": "recipient_self", "offer": "offer_acceptance", "readback": "readback_affirmation", "support": "support_acceptance", "none": "unknown"})

    def test_untrained_masks_and_no_acceptance(self):
        output = self.run_fixture(fixture_snapshot("I can pay one hundred on Friday."))
        self.assertEqual(output["status"], "abstain")
        self.assertTrue(output["abstentions"])
        self.assertFalse(self.model["qualification"]["component_completion"]["trained"])
        self.assertTrue(all(c["completion"] == "ambiguous" for c in output["clauses"][0]["components"]))
        self.assertEqual(output["consent_signal"]["decision"], "descriptive_only")

    def test_binding_context_immutable(self):
        context = BindingContext(binding_v2(fixture_snapshot()), self.bundle["model_id"])
        with self.assertRaises(InputRejected):
            context.model_id = "a" * 64

    def test_no_binding_never_fabricates_hashes(self):
        with self.assertRaises(InputRejected):
            predict_v2({}, self.bundle)
        with self.assertRaises(InputRejected):
            BindingContext({}, self.bundle["model_id"])

    def test_empty_malformed_bound_input_fail_closed(self):
        context = BindingContext(binding_v2(fixture_snapshot()), self.bundle["model_id"])
        for bad in (None, {}, [], "bad", dict(fixture_snapshot(), utterance={})):
            output = predict_v2(bad, self.bundle, context)
            self.assertEqual(output["status"], "abstain")
            self.assertEqual(output["binding"], context.binding())
            self.assertIsNone(output["primary"])

    def test_stale_binding_authoritative_context(self):
        snapshot = fixture_snapshot()
        context = BindingContext(dict(binding_v2(snapshot), state_revision=10), self.bundle["model_id"])
        output = predict_v2(snapshot, self.bundle, context)
        self.assertEqual(output["binding"]["state_revision"], 10)
        self.assertEqual(output["abstentions"][0]["reason"], "stale_binding")

    def test_untrusted_or_truncated_input(self):
        for key, value in (("source", "extracted_copy"), ("complete_transport", False), ("source_turn_id", "old")):
            snapshot = fixture_snapshot()
            snapshot["utterance"][key] = value
            output = self.run_fixture(snapshot)
            self.assertIsNone(output["primary"])

    def test_candidate_and_qualifier_overflow_abstain(self):
        for text in (" ".join(str(i) for i in range(25)), " ".join(["no"] * 25)):
            output = self.run_fixture(fixture_snapshot(text))
            self.assertEqual(output["abstentions"][0]["reason"], "size_limit")
            self.assertFalse(output["clauses"])

    def test_regex_miss_does_not_mean_absent(self):
        output = self.run_fixture(fixture_snapshot("Le montant serait cent vingt; le cinq mars."))
        self.assertTrue(all(c["completion"] == "ambiguous" for c in output["clauses"][0]["components"]))

    def test_sibling_span_boundaries(self):
        snapshot = fixture_snapshot("Actually make the amount one hundred and the date Fri...")
        spans = candidate_spans_v2(snapshot)
        surfaces = {s["name"]: snapshot["utterance"]["text"][s["start"]:s["end"]] for s in spans}
        self.assertEqual(surfaces["amount"], "one hundred")
        self.assertEqual(surfaces["date"], "Fri...")

    def test_spoken_offer_vs_readback_reference(self):
        snapshot = fixture_snapshot()
        self.assertEqual(reference_candidate_v2(snapshot, "offer_acceptance"), ("unit-offer-1", None, None))
        self.assertEqual(reference_candidate_v2(snapshot, "readback_affirmation"), (None, "unit-readback-1", None))
        snapshot["active_readback"] = None
        self.assertEqual(reference_candidate_v2(snapshot, "readback_affirmation"), (None, None, "unresolved_reference"))
        snapshot["spoken_offers"][0]["superseded"] = True
        self.assertEqual(reference_candidate_v2(snapshot, "offer_acceptance"), (None, None, "unresolved_reference"))

    def test_deferred_refusal_cannot_restore_old_revision(self):
        pending = fixture_snapshot()["pending"]
        event = {"target_index": 0, "component_revision": 3, "offer_id": "unit-offer-1"}
        self.assertFalse(check_deferred_refusal_v2(pending, event)["eligible_for_kernel_review"])
        event["component_revision"] = 4
        self.assertTrue(check_deferred_refusal_v2(pending, event)["eligible_for_kernel_review"])
        self.assertFalse(check_deferred_refusal_v2([{"target_index": 0}], {})["eligible_for_kernel_review"])

    def test_no_ids_hashes_or_policy_values_in_features(self):
        first = fixture_snapshot("3142", "security")
        second = copy.deepcopy(first)
        second["turn_id"] = "different"
        second["policy_hash"] = "a" * 64
        second["spoken_offers"][0]["offer_id"] = "other-offer"
        second["utterance"]["text"] = "9876"
        self.assertEqual(feature_v2(first), feature_v2(second))
        candidate = {"name": "security_answer", "start": 0, "end": 4}
        self.assertEqual(feature_v2(first, candidate), feature_v2(second, candidate))

    def test_no_io_or_mutation(self):
        snapshot = fixture_snapshot()
        context = BindingContext(binding_v2(snapshot), self.bundle["model_id"])
        original = copy.deepcopy((snapshot, self.bundle))
        with patch("builtins.open", side_effect=AssertionError("file")), patch.object(socket, "socket", side_effect=AssertionError("network")), patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            output = predict_v2(snapshot, self.bundle, context)
            embedded = self.namespace["predict_context_embedded"](snapshot, context.binding())
        self.assertEqual(output, embedded)
        self.assertEqual((snapshot, self.bundle), original)

    def test_export_bounds_parity_and_unsupported_authority_fields(self):
        self.assertLess(self.export["utf8_bytes"], 500000)
        self.assertLess(self.export["coefficient_count"], 100000)
        for role in ("recipient", "offer", "readback", "support", "none"):
            snapshot = fixture_snapshot(role=role)
            output = self.run_fixture(snapshot)
            self.assertEqual(output, self.namespace["predict_context_embedded"](snapshot, binding_v2(snapshot)))
            self.assertNotIn("input_sha256", output)
            changed = copy.deepcopy(output)
            changed["permission"] = True
            with self.assertRaises(Exception):
                validate_v2(changed, snapshot, self.bundle, BindingContext(binding_v2(snapshot), self.bundle["model_id"]))

    def test_missing_secondary_is_masked_and_duplicate_json_rejected(self):
        record = unit_training_records()[0]
        record["labels"].pop("secondary_intents")
        rows, report = prepare_examples([record], "train")
        self.assertFalse(any(row["head"] == "secondary" for row in rows))
        with self.assertRaises(ValueError):
            strict_json('{"value":1,"value":2}')
        with self.assertRaises(ValueError):
            strict_json('{"value":NaN}')
        with self.assertRaises(ValueError):
            strict_json('{"value":1e400}')

    def test_nonfinite_model_fails_closed(self):
        bad = copy.deepcopy(self.bundle)
        bad["model"]["heads"]["primary"]["bias"][0] = float("nan")
        snapshot = fixture_snapshot()
        result = predict_v2(snapshot, bad, BindingContext(binding_v2(snapshot), self.bundle["model_id"]))
        self.assertIsNone(result["primary"])
        self.assertEqual(result["abstentions"][0]["reason"], "runtime_failure")

    def test_pending_features_are_current_target_specific(self):
        first = fixture_snapshot()
        first["question"]["target_indices"] = [0]
        first["pending"][0]["components"] = {"amount": {"status": "complete"}}
        first["pending"].append({"target_index": 1, "components": {"amount": {"status": "unfinished"}}})
        second = copy.deepcopy(first)
        second["question"]["target_indices"] = [1]
        self.assertNotEqual(feature_v2(first), feature_v2(second))
        self.assertEqual(feature_v2(first, include_context=False), feature_v2(second, include_context=False))

    def test_no_context_disables_reference_paths(self):
        snapshot = fixture_snapshot()
        self.assertEqual(reference_candidate_v2(snapshot, "offer_acceptance", include_context=False), (None, None, "unresolved_reference"))
        self.assertEqual(reference_candidate_v2(snapshot, "readback_affirmation", include_context=False), (None, None, "unresolved_reference"))

    def test_multiple_candidates_preserve_unresolved_evidence(self):
        snapshot = fixture_snapshot("I can pay one hundred or two hundred.")
        output = self.run_fixture(snapshot)
        amount = next(c for c in output["clauses"][0]["components"] if c["name"] == "amount")
        self.assertEqual(amount["completion"], "ambiguous")
        self.assertEqual(len(amount["evidence"]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
