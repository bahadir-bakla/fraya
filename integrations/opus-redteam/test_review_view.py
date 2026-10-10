"""Offline lossless representation and review-contract tests; no external calls."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run


def raw_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


class ReviewViewTests(unittest.TestCase):
    def assert_roundtrip(self, original, raw=None):
        raw = raw_json(original) if raw is None else raw
        view = run.make_review_view(raw)
        # The model receives serialized JSON, not Python object identities.
        view = json.loads(json.dumps(view))
        reconstructed = run.reconstruct_review_view(view)
        self.assertEqual(run._json_text(reconstructed), run._json_text(original))
        run.verify_review_view(view, raw)
        self.assertEqual(view["source_sha256"], hashlib.sha256(raw).hexdigest())
        return view

    def test_identical_long_strings_are_stored_once(self):
        code = "def action():\n    return 'exact'\n" * 200
        view = self.assert_roundtrip({"one": code, "two": code, "three": code})
        references = [entry["chunks"] for entry in view["strings"]]
        self.assertEqual(references[0], references[1])
        self.assertEqual(references[1], references[2])
        self.assertLess(len(json.dumps(view)), len(json.dumps({"one": code, "two": code, "three": code})))

    def test_shared_prefix_with_unequal_suffixes(self):
        prefix = "shared exact code line\n" * 300
        view = self.assert_roundtrip({"a": prefix + "return 1\n", "b": prefix + "return 22\n"})
        self.assertTrue(any(chunk.startswith(prefix) for chunk in view["chunks"].values()))
        self.assertEqual({entry["pointer"] for entry in view["strings"]}, {"/a", "/b"})

    def test_shared_suffix_with_unequal_prefixes(self):
        suffix = "def same_behavior():\n    pass\n" * 300
        view = self.assert_roundtrip(["init\n" + suffix, "continue\n" + suffix, suffix])
        self.assertIn(suffix, view["chunks"].values())

    def test_shared_prefix_and_suffix_preserve_different_middle(self):
        prefix, suffix = "prefix\n" * 400, "suffix\n" * 400
        self.assert_roundtrip([prefix + "FIRST" + suffix, prefix + "SECOND-longer" + suffix])

    def test_escaped_strings_types_and_literal_reference_shapes(self):
        code = '\\n\n\r\t"quoted"\\path\u2603' * 300
        value = {"text": code, "same": code, "null": None, "bool": True,
                 "false": False, "integer": 1, "float": 1.0, "negative_zero": -0.0,
                 "number_string": "1", "null_string": "null", "empty": "",
                 "literal_reference": {"pointer": "/text", "chunks": ["C0"]},
                 "literal_placeholder": {"$ref": "C0"}}
        view = self.assert_roundtrip(value)
        result = run.reconstruct_review_view(view)
        for key in value:
            self.assertIs(type(result[key]), type(value[key]))

    def test_shape_envelope_empty_containers_and_original_pointers(self):
        text = "exact" * 200
        value = {"workflow_id": "export-id", "metadata": {"extra": text},
                 "workflow": {"initial_node": "a/b~c", "nodes": {
                     "a/b~c": {"code": text, "items": [None, {}, [], text]}}},
                 "": {"0": text}, "arr": [{"~1/": text}]}
        view = self.assert_roundtrip(value)
        pointers = {entry["pointer"] for entry in view["strings"]}
        self.assertEqual(pointers, {"/metadata/extra", "/workflow/nodes/a~1b~0c/code",
                                   "/workflow/nodes/a~1b~0c/items/3", "//0", "/arr/0/~01~1"})
        self.assertEqual(view["tree"]["workflow_id"], "export-id")
        self.assertEqual(view["tree"]["workflow"]["nodes"]["a/b~c"]["items"], [None, {}, [], None])

    def test_root_string_and_other_root_shapes(self):
        for value in ("long-root" * 100, [], {}, None, True, 42, 0.5, ["x" * 500]):
            with self.subTest(type=type(value).__name__):
                view = self.assert_roundtrip(value)
                if isinstance(value, str):
                    self.assertEqual(view["strings"][0]["pointer"], "")

    def test_bom_lexical_escapes_and_source_hash_are_authoritative(self):
        raw = b'\xef\xbb\xbf{ "a": "\\u0061", "n": 1e0, "list": [] }\r\n'
        view = self.assert_roundtrip(json.loads(raw.decode("utf-8-sig")), raw)
        with self.assertRaisesRegex(ValueError, "source hash"):
            run.verify_review_view(view, raw_json(run.reconstruct_review_view(view)))

    def test_modified_chunk_is_rejected(self):
        view = self.assert_roundtrip({"code": "abcdef" * 200})
        view["chunks"][next(iter(view["chunks"]))] += "changed behavior"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            run.reconstruct_review_view(view)

    def test_modified_type_is_rejected_even_when_python_equal(self):
        view = self.assert_roundtrip({"number": 1})
        view["tree"]["number"] = True
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            run.reconstruct_review_view(view)

    def test_duplicate_missing_and_nonplaceholder_pointers_rejected(self):
        view = self.assert_roundtrip({"code": "x" * 1000})
        duplicate = deepcopy(view)
        duplicate["strings"].append(deepcopy(duplicate["strings"][0]))
        missing = deepcopy(view)
        missing["strings"][0]["pointer"] = "/missing"
        nonplaceholder = deepcopy(view)
        nonplaceholder["tree"]["code"] = "not null"
        for corrupted in (duplicate, missing, nonplaceholder):
            with self.assertRaises(ValueError):
                run.reconstruct_review_view(corrupted)

    def test_duplicate_object_members_and_non_json_numbers_fail_closed(self):
        for raw in (b'{"x": 1, "x": 2}', b'{"x": NaN}', b'{"x": Infinity}'):
            with self.assertRaises(ValueError):
                run.make_review_view(raw)

    def test_numbers_that_would_round_or_underflow_fail_closed(self):
        for raw in (b'{"x": 0.123456789012345678901}', b'{"x": 1e-999}', b'{"x": 1e999}'):
            with self.assertRaisesRegex(ValueError, "precision loss"):
                run.make_review_view(raw)

    def test_prepare_uses_view_keeps_original_and_writes_only_designated_outputs(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            here = root / "integrations/opus-redteam"
            runtime = here / "runtime"
            here.mkdir(parents=True)
            (here / "review-instructions.txt").write_text("Synthetic instructions", encoding="utf-8")
            sources = {"brief-a": "a.md", "brief-b": "b.md", "openapi": "api.json"}
            for relative in ("a.md", "b.md"):
                (root / relative).write_text("line one\nline two\n", encoding="utf-8")
            (root / "api.json").write_text('{"paths": {"/get_account": {"post": {}}}}', encoding="utf-8")
            body = "def exact_body():\n    pass\n" * 1000
            candidate = root / "competition/runs/complete/workflow.json"
            candidate.parent.mkdir(parents=True)
            original = {"export_metadata": {"code": body}, "workflow": {
                "initial_node": "start", "nodes": {"start": {"code": body}, "next": {"code": body}}}}
            raw = raw_json(original)
            candidate.write_bytes(raw)
            contract = types.ModuleType("agent_forge.input_contract")
            contract.inspect_inputs = lambda *args: {"documents": []}
            policy = types.ModuleType("agent_forge.builder_policy")
            policy.POLICY_SCHEMA = {}
            api = types.ModuleType("agent_forge.tool_api")
            api.validate_json = lambda *args: []
            with patch.object(run, "ROOT", root), patch.object(run, "HERE", here), \
                 patch.object(run, "RUNTIME", runtime), patch.object(run, "SOURCES", sources), \
                 patch.object(run, "latest_published_candidate", return_value=candidate), \
                 patch.dict(sys.modules, {"agent_forge.input_contract": contract,
                                          "agent_forge.builder_policy": policy, "agent_forge.tool_api": api}):
                snapshot = run.prepare(manifest_path=runtime / "manifest.json")
            item = snapshot["candidates"][0]
            prompt = (runtime / "prompt.txt").read_text(encoding="utf-8")
            self.assertIn(run.REVIEW_VIEW_FORMAT, prompt)
            self.assertIn("LOSSLESS READ-ONLY", prompt)
            self.assertIn("L2 line two", prompt)
            self.assertEqual(candidate.read_bytes(), raw)
            self.assertEqual(Path(item["raw_snapshot"]).read_bytes(), raw)
            self.assertEqual(item["sha256"], hashlib.sha256(raw).hexdigest())
            run.verify_review_view(item["review_view"], raw)
            self.assertFalse((here / "source-manifest.json").exists())
            manifest = json.loads((runtime / "manifest.json").read_text())
            self.assertTrue(manifest["candidates"][0]["review_view"]["reconstruction_verified"])
            self.assertLess(manifest["prompt_bytes"], manifest["raw_prompt_bytes"])
            self.assertIn(item["text"], (runtime / "prompt-raw.txt").read_text())


class FixTargetTests(unittest.TestCase):
    def fixture(self, file):
        snapshot = {"candidates": [], "sources": {key: {"line_count": 2} for key in run.SOURCES},
                    "qualified_source_ids": ["brief-a:1"], "tool_names": ["close_call"]}
        attack = {"title": "Synthetic", "priority": "P1", "assessment": "source_derived_attack",
                  "scenario": {"brief": "A", "call_variables": {}, "identity_fixture": {}, "products": [],
                               "customer_turns": ["synthetic turn"], "fault_plan": []},
                  "expected_ledger": {key: [] for key in ("outcome", "reason", "promises", "notes",
                                                         "callbacks", "transfers", "oracle_scope")},
                  "expected_speech": ["synthetic constraint"],
                  "forbidden_bank_calls": [{"tool": "close_call", "when": "before goodbye", "reason": "order"}],
                  "qualified_source_ids": ["brief-a:1"], "failure_path": "synthetic source path",
                  "fix_target": {"file": file, "function_or_node": "synthetic", "suggested_change": "harden"}}
        attacks = []
        for number in range(1, 16):
            item = deepcopy(attack)
            item["id"] = f"O55-{number:02d}"
            attacks.append(item)
        return {"review_type": "source_review_not_executed", "candidate_reviewed": False, "attacks": attacks}, snapshot

    def test_supplied_guidance_host_and_existing_implementation_targets_allowed(self):
        for key in ("competition-guidance", "competition-host", "builder-prompts", "policy-runtime"):
            with self.subTest(source=key):
                run.validate_review(*self.fixture(run.SOURCES[key]))

    def test_outside_targets_rejected(self):
        for file in ("outside.py", "competition/../outside.py", run.SOURCES["brief-a"]):
            with self.assertRaisesRegex(ValueError, "outside supplied"):
                run.validate_review(*self.fixture(file))

    def test_unsupplied_guidance_is_rejected(self):
        review, snapshot = self.fixture(run.SOURCES["competition-guidance"])
        del snapshot["sources"]["competition-guidance"]
        with self.assertRaisesRegex(ValueError, "outside supplied"):
            run.validate_review(review, snapshot)


if __name__ == "__main__":
    unittest.main()
