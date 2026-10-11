"""Own-pack hash binding and unchanged actor/scorer behavior; no network or writes."""
import copy
import hashlib
import ast
import datetime
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import benchmark_runner
import bound_stress_catalog as bound
import speech_stress_adapter as base


class BoundCatalogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "own.json"
        self.rows = json.loads(base.OUT.read_text(encoding="utf-8"))
        self.rows[0]["title"] = "Own catalog binding counterexample"
        self.path.write_text(json.dumps(self.rows), encoding="utf-8")
        self.pin = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_custom_pack_never_falls_back_to_default_pack(self):
        adapter = bound.BoundStressCatalog(self.path, expected_sha256=self.pin)
        manifest = adapter.verify_pack()
        self.assertEqual(manifest["catalog_sha256"], benchmark_runner.digest(self.rows))
        self.assertNotEqual(manifest["catalog_sha256"], base.verify_pack()["catalog_sha256"])
        self.assertEqual(adapter.rows()[0]["title"], self.rows[0]["title"])

    def test_wrong_initial_hash_fails_before_client_or_artifact_creation(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
            with self.assertRaisesRegex(ValueError, "file hash mismatch"):
                bound.BoundStressCatalog(self.path, expected_sha256="0" * 64)

    def test_pack_mutation_is_rejected_after_binding(self):
        adapter = bound.BoundStressCatalog(self.path, expected_sha256=self.pin)
        self.path.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "file hash mismatch"):
            adapter.verify_pack()

    def test_bound_source_mutation_is_rejected(self):
        adapter = bound.BoundStressCatalog(self.path, expected_sha256=self.pin)
        original = bound.raw_sha
        def changed(path):
            return "0" * 64 if Path(path) == adapter.source_path else original(path)
        with patch.object(bound, "raw_sha", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "adapter source changed"):
                adapter.verify_pack()

    def test_binding_preserves_actor_and_score_functions(self):
        adapter = bound.BoundStressCatalog(self.path, expected_sha256=self.pin)
        self.assertIs(adapter.persona_for, base.persona_for)
        self.assertIs(adapter.score, base.score)
        self.assertIs(adapter.validate_hosted, base.validate_hosted)
        self.assertEqual(adapter.persona_for(copy.deepcopy(self.rows[0])),
                         base.persona_for(copy.deepcopy(self.rows[0])))


class ManifestBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "research/customer-benchmark/own.json"
        self.path.parent.mkdir(parents=True)
        self.rows = json.loads(base.OUT.read_text(encoding="utf-8"))
        self.path.write_text(json.dumps(self.rows, ensure_ascii=False), encoding="utf-8")
        self.pin = bound.raw_sha(self.path)
        self.manifest_path = self.path.with_suffix(".manifest.json")
        entries = []
        for name in sorted(bound.REQUIRED_SOURCES):
            source = self.root / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(("UTF-8 source ş " + name + "\r\n").encode("utf-8"))
            entries.append({"path": name, "sha256": bound.source_sha(source),
                            "hash_method": bound.SOURCE_HASH_METHOD})
        self.manifest = {
            "pack": self.path.name, "raw_pack_sha256": self.pin,
            "normalized_pack_sha256": benchmark_runner.digest(self.rows),
            "normalized_pack_hash_method": bound.PACK_HASH_METHOD,
            "source_hashes": entries,
            "catalog_binding": {
                "pack_path": self.path.relative_to(self.root).as_posix(),
                "manifest_path": self.manifest_path.relative_to(self.root).as_posix(),
                "canonical_pack_sha256": benchmark_runner.digest(self.rows),
            },
        }
        self.save_manifest()
        self.addCleanup(patch.stopall)
        patch.object(bound, "ROOT", self.root).start()

    def save_manifest(self):
        self.manifest_path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.manifest_pin = bound.raw_sha(self.manifest_path)

    def bind(self, **overrides):
        arguments = dict(expected_sha256=self.pin, manifest=self.manifest_path,
                         manifest_sha256=self.manifest_pin)
        arguments.update(overrides)
        return bound.BoundStressCatalog(self.path, **arguments)

    def test_valid_manifest_is_read_only_and_preserves_function_identities(self):
        before = self.manifest_path.read_bytes()
        adapter = self.bind()
        verified = adapter.verify_pack()
        self.assertEqual(verified["bound_manifest_file_sha256"], self.manifest_pin)
        self.assertEqual(verified["bound_canonical_pack_sha256"], benchmark_runner.digest(self.rows))
        verified["bound_manifest_file_sha256"] = "0" * 64
        self.assertEqual(adapter.verify_pack()["bound_manifest_file_sha256"], self.manifest_pin)
        self.assertEqual(adapter.rows(), self.rows)
        self.assertEqual(self.manifest_path.read_bytes(), before)
        for name in ("persona_for", "score", "validate_hosted"):
            self.assertIs(getattr(adapter, name), getattr(base, name))

    def test_manifest_arguments_must_be_paired(self):
        for overrides in ({"manifest": None}, {"manifest_sha256": None}):
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, "supplied together"):
                self.bind(**overrides)

    def test_wrong_raw_manifest_pin_fails_before_catalog_validation(self):
        with patch.object(base, "verify_pack") as validation:
            with self.assertRaisesRegex(ValueError, "manifest file hash mismatch"):
                self.bind(manifest_sha256="0" * 64)
            validation.assert_not_called()

    def test_same_json_different_raw_manifest_bytes_are_rejected(self):
        adapter = self.bind()
        self.manifest_path.write_bytes(self.manifest_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "manifest file hash mismatch"):
            adapter.verify_pack()

    def test_wrong_sibling_pack_and_pack_path_traversal_are_rejected(self):
        for name in ("sibling.json", "../own.json", "nested/own.json", "nested\\own.json"):
            with self.subTest(name=name):
                self.manifest["pack"] = name
                self.save_manifest()
                with self.assertRaisesRegex(ValueError, "pack basename mismatch"):
                    self.bind()

    def test_manifest_in_other_directory_is_rejected(self):
        other = self.root / "other.manifest.json"
        other.write_bytes(self.manifest_path.read_bytes())
        with self.assertRaisesRegex(ValueError, "separate sibling"):
            self.bind(manifest=other, manifest_sha256=bound.raw_sha(other))

    def test_wrong_canonical_pack_hash_is_rejected_with_correct_raw_pins(self):
        self.manifest["normalized_pack_sha256"] = "0" * 64
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "canonical pack hash mismatch"):
            self.bind()

    def test_wrong_catalog_binding_is_rejected(self):
        self.manifest["catalog_binding"]["pack_path"] = "research/customer-benchmark/sibling.json"
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "catalog binding mismatch"):
            self.bind()

    def test_adapter_returning_wrong_catalog_is_rejected(self):
        verified = base.verify_pack(self.path)
        wrong = copy.deepcopy(self.rows)
        wrong[0]["title"] = "Wrong catalog returned by adapter"
        with patch.object(base, "verify_pack", return_value=verified), patch.object(
            base, "catalog", return_value=SimpleNamespace(to_rows=lambda: wrong)
        ):
            with self.assertRaisesRegex(ValueError, "semantic digest mismatch"):
                self.bind()

    def test_matching_native_manifest_and_wrong_catalog_cannot_hide_wrong_pack(self):
        wrong = copy.deepcopy(self.rows)
        wrong[0]["title"] = "Matching adapter digest for the wrong pack"
        verified = base.verify_pack(self.path)
        verified["catalog_sha256"] = benchmark_runner.digest(wrong)
        with patch.object(base, "verify_pack", return_value=verified), patch.object(
            base, "catalog", return_value=SimpleNamespace(to_rows=lambda: wrong)
        ):
            with self.assertRaisesRegex(ValueError, "semantic digest mismatch"):
                self.bind()

    def test_manifest_source_change_blocks_initial_binding(self):
        source = self.root / self.manifest["source_hashes"][0]["path"]
        source.write_bytes(source.read_bytes() + b"changed\n")
        with patch.object(base, "verify_pack") as validation:
            with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                self.bind()
            validation.assert_not_called()

    def test_manifest_pack_mutation_with_fresh_raw_pin_still_fails_canonical_binding(self):
        self.rows[0]["title"] = "Changed pack with freshly calculated raw pin"
        self.path.write_text(json.dumps(self.rows), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "canonical pack hash mismatch"):
            self.bind(expected_sha256=bound.raw_sha(self.path))

    def test_additional_source_entries_are_also_verified(self):
        extra = self.root / "additional-source.txt"
        extra.write_text("Additional manifest input\n", encoding="utf-8")
        self.manifest["source_hashes"].append({"path": extra.name,
            "sha256": bound.source_sha(extra), "hash_method": bound.SOURCE_HASH_METHOD})
        self.save_manifest()
        adapter = self.bind()
        extra.write_text("Changed additional manifest input\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source hash mismatch"):
            adapter.verify_pack()

    def test_pack_mutation_is_rejected_by_rows_and_verify(self):
        adapter = self.bind()
        self.path.write_bytes(self.path.read_bytes() + b"\n")
        for check in (adapter.rows, adapter.verify_pack):
            with self.subTest(check=check.__name__), self.assertRaisesRegex(ValueError, "file hash mismatch"):
                check()

    def test_every_actual_source_change_is_rejected_after_binding(self):
        adapter = self.bind()
        for entry in self.manifest["source_hashes"]:
            source = self.root / entry["path"]
            before = source.read_bytes()
            with self.subTest(source=entry["path"]):
                source.write_bytes(before + b"changed\n")
                with self.assertRaisesRegex(ValueError, "source hash mismatch"):
                    adapter.verify_pack()
            source.write_bytes(before)
        adapter.verify_pack()

    def test_source_line_endings_follow_declared_normalization(self):
        adapter = self.bind()
        for entry in self.manifest["source_hashes"]:
            source = self.root / entry["path"]
            source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        adapter.verify_pack()

    def test_missing_duplicate_or_unsupported_sources_are_rejected(self):
        original = copy.deepcopy(self.manifest)
        for kind in ("missing", "duplicate", "method", "hash", "traversal", "absolute", "windows"):
            with self.subTest(kind=kind):
                self.manifest = copy.deepcopy(original)
                entries = self.manifest["source_hashes"]
                if kind == "missing":
                    entries.pop()
                elif kind == "duplicate":
                    entries.append(copy.deepcopy(entries[0]))
                elif kind == "method":
                    entries[0]["hash_method"] = "raw"
                elif kind == "hash":
                    entries[0]["sha256"] = "0" * 64
                else:
                    entries[0]["path"] = {"traversal": "../outside.txt", "absolute": "/outside.txt",
                                           "windows": "C:\\outside.txt"}[kind]
                self.save_manifest()
                with self.assertRaises(ValueError):
                    self.bind()

    def test_pack_hash_method_is_explicit(self):
        self.manifest["normalized_pack_hash_method"] = "raw"
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "pack hash method"):
            self.bind()

    def load_launcher(self):
        path = Path(__file__).resolve().parents[2] / "local-runs/autonomous-rd/night-stage2-launch.py"
        spec = importlib.util.spec_from_file_location("offline_stage2_launcher", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.root = self.root
        return module

    def launch_args(self):
        return ["--slot", "unused", "--version", "1", "--brief", "A", "--pack", str(self.path),
                "--sha256", self.pin, "--manifest", str(self.manifest_path),
                "--manifest-sha256", self.manifest_pin, "--budget-seconds", "60"]

    def test_launcher_requires_manifest_flags_before_side_effects(self):
        launch = self.load_launcher()
        args = self.launch_args()
        for name in ("--manifest", "--manifest-sha256"):
            without = args.copy()
            index = without.index(name)
            del without[index:index + 2]
            with self.subTest(flag=name), patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
                launch.main(without)

    def test_launcher_wrong_manifest_fails_before_state_credentials_client_or_creation(self):
        launch = self.load_launcher()
        self.manifest["pack"] = "sibling.json"
        self.save_manifest()
        with patch.object(launch, "check_budget"), patch.object(benchmark_runner, "main") as runner, patch.object(
            benchmark_runner, "OfficialClient"
        ) as client, patch.dict("sys.modules", {
            "freya_dpapi_server": SimpleNamespace(inject_credentials=Mock())
        }):
            with self.assertRaisesRegex(ValueError, "pack basename mismatch"):
                launch.main(self.launch_args())
            runner.assert_not_called()
            client.assert_not_called()
            import sys
            sys.modules["freya_dpapi_server"].inject_credentials.assert_not_called()
        self.assertFalse((self.root / "local-runs").exists())

    def test_launcher_rejects_directory_escape_before_binding(self):
        launch = self.load_launcher()
        args = self.launch_args()
        args[args.index("--pack") + 1] = str(self.root / "research/outside.json")
        with patch.object(launch, "check_budget"), patch.object(bound, "BoundStressCatalog") as constructor:
            with self.assertRaisesRegex(ValueError, "escapes catalog directory"):
                launch.main(args)
            constructor.assert_not_called()

    def test_launcher_rejects_lexical_traversal_even_when_inside_catalog_directory(self):
        launch = self.load_launcher()
        args = self.launch_args()
        args[args.index("--pack") + 1] = str(self.path.parent / "nested/../own.json")
        with patch.object(launch, "check_budget"), patch.object(bound, "BoundStressCatalog") as constructor:
            with self.assertRaisesRegex(ValueError, "path traversal"):
                launch.main(args)
            constructor.assert_not_called()

    def test_absolute_cutoff_and_budget_margin_are_preserved(self):
        launch = self.load_launcher()
        self.assertEqual(launch.CUTOFF.isoformat(), "2026-10-11T06:23:01+00:00")
        with patch.object(launch.datetime, "datetime") as current:
            current.now.return_value = launch.CUTOFF - datetime.timedelta(seconds=91)
            launch.check_budget(60)
            current.now.return_value = launch.CUTOFF - datetime.timedelta(seconds=90)
            with self.assertRaisesRegex(ValueError, "absolute 06:23:01Z"):
                launch.check_budget(60)
            for seconds in (59, 1801):
                with self.assertRaises(ValueError):
                    launch.check_budget(seconds)

    def test_existing_runner_verifies_before_client_and_every_mutating_request(self):
        # Inspect the pinned runner hook without clients, requests, or output creation.
        tree = ast.parse(Path(benchmark_runner.__file__).read_text(encoding="utf-8"))
        execute = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "execute")
        request = next(node for node in execute.body if isinstance(node, ast.FunctionDef) and node.name == "request")
        guard = next(node for node in request.body if isinstance(node, ast.If))
        self.assertEqual(ast.unparse(guard.test), "method != 'GET'")
        self.assertEqual(ast.unparse(guard.body[0]), "verify()")
        verify = next(node for node in execute.body if isinstance(node, ast.FunctionDef) and node.name == "verify")
        self.assertIn("adapter.verify_pack()", ast.unparse(verify))
        text = ast.unparse(execute)
        self.assertLess(text.index("verified_manifest = verify()"), text.index("client = client or OfficialClient"))


class FrozenV2BindingTests(unittest.TestCase):
    def test_actual_v2_read_only_binding_and_plan(self):
        root = Path(__file__).resolve().parents[2]
        pack = root / "research/customer-benchmark/night-stage2-short-turn-cases.v2.json"
        manifest = pack.with_suffix(".manifest.json")
        before = {path: path.read_bytes() for path in (pack, manifest)}
        adapter = bound.BoundStressCatalog(pack,
            expected_sha256="57566a4368428fb9d4b85b2a40ea442f40a2861713df8271875fd7b777d6045f",
            manifest=manifest,
            manifest_sha256="1e0ad7f2bb6aa561477cc06a9a419f7a739f1726da4cac66718cbb61d2f3eff4")
        rows = adapter.rows()
        self.assertEqual(len(rows), 12)
        for brief in ("A", "B"):
            ids = [row["variant_id"] for row in rows if row["brief"] == brief]
            self.assertEqual(len(ids), 6)
            plan = benchmark_runner.plan(rows, adapter, brief=brief, only=",".join(ids),
                                         reps=3, batch_size=5, parallel_reps=True)
            self.assertEqual(plan["sessions_required"], 18)
            self.assertEqual(plan["batches_required"], 4)
            self.assertEqual(plan["max_personas_per_batch"], 5)
            self.assertEqual(plan["network_calls"], 0)
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
