import ast
import hashlib
import socket
import subprocess
import unittest
from unittest.mock import patch

from inference import HEADS, local_snapshot, predict
from train_eval import HERE, load_data, load_model
from validation import validate_proposal


class ExportSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (HERE / "runtime_embedded.py").read_text(encoding="utf-8")
        cls.model = load_model()
        cls.records, _, _, _ = load_data()
        cls.namespace = {}
        exec(compile(cls.source, "runtime_embedded.py", "exec"), {"__builtins__": __builtins__}, cls.namespace)

    def test_only_supported_import_names(self):
        imports = [name.name for node in ast.walk(ast.parse(self.source)) if isinstance(node, ast.Import) for name in node.names]
        self.assertEqual(sorted(imports), ["json", "re"])
        self.assertFalse(any(isinstance(n, ast.ImportFrom) for n in ast.walk(ast.parse(self.source))))
        self.assertLess(len(self.source.encode()), 500000)
        self.assertNotIn("{{", self.source)
        self.assertNotIn("}}", self.source)

    def test_separate_namespace_parity_all_records(self):
        for record in self.records:
            snapshot = local_snapshot(record["utterance"], record["id"])
            snapshot["input_sha256"] = hashlib.sha256(snapshot["utterance"].encode()).hexdigest()
            offline, embedded = predict(snapshot, self.model), self.namespace["predict_embedded"](snapshot)
            self.assertTrue(validate_proposal(embedded, snapshot))
            self.assertEqual(offline["candidate"], embedded["candidate"])
            self.assertEqual(offline["abstain"], embedded["abstain"])
            self.assertEqual(offline["reasons"], embedded["reasons"])
            for head in HEADS:
                for label, score in offline["confidence"]["heads"][head]["distribution"].items():
                    self.assertAlmostEqual(score, embedded["confidence"]["heads"][head]["distribution"][label], places=12)

    def test_no_io_at_runtime(self):
        snapshot = local_snapshot("Please call me back later about this fictional account.")
        snapshot["input_sha256"] = hashlib.sha256(snapshot["utterance"].encode()).hexdigest()
        with patch("builtins.open", side_effect=AssertionError("filesystem")), patch.object(socket, "socket", side_effect=AssertionError("network")), patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            output = self.namespace["predict_embedded"](snapshot)
        self.assertTrue(validate_proposal(output, snapshot))

    def test_hash_is_required_and_checked_by_upstream_wrapper(self):
        snapshot = local_snapshot("Please call me back later about this fictional account.")
        with self.assertRaises(ValueError):
            self.namespace["predict_embedded"](snapshot)
        snapshot["input_sha256"] = "a" * 64
        output = self.namespace["predict_embedded"](snapshot)
        with self.assertRaises(ValueError):
            validate_proposal(output, snapshot)


if __name__ == "__main__":
    unittest.main(verbosity=2)
