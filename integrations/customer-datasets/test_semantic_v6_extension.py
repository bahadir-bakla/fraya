"""Source-only QA of the new author packet. No detector, model, old source or DEV reads.

Run: python -B -m unittest discover -s integrations/customer-datasets
     -p test_semantic_v6_extension.py -v
"""
import copy
import datetime
import hashlib
import json
import re
import unittest
from collections import Counter
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "research/customer-benchmark/semantic-v6-extension"
FORBIDDEN_KEYS = {"labels", "primary_label", "author_label", "expected", "prediction", "predictions",
                  "oracle", "oracle_annotations", "rationale", "collection_axis", "author_id",
                  "nomination", "family_goal", "sampling_strata", "y", "date_candidates",
                  "source_span", "completion_supervision", "family", "declared_lineage_id"}


def canonical_digest(obj):
    data = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def assert_label_free(obj, path=""):
    if isinstance(obj, dict):
        for k, value in obj.items():
            if k in FORBIDDEN_KEYS:
                raise ValueError("forbidden packet field " + path + "/" + k)
            # Target.label is an input identifier required by semantic_input.v1.
            if k == "label" and not re.fullmatch(r"/records/\d+/input/targets/\d+", path):
                raise ValueError("label outside input target identity")
            assert_label_free(value, path + "/" + k)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            assert_label_free(value, path + "/" + str(i))


def assert_span(span, packet):
    match = re.fullmatch(r"/records/(\d+)/input/utterance/text", span["raw_field_path"])
    if not match:
        raise ValueError("invalid typed source path")
    index = int(match.group(1))
    if not 0 <= index < len(packet["records"]):
        raise ValueError("source record out of bounds")
    text = packet["records"][index]["input"]["utterance"]["text"]
    start, end = span["char_start"], span["char_end"]
    if span["offset_unit"] != "python_unicode_codepoints" or not 0 <= start < end <= len(text):
        raise ValueError("invalid Unicode bounds")
    if text[start:end] != span["text"]:
        raise ValueError("source text mismatch")
    byte_start = len(text[:start].encode("utf-8"))
    byte_end = len(text[:end].encode("utf-8"))
    if (span["utf8_byte_start"], span["utf8_byte_end"]) != (byte_start, byte_end):
        raise ValueError("invalid UTF8 bounds")
    if text.encode("utf-8")[byte_start:byte_end].decode("utf-8") != span["text"]:
        raise ValueError("UTF8 source mismatch")


def assert_semantic_input(inp):
    known = {x["index"] for x in inp["targets"]}
    if len(known) != len(inp["targets"]):
        raise ValueError("duplicate target")
    if not set(inp["question"]["target_indices"]).issubset(known):
        raise ValueError("question references undeclared target")
    if inp["utterance"]["source_turn_id"] != inp["turn_id"]:
        raise ValueError("wrong source turn")
    if inp["phase"] == "security" or inp["question"]["role"] == "security" or inp["question"].get("security_field") is not None:
        raise ValueError("security surface")
    if inp["spoken_offers"] or inp["active_readback"] is not None:
        raise ValueError("unsupported offer/readback context")
    if {x["target_index"] for x in inp["pending"]} != known or len(inp["pending"]) != len(known):
        raise ValueError("pending target closure")
    for pending in inp["pending"]:
        if pending["unresolved_components"]:
            raise ValueError("prior state must be complete")
        for component in pending["components"].values():
            if component["status"] != "complete" or not component["revision"] or component["evidence_refs"]:
                raise ValueError("incomplete or unsupported prior state")
        if float(pending["components"]["amount"]["value"]) <= 0:
            raise ValueError("invalid fictional amount")
        datetime.date.fromisoformat(pending["components"]["date"]["value"])


class SemanticV6SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_packet = (ROOT / "label-free-train-packet.json").read_bytes()
        cls.packet = json.loads(cls.raw_packet)
        cls.schema = json.loads((ROOT / "packet.schema.json").read_bytes())
        cls.manifest = json.loads((ROOT / "manifest.json").read_bytes())
        cls.by_id = {r["example_id"]: r for r in cls.packet["records"]}

    def test_strict_source_schema_and_label_absence(self):
        jsonschema.Draft202012Validator.check_schema(self.schema)
        jsonschema.Draft202012Validator(self.schema).validate(self.packet)
        assert_label_free(self.packet)
        for record in self.packet["records"]:
            self.assertEqual(set(record), {"example_id", "input"})
            self.assertRegex(record["example_id"], r"^[0-9a-f]{24}$")

    def test_source_hashes_and_artifact_closure(self):
        self.assertEqual(hashlib.sha256(self.raw_packet).hexdigest(), self.manifest["source_packet_raw_sha256"])
        nominations = self.manifest["private_author_nominations"]
        self.assertEqual(set(nominations), set(self.by_id))
        for ri, record in enumerate(self.packet["records"]):
            binding = nominations[record["example_id"]]
            self.assertEqual(binding["source_record_path"], f"/records/{ri}")
            self.assertEqual(binding["source_record_json_sha256"], canonical_digest(record))
            self.assertEqual(binding["source_input_json_sha256"], canonical_digest(record["input"]))
            self.assertEqual(binding["raw_utterance_sha256"], hashlib.sha256(record["input"]["utterance"]["text"].encode("utf-8")).hexdigest())
        for artifact in self.manifest["artifacts"]:
            path = (REPO / artifact["path"]).resolve()
            self.assertTrue(path.is_relative_to(ROOT.resolve()))
            data = path.read_bytes()
            self.assertEqual(len(data), artifact["bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), artifact["sha256"])

    def test_exact_bounds_evidence_and_correction_occurrences(self):
        non_ascii_spans = 0
        corrected = 0
        for entry in self.manifest["private_author_nominations"].values():
            for evidence in entry["source_evidence"]:
                assert_span(evidence, self.packet)
                self.assertEqual(evidence["char_start"], 0)
            for candidate in entry["private_candidate_nominations"]:
                assert_span(candidate["source_span"], self.packet)
                sp = candidate["source_span"]
                non_ascii_spans += sp["char_end"] != sp["utf8_byte_end"]
                self.assertFalse(candidate["is_detector_candidate"])
                self.assertFalse(candidate["is_review_annotation"])
                self.assertIsNone(candidate["completion_supervision"])
                self.assertIsNone(candidate["normalized_value"])
                self.assertEqual(candidate["normalization_status"], "not_assessed")
                self.assertEqual(candidate["reference_status"], "unassessed")
            candidates = entry["private_candidate_nominations"]
            if any(c["candidate_role_nomination"] == "superseded" for c in candidates):
                previous = next(c for c in candidates if c["candidate_role_nomination"] == "superseded")
                current = next(c for c in candidates if c["candidate_role_nomination"] == "current")
                self.assertGreaterEqual(current["source_span"]["char_start"], previous["source_span"]["char_end"])
                corrected += 1
        self.assertGreater(non_ascii_spans, 0)
        self.assertEqual(corrected, 2)

    def test_lineage_retains_every_member_and_no_split_claim(self):
        lineage = self.manifest["source_neutral_lineage"]
        roots = lineage["roots"]
        members = [eid for root in roots for eid in root["members"]]
        self.assertEqual(len(roots), 24)
        self.assertEqual(Counter(members), Counter(self.by_id.keys()))
        self.assertTrue(all(len(root["members"]) == 3 for root in roots))
        edges = {(e["a"], e["b"]) for e in lineage["alias_edges"]}
        for root in roots:
            for eid in root["members"]:
                self.assertIn((eid, root["root_id"]), edges)
                self.assertEqual(self.manifest["private_author_nominations"][eid]["declared_lineage_id"], root["root_id"])
        self.assertFalse(lineage["root_count_is_support_count"])
        self.assertFalse(lineage["label_dependent_grouping"])
        self.assertEqual(lineage["audit"]["global_closure"], "unknown")
        self.assertIn("not asserted", lineage["audit"]["split_closure"])
        self.assertEqual(self.packet["split"], "train")
        self.assertEqual(self.manifest["actions"]["new_DEV_reads"], 0)
        self.assertEqual(self.manifest["actions"]["peer_reads"], 0)

    def test_privacy_and_fictional_current_state(self):
        sensitive = re.compile(r"\b(?:phone|telephone|mobile|DOB|PIN|password|passcode|security|account|passport|email|SSN|address)\b", re.I)
        identity = re.compile(r"(?:\+?\d[\d\s()-]{9,}\d|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})")
        for record in self.packet["records"]:
            inp = record["input"]
            assert_semantic_input(inp)
            # Dates are authored calendar expressions, not identity-like number runs.
            text = inp["utterance"]["text"] + " " + inp["question"]["text"]
            self.assertIsNone(sensitive.search(text))
            stripped_dates = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", "<date>", text)
            self.assertIsNone(identity.search(stripped_dates))
            self.assertTrue(all(t["product_id"].startswith("fictional-plan-") for t in inp["targets"]))
        self.assertEqual(self.manifest["modality"], "English synthetic text only")
        self.assertFalse(self.manifest["status"]["human_gold"])
        self.assertFalse(self.manifest["status"]["IID_gold"])

    def test_candidate_target_scope_and_explicit_masks(self):
        masked = 0
        mismatch = 0
        for eid, entry in self.manifest["private_author_nominations"].items():
            inp = self.by_id[eid]["input"]
            known = {t["index"] for t in inp["targets"]}
            for candidate in entry["private_candidate_nominations"]:
                self.assertTrue(candidate["target_indices"])
                self.assertTrue(set(candidate["target_indices"]).issubset(known))
                required = bool(candidate["mask_reasons"])
                self.assertEqual(candidate["training_mask_required"], required)
                if required:
                    self.assertEqual(candidate["eligibility"], "masked_by_construction")
                    masked += 1
                else:
                    self.assertIn("unknown", candidate["eligibility"])
                if set(candidate["target_indices"]) != set(inp["question"]["target_indices"]) and candidate["candidate_role_nomination"] == "current":
                    self.assertTrue(required)
                    mismatch += 1
        self.assertEqual(masked, 10)
        self.assertGreater(mismatch, 0)

    def test_no_training_or_qualification_by_counts(self):
        counts = self.manifest["counts"]
        self.assertEqual(counts["packet_rows"], len(self.by_id))
        self.assertEqual(len(self.by_id), 72)
        self.assertEqual(counts["primary_source_rows"], 36)
        self.assertEqual(counts["date_source_rows"], 36)
        self.assertEqual(counts["reviewed_rows"], 0)
        self.assertEqual(counts["adjudicated_rows"], 0)
        self.assertIsNone(counts["actual_eligible_primary_negative_groups"])
        self.assertIsNone(counts["actual_eligible_unfinished_date_groups"])
        self.assertFalse(self.manifest["status"]["fit_ready"])
        self.assertFalse(self.manifest["status"]["qualified"])
        self.assertTrue(all(v == 0 for v in self.manifest["actions"].values()))

    def test_rejects_label_leak_and_bad_state(self):
        packet = copy.deepcopy(self.packet)
        packet["records"][0]["primary_label"] = "negative"
        with self.assertRaises(ValueError):
            assert_label_free(packet)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.Draft202012Validator(self.schema).validate(packet)
        inp = copy.deepcopy(self.packet["records"][0]["input"])
        inp["question"]["target_indices"] = [99]
        with self.assertRaises(ValueError):
            assert_semantic_input(inp)
        inp = copy.deepcopy(self.packet["records"][0]["input"])
        inp["utterance"]["source_turn_id"] = "other"
        with self.assertRaises(ValueError):
            assert_semantic_input(inp)

    def test_rejects_corrupt_evidence_bounds_and_source_pointer(self):
        entry = next(iter(self.manifest["private_author_nominations"].values()))
        original = entry["source_evidence"][0]
        for key, value in (("char_start", -1), ("char_end", 99999), ("text", "wrong source"),
                           ("utf8_byte_start", 1), ("raw_field_path", "/records/99999/input/utterance/text")):
            broken = copy.deepcopy(original)
            broken[key] = value
            with self.assertRaises(ValueError, msg=key):
                assert_span(broken, self.packet)

    def test_review_allowlist_excludes_authoring_and_manifest(self):
        allowlist = {Path(p).name for p in self.manifest["reviewer_allowlist"]}
        self.assertEqual(allowlist, {"label-free-train-packet.json", "packet.schema.json"})
        self.assertIn("PARENT ONLY", self.manifest["audience"])
        self.assertNotIn("authoring.py", allowlist)
        self.assertNotIn("manifest.json", allowlist)

    def test_schema_and_source_goal_comparison_invariants(self):
        invariants = self.manifest["cross_author_comparison_invariants"]
        input_schema = self.schema["properties"]["records"]["items"]["properties"]["input"]
        self.assertEqual(canonical_digest(input_schema), invariants["input_schema_canonical_sha256"])
        self.assertEqual(canonical_digest(invariants["declared_source_goal"]), invariants["declared_source_goal_canonical_sha256"])
        self.assertTrue(invariants["parent_union_required_before_support_count"])
        self.assertIn("unknown", invariants["peer_schema_or_source_goal_hash_equal"])
        audit = self.manifest["source_neutral_lineage"]["audit"]
        self.assertEqual(audit["old_normalized_utterance_hashes_available"], audit["compatible_old_fingerprint_counts"]["normalized_utterance_sha256"])
        self.assertEqual(audit["old_carrier_phrase_hashes_available"], audit["compatible_old_fingerprint_counts"]["carrier_phrase_sha256"])
        self.assertGreater(audit["declared_old_input_hashes_compared"], 0)


if __name__ == "__main__":
    unittest.main()
