"""Adapter-only unit tests. All temporary writes stay in owned scenarios/.

Run from the repository root without importing/running any Freya test suite:
    python -B -m unittest discover -s integrations/mirofish/tests -p test_scenario_adapter.py -v
"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import urllib.request


ADAPTER_PATH = Path(__file__).resolve().parents[1] / "scenario_adapter.py"
spec = importlib.util.spec_from_file_location("mirofish_scenario_adapter", ADAPTER_PATH)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class ScenarioAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.synthetic = json.loads((adapter.ROOT / adapter.SYNTHETIC_FILE).read_text(encoding="utf-8"))
        cls.official = json.loads((adapter.ROOT / adapter.OFFICIAL_FILE).read_text(encoding="utf-8"))
        cls.catalog = adapter.build_catalog()

    def setUp(self):
        adapter.SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="adapter-test-", dir=adapter.SCENARIOS_DIR)
        self.directory = Path(self.temporary.name).resolve()
        self.assertTrue(self.directory.is_relative_to(adapter.SCENARIOS_DIR.resolve()))

    def tearDown(self):
        # Verify the absolute recursive-cleanup target stays inside our write scope.
        self.assertTrue(self.directory.is_relative_to(adapter.SCENARIOS_DIR.resolve()))
        self.temporary.cleanup()

    def case(self, case_id, catalog=None):
        return adapter.select_cases(catalog or self.catalog, [case_id])[0]

    def resolve(self, setup, brief="A", baseline=None):
        return adapter.resolve_fixture(baseline or self.synthetic["local_fixture_baseline"], setup, brief, "SYN-001")

    def fixture_root(self):
        root = self.directory / "sources"
        for relative in adapter.SOURCE_FILES:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((adapter.ROOT / relative).read_bytes())
        return root

    def cli(self, *args):
        return subprocess.run([sys.executable, "-B", str(ADAPTER_PATH), *map(str, args)],
                              cwd=self.directory, capture_output=True, text=True, encoding="utf-8")

    def test_all_63_cases_and_unique_source_mappings(self):
        self.assertEqual(self.catalog["counts"], {"synthetic": 50, "official": 13, "total": 63})
        self.assertEqual(len(self.catalog["cases"]), 63)
        self.assertEqual(len({c["id"] for c in self.catalog["cases"]}), 63)
        by_kind = {kind: [c for c in self.catalog["cases"] if c["source"]["kind"] == kind]
                   for kind in ("synthetic", "official")}
        for kind, source, path in (("synthetic", self.synthetic["cases"], adapter.SYNTHETIC_FILE),
                                   ("official", self.official, adapter.OFFICIAL_FILE)):
            self.assertEqual({c["source"]["case_id"] for c in by_kind[kind]}, adapter.KNOWN_IDS[kind])
            for index, (record, original) in enumerate(zip(by_kind[kind], source)):
                self.assertEqual(record["source"]["path"], path)
                self.assertEqual(record["source"]["case_id"], original["id"])
                self.assertEqual(record["source"]["case_sha256"], adapter.digest(original))
                self.assertEqual(record["source"]["json_pointer"], ("/cases/" if kind == "synthetic" else "/") + str(index))
                self.assertEqual(record["status"], adapter.STATUS)

    def test_every_synthetic_case_reconstructs_losslessly(self):
        self.assertEqual(self.catalog["shared"]["synthetic"], {k: v for k, v in self.synthetic.items() if k != "cases"})
        for original in self.synthetic["cases"]:
            record = self.case(original["id"])
            scenario, expected = record["scenario"], record["expected_output"]
            intent = scenario["behavior_intentions"]
            trigger = deepcopy(scenario["fixture_plan"])
            trigger["customer_behavior"] = intent["customer_behavior"]
            if "harness_requirements" in intent:
                trigger["harness_requirements"] = intent["harness_requirements"]
            if "fault_injection" in scenario["tool_outcomes"]:
                trigger["fault_injection"] = scenario["tool_outcomes"]["fault_injection"]
            reconstructed = {
                "id": record["source"]["case_id"], "brief": scenario["brief"],
                "persona": {**intent["persona"], "delivery": record["speech_delivery"]["source_delivery"]},
                "category": intent["category"], "trigger": trigger,
                **{k: expected[k] for k in ("expected_backend_invariants", "expected_conversation_checks",
                                           "source_rules", "expectation_classification", "oracle_scope")},
            }
            if "open_questions" in expected:
                reconstructed["open_questions"] = expected["open_questions"]
            self.assertEqual(reconstructed, original, original["id"])

    def test_every_official_case_and_oracle_reconstructs_exactly(self):
        for original in self.official:
            record = self.case(original["id"])
            scenario = record["scenario"]
            reconstructed = {
                "id": record["source"]["case_id"], "brief": scenario["brief"],
                **{k: scenario["fixture_facts"][k] for k in ("variables", "identity", "products")},
                **scenario["behavior_intentions"],
                "expected": record["expected_output"]["ledger"],
                "checks": record["expected_output"]["conversation_checks"],
            }
            if "faults" in scenario["tool_outcomes"]:
                reconstructed["faults"] = scenario["tool_outcomes"]["faults"]
            self.assertEqual(reconstructed, original, original["id"])
            self.assertEqual(adapter.canonical_bytes(record["expected_output"]["ledger"]),
                             adapter.canonical_bytes(original["expected"]))

    def test_provenance_hashes_are_actual_file_bytes(self):
        files = self.catalog["provenance"]["files"]
        self.assertEqual(set(files), set(adapter.SOURCE_FILES))
        for relative, value in files.items():
            self.assertEqual(value, hashlib.sha256((adapter.ROOT / relative).read_bytes()).hexdigest())
        for record in self.catalog["cases"]:
            self.assertEqual(record["source"]["file_sha256"], files[record["source"]["path"]])

    def test_deterministic_bytes_portable_root_and_tracked_catalog(self):
        first = adapter.canonical_bytes(self.catalog) + b"\n"
        self.assertEqual(first, adapter.canonical_bytes(adapter.build_catalog()) + b"\n")
        self.assertEqual(first, adapter.canonical_bytes(adapter.build_catalog(self.fixture_root())) + b"\n")
        self.assertEqual(first, (adapter.SCENARIOS_DIR / "catalog.json").read_bytes())
        self.assertNotIn("generated_at", self.catalog)

    def test_nested_scalars_merge_without_changing_baseline(self):
        baseline = deepcopy(self.synthetic["local_fixture_baseline"])
        before = deepcopy(baseline)
        resolved = self.resolve({"identity": {"phone_last4": "0007"}, "product_A": {"past_due": 512.34},
                                 "now": "2026-12-18T11:00"}, baseline=baseline)
        self.assertEqual(resolved["identity"], {"date_of_birth": "1988-03-14", "phone_last4": "0007"})
        self.assertEqual(resolved["products"][0]["past_due"], 512.34)
        self.assertEqual(resolved["products"][0]["minimum_payment"], 126)
        self.assertEqual(resolved["variables"]["now"], "2026-12-18T11:00")
        self.assertEqual(baseline, before)

    def test_product_type_replacement_removes_obsolete_fields(self):
        facts = self.case("SYN-036")["scenario"]["fixture_facts"]
        self.assertEqual(facts["products"], [{"product_id": "loan-alpha", "type": "personal_loan",
                                            "past_due": 900.75, "days_late": 10, "instalment_amount": 300.25}])
        baseline = deepcopy(self.synthetic["local_fixture_baseline"])
        baseline["product_A"] = deepcopy(facts["products"][0])
        card = self.resolve({"product_A": {"type": "credit_card", "card_last4": "0003", "minimum_payment": 101.01}}, baseline=baseline)
        self.assertNotIn("instalment_amount", card["products"][0])
        self.assertEqual(card["products"][0]["past_due"], 900.75)
        car = self.resolve({"product_A": {"type": "car_loan"}}, baseline=baseline)
        self.assertEqual(car["products"][0]["instalment_amount"], 300.25)
        with self.assertRaisesRegex(adapter.AdapterError, "product-specific"):
            self.resolve({"product_A": {"type": "personal_loan"}})

    def test_b_products_replace_entire_list_and_keep_order(self):
        original = next(c for c in self.synthetic["cases"] if c["id"] == "SYN-044")
        expected = original["trigger"]["setup"]["products_B_in_returned_order"]
        self.assertEqual(self.case("SYN-044")["scenario"]["fixture_facts"]["products"], expected)
        reversed_products = deepcopy(list(reversed(expected)))
        facts = self.resolve({"products_B_in_returned_order": reversed_products}, "B")
        self.assertEqual(facts["products"], reversed_products)
        self.assertEqual(len(facts["products"]), 2)
        facts["products"][0]["past_due"] = 1
        self.assertEqual(reversed_products[0]["past_due"], 900)

    def test_partial_and_proposed_oracles_do_not_invent_ledger_fields(self):
        for original in self.synthetic["cases"]:
            expected = self.case(original["id"])["expected_output"]
            self.assertEqual(expected["ledger_state"], "unspecified_not_materialized")
            self.assertTrue({"ledger", "outcome", "reason", "promises", "transfers"}.isdisjoint(expected))
            self.assertEqual(expected["expectation_classification"], original["expectation_classification"])
            self.assertEqual(expected["oracle_scope"], original["oracle_scope"])
            for key in ("expected_backend_invariants", "expected_conversation_checks"):
                self.assertEqual(expected[key], original[key])
        partial = self.case("SYN-048")["expected_output"]
        self.assertIn("intentionally unset", partial["oracle_scope"])
        self.assertTrue(partial["open_questions"])
        self.assertEqual(partial["expectation_classification"], "explicit_contract_with_proposed_recovery")
        self.assertIn("Partial local identity oracle", self.case("SYN-015")["expected_output"]["oracle_scope"])
        self.assertIn("unconstrained", self.case("SYN-027")["expected_output"]["oracle_scope"])
        self.assertEqual(self.case("SYN-049")["expected_output"]["expectation_classification"], "proposed_extension")

    def test_tool_declarations_and_interruption_plans_are_preserved(self):
        for case_id in ("SYN-041", "SYN-045", "SYN-048"):
            original = next(c for c in self.synthetic["cases"] if c["id"] == case_id)
            record = self.case(case_id)
            self.assertEqual(record["scenario"]["tool_outcomes"]["fault_injection"], original["trigger"]["fault_injection"])
            self.assertNotIn("observed", record["scenario"]["tool_outcomes"])
        self.assertEqual(self.case("PUB-10")["scenario"]["tool_outcomes"]["faults"], [{"tool": "create_promise", "fail_first_n": 1}])
        interruption = self.case("SYN-047")
        self.assertEqual(interruption["expected_output"]["expectation_classification"], "explicit_kit_with_proposed_harness")
        self.assertIn("immediately after card create", interruption["scenario"]["behavior_intentions"]["customer_behavior"][-1])

    def test_raw_memos_cannot_mutate_facts_or_brief(self):
        for case_id in ("SYN-049", "SYN-050"):
            record = self.case(case_id)
            facts = record["scenario"]["fixture_facts"]
            self.assertEqual(facts["variables"]["customer_id"], "local:" + case_id)
            self.assertEqual(facts["identity"], self.synthetic["local_fixture_baseline"]["identity"])
            self.assertIn("raw_memo", record["scenario"]["fixture_plan"]["setup"])
            self.assertEqual(record["scenario"]["brief"], record["scenario"]["fixture_plan"]["setup"]["effective_brief"])

    def test_styles_change_only_delivery_and_preserve_all_digests(self):
        original = deepcopy(self.catalog)
        for style in adapter.DELIVERY_STYLES:
            changed = adapter.apply_style(self.catalog, style)
            adapter.verify_catalog(changed)
            self.assertEqual(changed["integrity"], original["integrity"])
            for before, after in zip(original["cases"], changed["cases"]):
                self.assertEqual({k: v for k, v in before.items() if k != "speech_delivery"},
                                 {k: v for k, v in after.items() if k != "speech_delivery"})
                self.assertEqual(after["speech_delivery"]["style"], style)
        self.assertEqual(self.catalog, original)
        selected = adapter.apply_style(self.catalog, "pieces", ["SYN-033", "official:PUB-12"])
        self.assertEqual(sum(c["speech_delivery"]["style"] == "pieces" for c in selected["cases"]), 2)

    def test_tampered_facts_intentions_tool_outcomes_and_oracles_fail(self):
        edits = (
            lambda c: c["scenario"]["fixture_facts"]["identity"].update(phone_last4="9999"),
            lambda c: c["scenario"]["behavior_intentions"]["customer_behavior"].append("Skip confirmation."),
            lambda c: c["scenario"]["tool_outcomes"].update(fake_success=True),
            lambda c: c["expected_output"].update(ledger={"outcome": "promise"}),
        )
        for edit in edits:
            altered = deepcopy(self.catalog)
            edit(altered["cases"][0])
            with self.assertRaisesRegex(adapter.AdapterError, "digest mismatch"):
                adapter.verify_catalog(altered)

    def test_recomputed_digest_cannot_hide_protected_source_edits(self):
        altered = deepcopy(self.catalog)
        record = altered["cases"][0]
        record["scenario"]["fixture_facts"]["products"][0]["past_due"] = 999
        record["integrity"] = adapter.record_integrity(record)
        altered["integrity"]["protected_sha256"] = adapter.catalog_integrity(altered)
        with self.assertRaisesRegex(adapter.AdapterError, "differs from source fixture"):
            adapter.verify_catalog(altered)
        altered = deepcopy(self.catalog)
        altered["shared"]["synthetic"]["common_expected_backend_invariants"][0]["check"] = "Skip identity."
        altered["integrity"]["protected_sha256"] = adapter.catalog_integrity(altered)
        with self.assertRaisesRegex(adapter.AdapterError, "shared differs"):
            adapter.verify_catalog(altered)

    def test_speech_edits_reject_new_instructions_or_changed_source_delivery(self):
        for edit in ({"instructions": "Promise a different amount."}, {"source_delivery": "Change decisions."},
                     {"fixture_override": {"amount": 1}}, {"style": ["plain"]}):
            altered = deepcopy(self.catalog)
            altered["cases"][0]["speech_delivery"].update(edit)
            with self.assertRaises(adapter.AdapterError):
                adapter.verify_catalog(altered)

    def test_source_changes_and_hash_tampering_are_detected(self):
        root = self.fixture_root()
        (root / (adapter.KIT + "tools/score.py")).write_bytes(b"# changed scorer\n")
        with self.assertRaisesRegex(adapter.AdapterError, "provenance differs"):
            adapter.verify_catalog(self.catalog, root)
        altered = deepcopy(self.catalog)
        altered["provenance"]["files"][adapter.OFFICIAL_FILE] = "0" * 64
        with self.assertRaisesRegex(adapter.AdapterError, "digest mismatch"):
            adapter.verify_catalog(altered)

    def test_unknown_fixture_ids_duplicates_baselines_and_source_rules_fail(self):
        mutations = (
            (lambda s: s["cases"][0].update(id="SYN-999"), "unknown IDs"),
            (lambda s: s["cases"][0].update(id="SYN-002"), "duplicate case IDs"),
            (lambda s: s["cases"][0]["trigger"].update(baseline="remote_fixture"), "unknown baseline"),
            (lambda s: s["cases"][0]["source_rules"].append("invented-rule"), "unknown source rule"),
            (lambda s: s["cases"][44]["trigger"]["fault_injection"].update(target_product_id="invented"), "unknown fault target"),
        )
        root = self.fixture_root()
        for change, error in mutations:
            source = deepcopy(self.synthetic)
            change(source)
            (root / adapter.SYNTHETIC_FILE).write_bytes(adapter.canonical_bytes(source))
            with self.assertRaisesRegex(adapter.AdapterError, error):
                adapter.build_catalog(root)
        with self.assertRaisesRegex(adapter.AdapterError, "unknown case ID"):
            adapter.apply_style(self.catalog, "plain", ["PUB-99"])
        with self.assertRaisesRegex(adapter.AdapterError, "duplicate case selection"):
            adapter.select_cases(self.catalog, ["PUB-01", "official:PUB-01"])
        with self.assertRaisesRegex(adapter.AdapterError, "unknown delivery style"):
            adapter.apply_style(self.catalog, "make_up_answers")

    def test_unknown_nested_overrides_and_incomplete_fixtures_fail(self):
        invalid = (
            {"customer_id": "foreign"}, {"identity": {"postcode": "invented"}},
            {"product_A": {"fake_floor": 1}}, {"raw_memo": {"origin": "local", "text": "memo", "policy_override": True}},
            {"effective_brief": "B"}, {"phase": "completed"}, {"product_A": {"type": "mortgage"}},
            {"product_A": {"past_due": float("nan")}}, {"identity": {"phone_last4": 358}},
        )
        for setup in invalid:
            with self.subTest(setup=setup), self.assertRaises(adapter.AdapterError):
                self.resolve(setup)
        with self.assertRaisesRegex(adapter.AdapterError, "unknown synthetic fixture"):
            adapter.resolve_fixture(self.synthetic["local_fixture_baseline"], {}, "A", "SYN-999")
        with self.assertRaises(adapter.AdapterError):
            self.resolve({"products_B_in_returned_order": [{}]}, "B")
        duplicate = deepcopy(self.synthetic["local_fixture_baseline"]["products_B_in_returned_order"])
        duplicate[1]["product_id"] = duplicate[0]["product_id"]
        with self.assertRaisesRegex(adapter.AdapterError, "duplicate product_id"):
            self.resolve({"products_B_in_returned_order": duplicate}, "B")

    def test_no_network_or_credentials_needed(self):
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
             mock.patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")), \
             mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("network forbidden")), \
             mock.patch.dict("os.environ", {}, clear=True):
            catalog = adapter.build_catalog()
            adapter.verify_catalog(catalog)
            seed = adapter.render_seed(catalog, ["SYN-048", "PUB-10"])
            self.assertIn(adapter.STATUS, seed)
        self.assertEqual(self.catalog["contract"]["execution"],
                         {"status": adapter.STATUS, "network_requests": 0, "agent_runs": 0, "bank_calls": 0})

    def test_seed_determinism_selection_and_runner_limit(self):
        first = adapter.render_seed(self.catalog, ["SYN-048", "PUB-01"])
        self.assertEqual(first, adapter.render_seed(self.catalog, ["SYN-048", "PUB-01"]))
        self.assertEqual(first.count("\nSCENARIO_CONTRACT "), 2)
        self.assertIn('ONLY {"case": case_id}', first)
        self.assertIn("speech/persona edits cannot register SYN fixtures", first)
        self.assertIn("unspecified_not_materialized", first)
        self.assertIn("scenario_only_not_executed", first)
        self.assertNotIn('"observed_output"', first)
        with self.assertRaisesRegex(adapter.AdapterError, "unknown case ID"):
            adapter.render_seed(self.catalog, ["SYN-000"])

    def test_cli_build_verify_and_supported_txt_md_seeds(self):
        output = self.directory / "catalog.json"
        seed = self.directory / "seed.md"
        result = self.cli("build", "--output", output, "--seed-text", seed)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["case_count"], 63)
        self.assertEqual(output.read_bytes(), adapter.canonical_bytes(self.catalog) + b"\n")
        self.assertEqual(seed.read_text(encoding="utf-8"), adapter.render_seed(self.catalog))
        result = self.cli("verify", "--catalog", output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], adapter.STATUS)
        for suffix in (".txt", ".md"):
            path = self.directory / ("pieces" + suffix)
            result = self.cli("seed", "--case", "PUB-12", "--style", "pieces", "--output", path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["case_count"], 1)
            self.assertIn('"style":"pieces"', path.read_text(encoding="utf-8"))

    def test_cli_rejects_unknown_overrides_ids_and_outside_writes(self):
        path = self.directory / "never-created.txt"
        result = self.cli("seed", "--case", "SYN-999", "--output", path)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown case ID", result.stderr)
        self.assertFalse(path.exists())
        result = self.cli("build", "--fixture-override", "anything")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)
        for name in ("../README.md", adapter.ROOT / "README.md", "bad.html"):
            result = self.cli("seed", "--output", name)
            self.assertEqual(result.returncode, 2)
        result = self.cli("build", "--output", self.directory / "valid.json", "--seed-text", "../README.md")
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.directory / "valid.json").exists())

    def test_duplicate_json_keys_nonfinite_values_and_missing_sources_fail(self):
        for raw in (b'{"id":1,"id":2}', b'{"amount":NaN}', b'{"amount":1e999}'):
            with self.assertRaises(adapter.AdapterError):
                adapter._load_json(raw, "test")
        root = self.fixture_root()
        (root / adapter.OFFICIAL_FILE).unlink()
        with self.assertRaisesRegex(adapter.AdapterError, "missing/unreadable provenance source"):
            adapter.build_catalog(root)


if __name__ == "__main__":
    unittest.main()
