"""Offline contracts and synthetic receipt controls; never actor executions.

Expected-derived programs below exist only to construct negative receipt controls.
A replay cannot establish spoken consent, an agent run, or a transcript verdict.
"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, is_dataclass
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import benchmark_adapter as b
import speech_stress_adapter as s


SCOPE = "authored_text_only_speech_stress_on_registered_bank_facts_not_official_pub_score"


def forbid_credential_read(key, default=None):
    # argparse/gettext read locale and terminal settings; supply defaults without
    # reading the real environment. Credential lookup is an immediate failure.
    if any(token in str(key).upper() for token in ("FREYA", "KEY", "TOKEN", "SECRET", "CREDENTIAL")):
        raise AssertionError("credential lookup attempted")
    return default


def authored_row(brief="A"):
    """An independently authored, source-bound row, not catalog equality."""
    row = deepcopy(b.PUBLIC["PUB-01" if brief == "A" else "PUB-11"])
    row.update(variant_id=row["id"] + "__speech_unit_contract", third_party=False,
               faults=[], style=None, delivery_profile="plain", local_only=False,
               hosted_registered=True, execution_status="not_executed",
               evaluation_scope=SCOPE, oracle_rule_refs=["A11"],
               stress={"modality": "text_only_approximation", "tags": ["self_correction"],
                       "limitations": "Authored text only; no audio or ASR execution."},
               title="An independently authored correction",
               script="Confirms identity and answers security when asked. Offers the card minimum today. Confirms the final read-back.",
               checks=["No promise before verification and final confirmation."])
    row["expected"] = {"outcome": "promise", "reason": None,
                       "promises": [{"product_id": "p1", "amount": row["products"][0]["minimum_payment"], "date": "2026-10-14"}],
                       "notes": [], "callbacks": [], "transfers": []}
    if brief == "B":
        row["script"] += " Refuses the personal loan and says the car loan is already paid."
        row["expected"]["notes"] = [{"product_id": "p2", "reason": "refused"},
                                      {"product_id": "p3", "reason": "paid"}]
    return row


def synthetic_receipts(row):
    """Explicitly synthetic expected-derived receipt control, NOT actor execution."""
    case = s.kernel_case(row)
    cid = case["facts"]["variables"]["customer_id"]
    calls = []

    def call(tool, **arguments):
        calls.append({"tool": tool, "arguments": {"customer_id": cid, **arguments}})

    if row["expected"]["reason"] == "failed":
        for _ in range(3):
            call("verify_identity", field="date_of_birth", answer="1900-01-01")
    elif not row["third_party"] and row["expected"]["outcome"] not in {"not_verified", "not_reached"}:
        for field in ("date_of_birth", "phone_last4"):
            call("verify_identity", field=field, answer=row["identity"][field])
        call("get_account")
    for key, tool in (("promises", "create_promise"), ("notes", "add_note"),
                      ("callbacks", "schedule_callback"), ("transfers", "transfer_to_agent")):
        for record in row["expected"][key]:
            call(tool, **record)
    close = {"outcome": row["expected"]["outcome"]}
    if row["expected"]["reason"] is not None:
        close["reason"] = row["expected"]["reason"]
    call("close_call", **close)
    return case, b.local.replay(case, calls)


class StructuralContractTests(unittest.TestCase):
    def assert_invalid(self, row):
        with self.assertRaises(ValueError):
            s.StressCatalog.from_rows([row])
        with self.assertRaises(ValueError):
            s.validate_hosted([row])

    def test_custom_script_title_and_ledger_are_structurally_valid(self):
        for brief in ("A", "B"):
            row = authored_row(brief)
            with self.subTest(brief=brief):
                pack = s.StressCatalog.from_rows([row])
                s.validate_hosted(pack)
                s.validate_hosted(pack.to_rows())
                self.assertEqual(pack.to_rows(), [row])
                self.assertNotEqual(row["script"], b.PUBLIC[row["id"]]["script"])
                self.assertNotEqual(row["expected"], b.PUBLIC[row["id"]]["expected"])
                row["title"] = "Another valid authored title"
                row["script"] += " Says 'one moment' once before giving the complete answer."
                s.validate_hosted(s.StressCatalog.from_rows([row]))

    def test_typed_catalog_is_frozen_and_defensively_snapshotted(self):
        rows = [authored_row()]
        pack = s.StressCatalog.from_rows(rows)
        original = deepcopy(rows)
        self.assertTrue(is_dataclass(pack))
        self.assertIsInstance(pack.scenarios, tuple)
        with self.assertRaises(FrozenInstanceError):
            pack.scenarios = ()
        scenario = pack.scenarios[0]
        self.assertTrue(is_dataclass(scenario))
        with self.assertRaises(FrozenInstanceError):
            scenario.script = "mutated"
        self.assertTrue(is_dataclass(scenario.expected))
        with self.assertRaises(FrozenInstanceError):
            scenario.expected.outcome = "paid"
        for obj in (pack, scenario, scenario.expected):
            for field in fields(obj):
                self.assertNotIsInstance(getattr(obj, field.name), (dict, list, set))
        rows[0]["products"][0]["past_due"] = 999
        rows[0]["expected"]["promises"].clear()
        exported = pack.to_rows()
        exported[0]["identity"]["phone_last4"] = "0000"
        exported[0]["stress"]["tags"].append("mutated")
        self.assertEqual(pack.to_rows(), original)

    def test_subset_valid_duplicates_and_empty_rejected(self):
        rows = [authored_row("A"), authored_row("B")]
        s.validate_hosted(rows)
        s.validate_hosted(s.StressCatalog.from_rows(rows[:1]))
        for bad in ([], [rows[0], deepcopy(rows[0])], {}, None):
            with self.subTest(value=bad), self.assertRaises(ValueError):
                s.StressCatalog.from_rows(bad)

    def test_catalog_reads_requested_path_without_creating_files(self):
        target = s.OUT.parent / "unit-only-virtual-speech-catalog.json"
        row = authored_row()
        original_read = Path.read_text
        def virtual_catalog(path, *args, **kwargs):
            return json.dumps([row]) if path == target else original_read(path, *args, **kwargs)
        with patch.object(Path, "read_text", virtual_catalog):
            self.assertEqual(s.catalog(target).to_rows(), [row])

    def test_strict_envelope_types_extra_fields_stress_and_scope(self):
        changes = [("third_party", "false"), ("hosted_registered", 1),
                   ("local_only", 0), ("unexpected", "field"),
                   ("evaluation_scope", "official_pub_score"), ("id", "PUB-02"),
                   ("stress", {"modality": "audio", "tags": ["fast"], "limitations": "None"}),
                   ("stress", {"modality": "text_only_approximation", "tags": [True], "limitations": "None"})]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                row = authored_row(); row[key] = value
                self.assert_invalid(row)
        row = authored_row(); row["expected"]["unexpected"] = True
        self.assert_invalid(row)
        row = authored_row(); del row["stress"]["limitations"]
        self.assert_invalid(row)

    def test_original_bank_facts_and_faults_cannot_be_redefined(self):
        mutations = [("variables", "now", "2026-10-15T11:00"),
                     ("identity", "phone_last4", "0000"),
                     ("variables", "customer_id", "foreign-customer")]
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                row = authored_row(); row[section][key] = value
                self.assert_invalid(row)
        for value in (True, 0, 419.0):
            row = authored_row(); row["products"][0]["past_due"] = value
            self.assert_invalid(row)
        row = authored_row(); row["products"][0]["undocumented"] = "payload"
        self.assert_invalid(row)
        row = authored_row(); row["faults"] = [{"tool": "create_promise", "product_id": "p1", "fail_first_n": 1, "result": {"ok": False}}]
        self.assert_invalid(row)
        row = authored_row("B"); row["products"].reverse()
        self.assert_invalid(row)

    def test_promise_schema_dates_products_numbers_and_extra_fields(self):
        for key, value in (("date", "2026-02-30"), ("date", "2026-10-17"),
                           ("date", "2027-01-01"), ("product_id", "unknown"),
                           ("amount", True), ("amount", "126"), ("amount", 125.99),
                           ("amount", 420.01), ("amount", float("nan")),
                           ("customer_id", "oracle-leak"), ("extra", "field")):
            with self.subTest(key=key, value=value):
                row = authored_row(); row["expected"]["promises"][0][key] = value
                self.assert_invalid(row)

    def test_callback_transfer_note_and_close_contracts(self):
        bad = []
        row = authored_row(); row["expected"]["reason"] = "paid"; bad.append(row)
        row = authored_row(); row["expected"]["notes"] = [{"product_id": "p1", "reason": "paid"}]; bad.append(row)
        row = authored_row("B"); row["expected"]["notes"].pop(); bad.append(row)
        row = authored_row("B"); row["expected"]["notes"][0]["reason"] = "invented"; bad.append(row)
        row = authored_row("B"); row["expected"]["notes"][0]["extra"] = True; bad.append(row)
        row = authored_row(); row["expected"]["transfers"] = [{"queue": "invented"}]; bad.append(row)
        for value in ({"date": "2026-02-30", "time": "12:00"}, {"date": "2026-10-14", "time": "09:00"},
                      {"date": "2026-10-14", "time": "12:00", "extra": True}):
            row = authored_row(); row["expected"].update(outcome="not_reached", reason="callback", promises=[], callbacks=[value]); bad.append(row)
        for index, row in enumerate(bad):
            with self.subTest(index=index):
                self.assert_invalid(row)

    def test_actor_formatter_never_receives_expected_products_or_rules(self):
        row = authored_row()
        with patch.object(b.official, "persona_for", wraps=b.official.persona_for) as formatter:
            spec = s.persona_for(row)
        actor, identity = formatter.call_args.args[:2]
        for key in ("expected", "products", "faults", "oracle_rule_refs", "stress"):
            self.assertNotIn(key, actor)
        self.assertEqual(actor.get("checks", []), [])
        self.assertEqual(actor["script"], row["script"])
        self.assertEqual(identity["identity"], row["identity"])
        self.assertIn(row["script"], spec["prompt"])
        other = deepcopy(row)
        other["expected"]["promises"][0]["amount"] = 200
        other["checks"] = ["ORACLE_CHECK_SENTINEL_ONLY"]
        self.assertEqual(s.persona_for(other)["prompt"], spec["prompt"])
        self.assertNotIn("ORACLE_CHECK_SENTINEL_ONLY", s.persona_for(other)["prompt"])
        self.assertNotIn('"product_id"', spec["prompt"])

    def test_third_party_actor_never_gets_identity_answers(self):
        row = authored_row()
        row.update(third_party=True, family="Third party", script="A sibling answers. Does not know any security answers and says this is the wrong number.")
        row["expected"].update(outcome="not_reached", reason="wrong_number", promises=[])
        with patch.object(b.official, "persona_for", wraps=b.official.persona_for) as formatter:
            spec = s.persona_for(row)
        self.assertEqual(formatter.call_args.args[1], {"identity": {}})
        for value in row["identity"].values():
            self.assertNotIn(value, spec["prompt"])


class ReceiptGuardTests(unittest.TestCase):
    def setUp(self):
        self.row = authored_row("B")
        self.case, self.base = synthetic_receipts(self.row)
        self.assertTrue(b.local.SCORE(self.case, self.base)["pass"])
        self.assertTrue(s.score(self.case, self.base)["ledger_and_trace_pass"])

    def assert_corrupt(self, ledger, case=None):
        case = self.case if case is None else case
        self.assertTrue(b.local.SCORE(case, ledger)["pass"], "original ledger-only oracle must pass the negative control")
        before = deepcopy(ledger)
        verdict = s.score(case, ledger, {"outcome": "pass"})
        self.assertFalse(verdict["ledger_and_trace_pass"], verdict)
        self.assertFalse(verdict["pass"], verdict)
        self.assertEqual(ledger, before)

    def test_kernel_facts_are_synthetic_and_independent(self):
        cid = self.case["facts"]["variables"]["customer_id"]
        self.assertTrue(cid.startswith("local-"))
        self.assertNotIn("customer_id", self.row["variables"])
        self.assertEqual([p["product_id"] for p in self.case["facts"]["products"]], ["p1", "p2", "p3"])
        self.case["facts"]["products"][0]["past_due"] = 999
        self.assertEqual(self.row["products"][0]["past_due"], 220)

    def test_divergent_injected_local_facts_rejected_before_scorer(self):
        for section, key, value in (("variables", "customer_id", "foreign-local"),
                                    ("identity", "phone_last4", "9999")):
            case = deepcopy(self.case); case["facts"][section][key] = value
            with self.subTest(section=section), patch.object(b, "score", side_effect=AssertionError("invalid facts reached scorer")):
                self.assertFalse(s.score(case, self.base, {"outcome": "pass"})["pass"])
        case = deepcopy(self.case); case["facts"]["products"].reverse()
        with patch.object(b, "score", side_effect=AssertionError("invalid facts reached scorer")):
            self.assertFalse(s.score(case, self.base)["ledger_and_trace_pass"])

    def test_invalid_authored_schema_is_rejected_before_original_scorer(self):
        case = deepcopy(self.case); case["expected"]["promises"][0]["amount"] = True
        with patch.object(b, "score", side_effect=AssertionError("invalid schema reached scorer")):
            self.assertFalse(s.score(case, self.base, {"outcome": "pass"})["pass"])

    def test_false_success_verification_receipts(self):
        for index in (0, 1):
            ledger = deepcopy(self.base); ledger["calls"][index]["result"]["verified"] = False
            with self.subTest(index=index):
                self.assert_corrupt(ledger)
        ledger = deepcopy(self.base); ledger["calls"][0]["arguments"]["answer"] = "1900-01-01"
        self.assert_corrupt(ledger)

    def test_account_must_be_complete_ordered_and_successful(self):
        products = self.base["calls"][2]["result"]["products"]
        for returned in (products[:1], products[::-1], products + [products[0]], []):
            ledger = deepcopy(self.base); ledger["calls"][2]["result"]["products"] = deepcopy(returned)
            with self.subTest(returned=returned):
                self.assert_corrupt(ledger)
        ledger = deepcopy(self.base); ledger["calls"][2]["result"]["ok"] = False
        self.assert_corrupt(ledger)

    def test_customer_id_binding_local_and_hosted(self):
        for index in range(len(self.base["calls"])):
            ledger = deepcopy(self.base); ledger["calls"][index]["arguments"].pop("customer_id")
            with self.subTest(index=index):
                self.assert_corrupt(ledger)
        ledger = deepcopy(self.base)
        for call in ledger["calls"]:
            call["args"] = call.pop("arguments"); call["args"].pop("customer_id")
        self.assert_corrupt(ledger, self.row)
        bound = deepcopy(self.row); bound["_session_customer_id"] = self.case["facts"]["variables"]["customer_id"]
        self.assertTrue(s.score(bound, ledger)["ledger_and_trace_pass"])
        ledger["calls"][0]["args"]["customer_id"] = "foreign-session"
        self.assert_corrupt(ledger, bound)

    def test_boolean_strings_never_count_as_success(self):
        for index in range(len(self.base["calls"])):
            for value in ("true", "false", 1):
                ledger = deepcopy(self.base); ledger["calls"][index]["result"]["ok"] = value
                with self.subTest(index=index, value=value):
                    self.assert_corrupt(ledger)

    def test_original_openapi_request_contract_is_checked_against_receipts(self):
        for key, value in (("amount", True), ("date", "2026-02-30"),
                           ("product_id", "unknown-product"), ("extra", "undocumented")):
            ledger = deepcopy(self.base)
            next(c for c in ledger["calls"] if c["tool"] == "create_promise")["arguments"][key] = value
            with self.subTest(key=key):
                self.assert_corrupt(ledger)

    def test_failed_close_and_ledger_receipt_disagreement(self):
        ledger = deepcopy(self.base); ledger["calls"][-1]["result"]["ok"] = False
        self.assert_corrupt(ledger)
        for tool in ("create_promise", "add_note"):
            ledger = deepcopy(self.base)
            next(c for c in ledger["calls"] if c["tool"] == tool)["result"]["ok"] = False
            with self.subTest(tool=tool):
                self.assert_corrupt(ledger)

    def test_missing_or_failing_transcript_never_yields_agent_pass(self):
        for judge in (None, {}, {"outcome": "pending"}, {"outcome": "fail", "reason": "No valid spoken confirmation"}):
            with self.subTest(judge=judge):
                verdict = s.score(self.case, self.base, judge)
                self.assertTrue(verdict["ledger_and_trace_pass"])
                self.assertFalse(verdict["transcript_pass"])
                self.assertFalse(verdict["pass"])


class PackAndPlanTests(unittest.TestCase):
    def test_saved_catalog_has_ten_authored_source_bound_rows(self):
        pack = s.catalog()
        self.assertIsInstance(pack, s.StressCatalog)
        rows = pack.to_rows()
        self.assertEqual(len(rows), 10)
        self.assertEqual(len({row["variant_id"] for row in rows}), 10)
        self.assertEqual({row["id"] for row in rows}, {"PUB-01", "PUB-11"})
        s.validate_hosted(pack)
        for row in rows:
            for field in ("variables", "identity", "products", "brief"):
                self.assertEqual(row[field], b.PUBLIC[row["id"]][field])
            self.assertNotEqual(row["script"], b.PUBLIC[row["id"]]["script"])
            self.assertEqual(row["evaluation_scope"], SCOPE)
            self.assertEqual(row["stress"]["modality"], "text_only_approximation")
        self.assertTrue(any(row["expected"] != b.PUBLIC[row["id"]]["expected"] for row in rows))
        self.assertTrue(any(row["expected"]["promises"] for row in rows))
        self.assertTrue(any(row["brief"] == "B" and row["expected"]["promises"] and row["expected"]["notes"] for row in rows))

    def test_pack_pins_original_kit_independently_and_validates_catalog(self):
        with patch.object(b, "verify_pack", side_effect=AssertionError("must not depend on base pack")):
            manifest = s.verify_pack()
        self.assertEqual(manifest["evaluation_scope"], SCOPE)
        self.assertEqual(manifest["catalog_sha256"], s.runner.digest(s.catalog().to_rows()))
        self.assertEqual(set(manifest["sources"]), {"tools/score.py", "tools/openapi.json", "tools/run_cases.py", "public-test-set.json", "briefs/brief-a.md", "briefs/brief-b.md"})
        original_read = Path.read_bytes
        def altered_source(path):
            data = original_read(path)
            return data + b"\n# changed original\n" if path == s.KIT / "tools/score.py" else data
        with patch.object(Path, "read_bytes", altered_source), self.assertRaises(ValueError):
            s.verify_pack()
        original_text = Path.read_text
        def altered_catalog(path, *args, **kwargs):
            return "[]" if path == s.OUT else original_text(path, *args, **kwargs)
        with patch.object(Path, "read_text", altered_catalog), self.assertRaises(ValueError):
            s.verify_pack()

    def test_authored_catalog_promise_and_mixed_note_receipt_controls(self):
        rows = s.catalog().to_rows()
        promise = next(row for row in rows if row["brief"] == "A" and row["expected"]["promises"])
        mixed = next(row for row in rows if row["brief"] == "B" and row["expected"]["promises"] and row["expected"]["notes"])
        for row in (promise, mixed):
            with self.subTest(variant=row["variant_id"]):
                case, ledger = synthetic_receipts(row)
                self.assertTrue(b.local.SCORE(case, ledger)["pass"])
                verdict = s.score(case, ledger)
                self.assertTrue(verdict["ledger_and_trace_pass"], verdict)
                self.assertFalse(verdict["pass"])
                self.assertFalse(verdict["transcript_pass"])
                ledger["calls"][-1]["result"]["ok"] = False
                self.assertTrue(b.local.SCORE(case, ledger)["pass"])
                self.assertFalse(s.score(case, ledger, {"outcome": "pass"})["pass"])

    def test_typed_and_list_subset_plans_use_runner_without_client(self):
        rows = [authored_row("B")]
        with patch.object(s.runner, "OfficialClient", side_effect=AssertionError("client constructed")), \
             patch("socket.socket", side_effect=AssertionError("socket created")), \
             patch.object(s.runner, "plan", wraps=s.runner.plan) as planner:
            typed = s.plan(s.StressCatalog.from_rows(rows))
            listed = s.plan(rows)
        self.assertEqual(planner.call_count, 2)
        self.assertEqual(typed, listed)
        self.assertEqual(typed["scope"], SCOPE)
        self.assertEqual(typed["repetitions"], 3)
        self.assertEqual(typed["max_personas_per_batch"], 5)
        self.assertEqual(typed["sessions_required"], 3)
        self.assertFalse(typed["execution_supported"])
        self.assertFalse(typed["voice_asr_certified"])

    def test_main_is_keyless_plan_with_defaults_and_no_socket_or_client(self):
        output = io.StringIO()
        with patch.object(s.runner, "OfficialClient", side_effect=AssertionError("client constructed")), \
             patch("socket.socket", side_effect=AssertionError("socket created")), \
             patch.object(os, "getenv", side_effect=forbid_credential_read), \
             patch.object(os.environ, "get", side_effect=forbid_credential_read), \
             patch.object(s.runner, "plan", wraps=s.runner.plan) as planner, \
             patch("sys.stdout", output):
            self.assertEqual(s.main([]), 0)
        result = json.loads(output.getvalue())
        planner.assert_called_once()
        self.assertEqual(result["mode"], "plan")
        self.assertEqual(result["network_calls"], 0)
        self.assertEqual(result["execution_status"], "not_executed")
        self.assertEqual(result["scope"], SCOPE)
        self.assertEqual(result["repetitions"], 3)
        self.assertEqual(result["max_personas_per_batch"], 5)
        self.assertFalse(result["execution_supported"])

    def test_execute_is_rejected_before_catalog_credentials_client_or_socket(self):
        output = io.StringIO()
        with patch.object(s, "catalog", side_effect=AssertionError("catalog read")), \
             patch.object(s, "verify_pack", side_effect=AssertionError("pack read")), \
             patch.object(s.runner, "OfficialClient", side_effect=AssertionError("client constructed")), \
             patch.object(s.runner, "execute", side_effect=AssertionError("execution attempted")), \
             patch("socket.socket", side_effect=AssertionError("socket created")), \
             patch.object(os, "getenv", side_effect=forbid_credential_read), \
             patch.object(os.environ, "get", side_effect=forbid_credential_read), \
             patch("sys.stdout", output):
            self.assertEqual(s.main(["--execute"]), 2)
        self.assertEqual(json.loads(output.getvalue())["error_code"], "speech_stress_offline_only")


if __name__ == "__main__":
    unittest.main()
