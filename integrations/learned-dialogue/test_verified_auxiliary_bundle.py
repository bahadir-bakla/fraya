"""Tampered model files and authority claims must fail before inference."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from verified_auxiliary_bundle import BundleRejected, load_auxiliary

ROOT = Path(__file__).resolve().parent


class VerifiedBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.good = json.loads((ROOT / "day2_public_model_v2.gnn.json").read_text())
        cls.labels = cls.good["publisher_labels"]

    def check_bytes(self, data, digest=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_bytes(data)
            return load_auxiliary(path, expected_sha256=digest or hashlib.sha256(data).hexdigest(),
                                  expected_labels=self.labels, kind="public_intent_v2")

    def rejected_change(self, change):
        model = copy.deepcopy(self.good)
        change(model)
        with self.assertRaises(BundleRejected):
            self.check_bytes(json.dumps(model).encode())

    def test_frozen_exports(self):
        for name in ("gnn", "no_edges", "sparse"):
            data = (ROOT / ("day2_public_model_v2." + name + ".json")).read_bytes()
            model = self.check_bytes(data)
            self.assertIs(model["qualified"], False)

    def test_digest_mismatch(self):
        with self.assertRaises(BundleRejected):
            self.check_bytes(json.dumps(self.good).encode(), "0" * 64)

    def test_duplicate_fields(self):
        with self.assertRaises(BundleRejected):
            self.check_bytes(b'{"qualified":false,"qualified":true}')

    def test_oversize(self):
        with self.assertRaises(BundleRejected):
            self.check_bytes(b" " * 500_001)

    def test_bank_authority(self):
        for field, value in (("qualified", True), ("qualified", "false"),
                             ("bank_mapping", {"intent": "promise"})):
            self.rejected_change(lambda m, f=field, v=value: m.__setitem__(f, v))

    def test_taxonomy_reordering(self):
        self.rejected_change(lambda m: m["publisher_labels"].reverse())

    def test_nonfinite_and_zero_temperature(self):
        for value in (0, -1, float("nan"), float("inf"), True):
            self.rejected_change(lambda m, v=value: m["calibration"].__setitem__("temperature", v))

    def test_threshold_bounds(self):
        for value in (-0.1, 2, "0.8", False):
            self.rejected_change(lambda m, v=value: m["calibration"].__setitem__("threshold", v))

    def test_parameter_dimensions(self):
        self.rejected_change(lambda m: m["parameters"]["embedding"].pop())

    def test_bool_coefficient(self):
        self.rejected_change(lambda m: m["parameters"]["embedding"][0].__setitem__(0, True))

    def test_unknown_architecture(self):
        self.rejected_change(lambda m: m.__setitem__("architecture", "remote_plugin"))

    def test_quantized_bounds(self):
        model = json.loads((ROOT / "day2_public_model_v2.sparse.json").read_text())
        model["parameters"]["weights_q"][0][0] = 32768
        with self.assertRaises(BundleRejected):
            self.check_bytes(json.dumps(model).encode())

    def test_frozen_teacher_head(self):
        path = ROOT / "day2_pretrained_head.json"
        freeze = json.loads((ROOT / "day2_pretrained_freeze.json").read_text())
        model = load_auxiliary(path, expected_sha256=freeze["head_sha256"],
                               expected_labels=self.labels, kind="minilm_offline_head")
        self.assertEqual(model["usage"], "offline_teacher_reference_only")

    def test_teacher_authority_and_remote_code(self):
        good = json.loads((ROOT / "day2_pretrained_head.json").read_text())
        changes = [lambda m: m.__setitem__("bank_policy_target", "authorize_payment"),
                   lambda m: m.__setitem__("usage", "bank_tool"),
                   lambda m: m["encoder"].__setitem__("trust_remote_code", True),
                   lambda m: m["weight_scales"].__setitem__(0, 0),
                   lambda m: m["weights_qint16"][0].__setitem__(0, True)]
        for change in changes:
            model = copy.deepcopy(good)
            change(model)
            data = json.dumps(model).encode()
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "head.json"
                path.write_bytes(data)
                with self.assertRaises(BundleRejected):
                    load_auxiliary(path, expected_sha256=hashlib.sha256(data).hexdigest(),
                                   expected_labels=self.labels, kind="minilm_offline_head")


if __name__ == "__main__":
    unittest.main()
