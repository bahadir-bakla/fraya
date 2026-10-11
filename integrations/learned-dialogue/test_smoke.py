import copy
import json
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_data import freeze
from inference import features, local_snapshot, predict
from train_eval import HERE, integrity, load_data, load_model, validate_model, write_json
from validation import validate_proposal


class PrototypeSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records, cls.oracle, cls.manifest, cls.split_check = load_data()
        cls.model = load_model()

    def test_group_disjoint_split(self):
        self.assertTrue(self.split_check["passed"])
        self.assertEqual(self.split_check["records"], 96)

    def test_reject_each_cross_split_group(self):
        for key in ("source_group", "semantic_template_group", "scenario_family"):
            rows = copy.deepcopy(self.records)
            held = next(r for r in rows if r["split"] == "holdout")
            held[key] = rows[0][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                integrity(rows)

    def test_reject_hidden_augmentation_ancestor(self):
        rows = copy.deepcopy(self.records)
        next(r for r in rows if r["split"] == "holdout")["augmentation_parent"] = rows[0]["id"]
        with self.assertRaises(ValueError):
            integrity(rows)

    def test_reject_duplicate_text(self):
        rows = copy.deepcopy(self.records)
        rows[-1]["utterance"] = rows[0]["utterance"].upper()
        with self.assertRaises(ValueError):
            integrity(rows)

    def test_immutable_oracle_writer(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / "frozen.json"
            freeze(path, b"first")
            freeze(path, b"first")
            with self.assertRaises(ValueError):
                freeze(path, b"changed")
            self.assertEqual(path.read_bytes(), b"first")

    def test_labels_outside_features(self):
        vector = features(self.records[0]["utterance"])
        self.assertTrue(all(k.startswith(("w:", "b:", "c:")) for k in vector))
        self.assertFalse(any(head in self.records[0] for head in self.model["heads"]))
        train_words = set(" ".join(r["utterance"].lower() for r in self.records if r["split"] == "train").split())
        self.assertNotIn("violin", self.model["word_vocabulary"])

    def test_exact_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory(dir=HERE) as directory:
            path = Path(directory) / "roundtrip.json"
            write_json(path, self.model)
            restored = load_model(path)
            for record in self.records:
                snapshot = local_snapshot(record["utterance"], record["id"])
                self.assertEqual(predict(snapshot, self.model), predict(snapshot, restored))

    def test_reject_bad_model(self):
        model = copy.deepcopy(self.model)
        model["heads"]["primaryintent"]["weights"][0]["w:bad"] = float("nan")
        with self.assertRaises(ValueError):
            validate_model(model)

    def test_forbidden_side_effects_and_no_mutation(self):
        snapshot = local_snapshot("Please call me back later about this fictional account.")
        original_snapshot, original_model = copy.deepcopy(snapshot), copy.deepcopy(self.model)
        with patch("builtins.open", side_effect=AssertionError("file access")), patch.object(socket, "socket", side_effect=AssertionError("network")), patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            result = predict(snapshot, self.model)
            self.assertTrue(validate_proposal(result, snapshot))
        self.assertEqual(snapshot, original_snapshot)
        self.assertEqual(self.model, original_model)

    def test_uncalibrated_fail_closed(self):
        model = copy.deepcopy(self.model)
        model["calibration"]["fitted"] = False
        output = predict(local_snapshot("Please call me back later about this fictional account."), model)
        self.assertTrue(output["abstain"])
        self.assertIn("uncalibrated_bundle", output["reasons"])

    def test_uncertain_input_guard(self):
        inputs = ["I could pay one hundred and", "I can pay Friday, actually I meant Monday.",
                  "I do not agree to that payment.", "Maybe call me back tomorrow.",
                  "Purple robots compose crystal violin symphonies.", "", "yes", "Friday", "1234",
                  "Please call me back at", "My security PIN is 1234."]
        for text in inputs:
            with self.subTest(text=text):
                result = predict(local_snapshot(text), self.model)
                self.assertTrue(result["abstain"])
                self.assertTrue(validate_proposal(result, local_snapshot(text)))

    def test_value_components_not_canonicalized(self):
        text = "I want to pay 123 on Friday; the security answer is fictional."
        output = predict(local_snapshot(text), self.model)
        self.assertTrue(output["abstain"])
        components = output["clauses"][0]["components"]
        for component in ("amount", "date", "security"):
            self.assertEqual(components[component]["status"], "ambiguous")
            self.assertTrue(components[component]["evidence_spans"])
        self.assertNotIn("123", json.dumps(output))

    def test_untrusted_raw_text_abstains(self):
        snapshot = local_snapshot("Please call me back later about this fictional account.")
        snapshot["raw_text_provenance"] = "extracted_copy"
        output = predict(snapshot, self.model)
        self.assertTrue(output["abstain"])
        self.assertIn("trusted_latest_raw_turn_adapter_unverified", output["reasons"])

    def test_reject_stale_bindings_and_bad_span(self):
        snapshot = local_snapshot("Please call me back later about this fictional account.")
        output = predict(snapshot, self.model)
        for key, bad in (("turn_id", "next"), ("state_revision", 2), ("policy_hash", "a" * 64)):
            changed = dict(snapshot, **{key: bad})
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_proposal(output, changed)
        changed_output = copy.deepcopy(output)
        changed_output["clauses"][0]["evidence_span"]["end"] = 10000
        with self.assertRaises(ValueError):
            validate_proposal(changed_output, snapshot)

    def test_reject_authority_or_tool_injection(self):
        snapshot = local_snapshot("Please call me back later about this fictional account.")
        output = predict(snapshot, self.model)
        output["permission"] = True
        with self.assertRaises(ValueError):
            validate_proposal(output, snapshot)

    def test_at_least_one_complete_proposal_is_usable(self):
        accepted = [r for r in self.records if r["split"] == "holdout" and not predict(local_snapshot(r["utterance"], r["id"]), self.model)["abstain"]]
        self.assertEqual(len(accepted), 4)
        self.assertTrue(all(not self.oracle[r["id"]]["must_abstain"] for r in accepted))


if __name__ == "__main__":
    unittest.main(verbosity=2)
