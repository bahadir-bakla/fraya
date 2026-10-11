import copy
import unittest
from datetime import datetime, timezone
from modal_dryrun import evaluate_admission
from train_v2 import ROOT, strict_json


class ModalPlanningSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = strict_json((ROOT / "analysis/learned-layer-design.json").read_bytes())["bounded_modal_h100_experiment"]
        cls.budget = {"profile": "businessforever2338", "target_usd": 30, "hard_cap_usd": 35,
                      "actual_task_cost_usd": 0, "actual_task_cost_verified": True, "reservations": [],
                      "invocations": [], "single_job_at_a_time": True, "max_gpus_per_job": 1, "cloud_stop_utc": "2026-10-11T06:13:01Z"}
        cls.now = datetime(2026, 10, 11, 2, 0, tzinfo=timezone.utc)

    def test_missing_data_and_reservation_is_no_go(self):
        r = evaluate_admission(self.budget, self.plan, self.now)
        self.assertFalse(r["admission_conditions_met"])
        self.assertFalse(r["remote_launch_available"])
        self.assertIn("reviewed_data_gate_not_authorized", r["reasons"])

    def test_reservation_uses_h200_maximum(self):
        r = evaluate_admission(self.budget, self.plan, self.now)
        self.assertEqual(r["gpu_rate_basis"]["maximum_used"], .001261)
        self.assertGreater(r["illustrative_compute_cost_usd"], 6.0)
        self.assertLess(r["illustrative_compute_cost_usd"], 10.0)

    def test_global_budget_is_not_per_worker(self):
        budget = copy.deepcopy(self.budget)
        budget["actual_task_cost_usd"] = 26
        r = evaluate_admission(budget, self.plan, self.now)
        self.assertIn("global_target_30_would_be_exceeded", r["reasons"])
        self.assertIn("global_hard_cap_35_would_be_exceeded", r["reasons"])

    def test_deadline_and_concurrency_veto(self):
        budget = copy.deepcopy(self.budget)
        budget["invocations"] = [{"status": "running"}]
        r = evaluate_admission(budget, self.plan, datetime(2026, 10, 11, 6, 14, tzinfo=timezone.utc))
        self.assertIn("another_job_active", r["reasons"])
        self.assertIn("cloud_stop_deadline_passed", r["reasons"])

    def test_negative_or_nonfinite_spend_rejected(self):
        for value in (-1, float("nan"), float("inf")):
            budget = dict(self.budget, actual_task_cost_usd=value)
            with self.assertRaises(ValueError):
                evaluate_admission(budget, self.plan, self.now)

    def test_planning_never_mutates_parent_ledger(self):
        before = copy.deepcopy(self.budget)
        evaluate_admission(self.budget, self.plan, self.now)
        self.assertEqual(before, self.budget)

    def test_billing_rule_and_wall_timeout_are_distinct(self):
        r = evaluate_admission(self.budget, self.plan, self.now)
        self.assertTrue(r["gpu_rate_basis"]["automatic_h100_h200_upgrade_billed_at_h100"])
        self.assertTrue(r["gpu_rate_basis"]["maximum_rate_is_extra_conservative_not_upgrade_billing_rule"])
        self.assertEqual(r["timeout_contract"]["per_job_total_wall_seconds"], [420, 2100, 2100])
        self.assertIn("actual_sdk_timeout_retry_stop_capabilities_unverified", r["reasons"])
        self.assertIn("parent_total_wall_and_independent_remote_stop_unverified", r["reasons"])
