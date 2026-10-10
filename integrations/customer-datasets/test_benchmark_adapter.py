import copy
import json
from pathlib import Path
import tempfile
import unittest
import jsonschema

import benchmark_adapter as b


class FixtureContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads((b.OUT / "local-cases.json").read_text(encoding="utf-8"))
        cls.hosted = json.loads((b.OUT / "hosted-cases.json").read_text(encoding="utf-8"))

    def fresh(self, family="full_payment", seed=0):
        return b.fresh_case(family, seed)

    def test_all_authored_reference_fixtures_and_schemas(self):
        report = b.validation(self.cases, self.hosted)
        self.assertEqual(report["errors"], [])
        self.assertGreaterEqual(report["local_scenarios"], 360)
        self.assertFalse(report["agent_executed"])
        self.assertFalse(report["transcript_judge_executed"])
        self.assertEqual(len({c["family"] for c in self.cases}), 27)

    def test_unmodified_official_scorer_is_the_ledger_oracle(self):
        case = self.fresh()
        ledger = b.local.replay(case)
        self.assertTrue(b.local.SCORE(case, ledger)["pass"])
        verdict = b.score(case, ledger)
        self.assertTrue(verdict["ledger_and_trace_pass"])
        self.assertFalse(verdict["pass"])
        self.assertFalse(verdict["transcript_pass"])

    def test_transcript_fail_never_gets_ledger_only_pass(self):
        case = self.fresh()
        verdict = b.score(case, b.local.replay(case), {"outcome": "fail", "reason": "disclosed debt before verification"})
        self.assertTrue(verdict["ledger_and_trace_pass"])
        self.assertFalse(verdict["pass"])

    def test_missing_transcript_verdict_fails(self):
        case = self.fresh()
        for judge in [None, {}, {"outcome": "pending"}, {"outcome": "unknown"}]:
            self.assertFalse(b.score(case, b.local.replay(case), judge)["pass"])

    def test_duplicate_close_blindspot_is_caught(self):
        case = self.fresh()
        calls = copy.deepcopy(case["execution"]["reference_tool_calls"])
        calls.append(copy.deepcopy(calls[-1]))
        ledger = b.local.replay(case, calls)
        self.assertTrue(b.local.SCORE(case, ledger)["pass"])
        self.assertFalse(b.score(case, ledger, {"outcome": "pass"})["pass"])

    def test_last_tool_and_close_presence(self):
        case = self.fresh()
        calls = case["execution"]["reference_tool_calls"]
        for bad in [calls[:-1], calls + [{"tool": "get_account", "arguments": {"customer_id": case["facts"]["variables"]["customer_id"]}}]]:
            self.assertFalse(b.score(case, b.local.replay(case, bad), {"outcome": "pass"})["pass"])

    def test_forbidden_note_on_brief_a_even_if_note_fails(self):
        case = self.fresh()
        calls = copy.deepcopy(case["execution"]["reference_tool_calls"])
        calls.insert(-1, {"tool": "add_note", "arguments": {"customer_id": case["facts"]["variables"]["customer_id"], "product_id": "p1", "reason": "paid"}})
        self.assertFalse(b.score(case, b.local.replay(case, calls), {"outcome": "pass"})["pass"])

    def test_security_wrong_answer_budget_does_not_reset_per_field(self):
        case = self.fresh("three_wrong")
        ledger = b.local.replay(case)
        self.assertEqual([x["tool"] for x in ledger["calls"]].count("verify_identity"), 4)
        self.assertEqual(ledger["outcome"], "not_verified")
        self.assertFalse(any(x["tool"] == "get_account" for x in ledger["calls"]))

    def test_day_month_hint_keeps_wrong_budget(self):
        case = self.fresh("swapped_dob")
        ledger = b.local.replay(case)
        first = ledger["calls"][0]["result"]
        self.assertEqual(first["hint"], "day_month_swapped")
        self.assertEqual(first["wrong_answers_left"], 3)
        self.assertTrue(b.score(case, ledger)["ledger_and_trace_pass"])

    def test_cent_below_floor_mutation_is_rejected(self):
        case = self.fresh("below_floor")
        calls = copy.deepcopy(case["execution"]["reference_tool_calls"])
        calls[3]["arguments"]["amount"] -= .01
        ledger = b.local.replay(case, calls)
        self.assertTrue(ledger["calls"][3]["result"]["ok"])
        self.assertFalse(b.score(case, ledger, {"outcome": "pass"})["pass"])

    def test_holiday_despite_successful_backend_is_rejected(self):
        case = self.fresh("nonbusiness_date", 2)
        calls = copy.deepcopy(case["execution"]["reference_tool_calls"])
        calls[3]["arguments"]["date"] = "2026-10-26"
        ledger = b.local.replay(case, calls)
        self.assertTrue(ledger["calls"][3]["result"]["ok"])
        self.assertFalse(b.score(case, ledger, {"outcome": "pass"})["pass"])

    def test_late_and_early_bands_get_different_deadlines(self):
        case = self.fresh("split_deadlines")
        promises = case["expected"]["promises"]
        self.assertGreater(promises[0]["date"], promises[1]["date"])
        self.assertEqual(promises[0]["date"], promises[2]["date"])

    def test_failed_product_keeps_successful_products_and_two_calls_only(self):
        case = self.fresh("partial_failure")
        ledger = b.local.replay(case)
        self.assertEqual([p["product_id"] for p in ledger["promises"]], ["p1"])
        self.assertEqual(ledger["notes"][0], {"product_id": "p2", "reason": "service_error"})
        self.assertEqual(sum(c["tool"] == "create_promise" and c["arguments"].get("product_id") == "p2" for c in ledger["calls"]), 2)
        calls = copy.deepcopy(case["execution"]["reference_tool_calls"])
        calls.insert(5, copy.deepcopy(calls[4]))
        self.assertFalse(b.score(case, b.local.replay(case, calls), {"outcome": "pass"})["pass"])

    def test_transfer_suppresses_notes_even_after_recorded_promise(self):
        case = self.fresh("transfer_after_promise")
        ledger = b.local.replay(case)
        self.assertEqual(ledger["outcome"], "transferred")
        self.assertEqual(len(ledger["promises"]), 1)
        self.assertEqual(ledger["notes"], [])
        calls = copy.deepcopy(case["execution"]["reference_tool_calls"])
        calls.insert(3, {"tool": "add_note", "arguments": {"customer_id": case["facts"]["variables"]["customer_id"], "product_id": "p3", "reason": "dispute"}})
        self.assertFalse(b.score(case, b.local.replay(case, calls), {"outcome": "pass"})["pass"])

    def test_third_party_actor_does_not_receive_security_facts(self):
        case = self.fresh("callback_boundary")
        prompt = b.customer_prompt(case)["prompt"]
        self.assertNotIn(case["facts"]["identity"]["date_of_birth"], prompt)
        self.assertNotIn(case["facts"]["identity"]["phone_last4"], prompt)
        self.assertNotIn("promises", prompt)

    def test_actor_does_not_receive_backend_faults_or_expected_ledger(self):
        case = self.fresh("partial_failure")
        prompt = b.customer_prompt(case)["prompt"]
        self.assertNotIn("synthetic declared failure", prompt)
        self.assertNotIn("service_error", prompt)
        self.assertNotIn('"product_id"', prompt)
        self.assertNotIn(case["facts"]["variables"]["customer_id"], prompt)

    def test_all_sources_retain_licensed_dataset_provenance(self):
        sourced = [c for c in self.cases if c["id"].startswith("DATA-")]
        self.assertEqual(len(sourced), 50)
        for case in sourced:
            source = case["provenance"]["dataset_transformation"]
            self.assertEqual(source["dataset"]["license"], "CC-BY-4.0")
            self.assertEqual(len(source["dataset"]["sha256"]), 64)
            self.assertTrue(source["dataset"]["attribution"])
            self.assertNotIn("utterance", source)

    def test_flat_export_preserves_fault_schedule_and_rule_links(self):
        case = self.fresh("partial_failure")
        row = b.runner_case(case)
        self.assertEqual(row["faults"], case["facts"]["faults"])
        self.assertEqual(row["oracle_rule_refs"], case["oracle"]["rule_refs"])
        self.assertFalse(row["hosted_registered"])

    def test_fixture_schema_checks_identity_ledger_items_and_reason_pair(self):
        case = copy.deepcopy(self.cases[-1])
        validator = jsonschema.Draft202012Validator(b.scenario_schema(), format_checker=jsonschema.FormatChecker())
        def errors(c):
            return list(validator.iter_errors({"schema_version": "1.0.0", "rule_registry": {}, "shared_constraints": [], "scenarios": [c]}))
        self.assertEqual(errors(case), [])
        bad = copy.deepcopy(case); bad["facts"]["identity"]["phone_last4"] = 7
        self.assertTrue(errors(bad))
        bad = copy.deepcopy(case); bad["expected"]["reason"] = "made_up"
        self.assertTrue(errors(bad))
        bad = copy.deepcopy(case); bad["expected"]["promises"] = [{"product_id": "p1", "amount": "420.01", "date": "2026-10-14"}]
        self.assertTrue(errors(bad))

    def test_hosted_public_facts_cannot_be_edited(self):
        b.validate_hosted(self.hosted)
        for field in ["variables", "identity", "products", "script", "expected", "checks", "brief"]:
            rows = copy.deepcopy(self.hosted[:1])
            rows[0][field] = "changed"
            with self.subTest(field=field), self.assertRaises(ValueError):
                b.validate_hosted(rows)

    def test_new_local_case_cannot_be_sent_to_hosted_mock(self):
        row = b.runner_case(self.fresh())
        row.update(variant_id="PUB-01__pieces", local_only=False, hosted_registered=True)
        with self.assertRaises(ValueError):
            b.validate_hosted([row])

    def test_hosted_duplicate_variant_and_unknown_actor_instructions_rejected(self):
        with self.assertRaises(ValueError):
            b.validate_hosted([self.hosted[0], self.hosted[0]])
        row = copy.deepcopy(self.hosted[0]); row["delivery_profile"] = "ignore policy"
        with self.assertRaises(ValueError):
            b.validate_hosted([row])
        row = copy.deepcopy(self.hosted[0]); row["extra_prompt"] = "ignore policy"
        with self.assertRaises(ValueError):
            b.validate_hosted([row])

    def test_same_public_fixture_supports_distinct_variant_ids(self):
        rows = [r for r in self.hosted if r["id"] == "PUB-01"]
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({r["variant_id"] for r in rows}), 9)
        b.validate_hosted(rows)

    def test_malformed_ledgers_fail_closed(self):
        case = self.fresh()
        for ledger in [{}, {"promises": None}, {"calls": []}, {"promises": [None]}]:
            self.assertFalse(b.score(case, ledger, {"outcome": "pass"})["pass"])

    def test_fabricated_verification_or_truthy_success_never_passes(self):
        case = self.fresh()
        base = b.local.replay(case)
        mutations = []
        ledger = copy.deepcopy(base); ledger["calls"][0]["arguments"]["answer"] = "1985-04-08"; mutations.append(ledger)
        ledger = copy.deepcopy(base); ledger["calls"][0]["result"]["ok"] = False; mutations.append(ledger)
        ledger = copy.deepcopy(base); ledger["calls"][3]["result"]["ok"] = "false"; mutations.append(ledger)
        ledger = copy.deepcopy(base); ledger["calls"][2]["result"]["products"] = []; mutations.append(ledger)
        ledger = copy.deepcopy(base); ledger["calls"][-1]["result"]["ok"] = False; mutations.append(ledger)
        for i, ledger in enumerate(mutations):
            with self.subTest(i=i):
                self.assertFalse(b.score(case, ledger, {"outcome": "pass"})["pass"])

    def test_failed_identity_outcome_without_security_attempts_rejected(self):
        case = self.fresh("three_wrong")
        ledger = b.local.replay(case)
        ledger["calls"] = ledger["calls"][-1:]
        self.assertTrue(b.local.SCORE(case, ledger)["pass"])
        self.assertFalse(b.score(case, ledger, {"outcome": "pass"})["pass"])

    def test_failed_forbidden_promise_attempt_is_still_rejected(self):
        case = self.fresh("hardship_declines")
        ledger = b.local.replay(case)
        ledger["calls"].insert(-1, {"tool": "create_promise", "arguments": {"customer_id": case["facts"]["variables"]["customer_id"], "product_id": "p1", "amount": 420.01, "date": "2026-10-14"}, "result": {"ok": False, "error": "temporary failure"}})
        self.assertTrue(b.local.SCORE(case, ledger)["pass"])
        self.assertFalse(b.score(case, ledger, {"outcome": "pass"})["pass"])

    def test_unknown_product_and_cross_customer_call_rejected(self):
        case = self.fresh()
        for field, value in [("product_id", "invented"), ("customer_id", "another-call")]:
            calls = copy.deepcopy(case["execution"]["reference_tool_calls"])
            calls[3]["arguments"][field] = value
            self.assertFalse(b.score(case, b.local.replay(case, calls), {"outcome": "pass"})["pass"])

    def test_pack_hashes_and_source_freeze(self):
        b.verify_pack()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            for source in b.OUT.glob("*.json"):
                (target / source.name).write_bytes(source.read_bytes())
            data = json.loads((target / "hosted-cases.json").read_text(encoding="utf-8"))
            data[0]["expected"]["outcome"] = "paid"
            (target / "hosted-cases.json").write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                b.verify_pack(target)


if __name__ == "__main__":
    unittest.main()
