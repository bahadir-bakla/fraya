"""Synthetic temporary ledgers and mock process witnesses only; no cloud calls.

Grant dictionaries are unit doubles, never saved outside temp fixtures, never
reported as actual parent authority, and never usable by the disabled live runner.
"""
import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

import modal_budget_v4 as budget
import modal_runner_v4 as runner


NOW = budget.utc_seconds("2026-10-11T03:00:00Z")
EXPIRES = "2026-10-11T06:13:01Z"
APP = "ap-" + "a" * 22
SCHEMA = {"known": True, "version": runner.SDK_VERSION, "source_sha256": runner.SDK_SCHEMA_FILES,
          "schema_sha256": budget.digest({"version": runner.SDK_VERSION, "source_sha256": runner.SDK_SCHEMA_FILES})}


def listing(state="stopped", tasks="0"):
    return {"app_id": APP, "description": "unit", "state": state, "tasks": tasks, "created_at": None, "stopped_at": None}


class Clock:
    def __init__(self):
        self.wall, self.elapsed = NOW, 0
    def utc(self):
        return self.wall
    def mono(self):
        return self.elapsed
    def advance(self, seconds):
        self.wall += seconds
        self.elapsed += seconds


class FakeProcess:
    def __init__(self, owner):
        self.owner = owner
    def wait(self, timeout):
        self.owner.calls.append(("wait", timeout))
        if self.owner.mode == "watchdog":
            self.owner.clock.advance(timeout + 1)
            raise TimeoutError("unit compute timeout")
        if self.owner.mode == "execution_exception":
            raise RuntimeError("unit wait exception")
        return 0
    def terminate(self, timeout):
        self.owner.calls.append(("terminate", timeout))
        if self.owner.mode == "finally_exception":
            raise RuntimeError("unit terminate exception")
    def kill(self, timeout):
        self.owner.calls.append(("kill", timeout))


class FakeTransport(runner.MockTransport):
    def __init__(self, journal, nonce, clock, mode="ok"):
        self.journal, self.nonce, self.clock, self.mode = journal, nonce, clock, mode
        self.calls = []
    def launch(self, argv, **kwargs):
        self.calls.append(("launch", argv, kwargs))
        if self.mode == "startup_timeout":
            self.clock.advance(241)
        return FakeProcess(self)
    def ids(self, timeout):
        if self.mode == "truncated_ids":
            return b'{"app_id":"ap-'
        row = next(r for r in self.journal.snapshot()["reservations"] if r["nonce"] == self.nonce)
        return budget.encoded({"app_id": APP, "nonce": self.nonce, "owner_fence": row["owner_fence"]})
    def run(self, operation, argv, **kwargs):
        self.calls.append((operation, argv, kwargs))
        if self.mode == "finally_exception":
            raise RuntimeError("unit stop exception")
        if operation != "list":
            return {"exit_code": 0}
        rows = [listing()]
        if self.mode == "duplicate_listing":
            rows.append(listing("running", "1"))
        raw = budget.encoded(rows)
        row = next(r for r in self.journal.snapshot()["reservations"] if r["nonce"] == self.nonce)
        proof = budget.encoded({"app_id": APP, "workspace_identity_evidence_sha256": row["immutable_grant"]["workspace_identity_evidence_sha256"],
                              "all_related_resources_stopped": True, "observed_utc": self.clock.utc(), "listing_sha256": budget.sha(raw)})
        out = {"raw": raw, "observed_utc": self.clock.utc()}
        if self.mode != "cli_zero_only":
            out.update(provider_stop_raw=proof, trusted_provider_stop_sha256=budget.sha(proof))
        return out


class ModalHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="modal-v4-unit-")
        self.root = Path(self.temp.name)
        self.journal = budget.ParentJournal(self.root / "parent-journal.json", "unit-parent", "unit-work")
        self.snapshot = {"profile": budget.PROFILE, "target_usd": 30, "hard_cap_usd": 35,
                         "cloud_stop_utc": budget.HARD_STOP, "actual_task_cost_verified": True,
                         "actual_task_cost_usd": 0, "reservations": [], "invocations": []}
        raw = budget.encoded(self.snapshot)
        self.journal.initialize(raw, budget.sha(raw))
        stage = self.root / "stage"
        stage.mkdir()
        self.software = {"python_path": str(runner.SYSTEM_PYTHON), "python_sha256": runner.SYSTEM_PYTHON_SHA256,
                         "software_root": str(stage), "cwd": str(stage), "approved_path": "C:\\Windows\\System32",
                         "files": {}}
        for name in runner.SOFTWARE_NAMES:
            raw = (Path(__file__).parent / name).read_bytes()
            (stage / name).write_bytes(raw)
            self.software["files"][name] = budget.sha(raw)
        self.resources = {"gpu_count": 1, "max_containers": 1, "gpu_rate_micro_per_second": 1000,
                          "gpu_billable_seconds_max": 30, "cpu_rate_micro_per_core_second": 100,
                          "cpu_millicores_max": 1000, "cpu_billable_seconds_max": 300,
                          "ram_rate_micro_per_gib_second": 10, "memory_mib_max": 1024,
                          "ram_billable_seconds_max": 300, "disk_rate_micro_per_gib_second": 1,
                          "disk_gib_max": 2, "disk_billable_seconds_max": 300,
                          "build_bound_micro_usd": 100000, "storage_bound_micro_usd": 100000,
                          "egress_bound_micro_usd": 100000, "other_bound_micro_usd": 100000}
        self.environment = {"USERPROFILE": "C:\\Users\\unit", "APPDATA": "C:\\Users\\unit\\AppData\\Roaming",
                            "LOCALAPPDATA": "C:\\Users\\unit\\AppData\\Local", "SYSTEMROOT": "C:\\Windows",
                            "TEMP": str(self.root), "MODAL_TOKEN_ID": "unit-secret", "MODAL_TOKEN_SECRET": "unit-secret",
                            "FREYA_KEY": "unit-secret", "ZEP_KEY": "unit-secret", "LLM_KEY": "unit-secret",
                            "OTHER_UNRELATED_SECRET": "unit-secret", "PYTHONPATH": str(self.root), "PYTHONHOME": str(self.root),
                            "HF_TOKEN": "unit-secret", "HTTP_PROXY": "unit-secret", "PATH": "unapproved"}
    def tearDown(self):
        self.temp.cleanup()

    def grant_double(self, index=1, amount=1_000_000, software=None):
        sources = [{"path": "unit-reviewed-train.json", "sha256": "b" * 64, "split": "train", "reviewed": True},
                   {"path": "unit-reviewed-dev.json", "sha256": "c" * 64, "split": "dev", "reviewed": True}]
        payload = budget.encoded({"schema_version": "modal_train_payload.v4", "source_allowlist": sources, "holdout_allowed": False})
        grant = {"schema_version": "parent_modal_gpu_grant.v4", "issuer": "parent", "gpu_authorized": True,
                 "cloud_authorized": True, "profile": budget.PROFILE, "nonce": f"{index:032x}",
                 "work_id": "unit-work", "coordinator_id": "unit-parent", "reservation_id": f"unit-res-{index}",
                 "parent_journal_path": str(self.journal.path), "experiment_id": f"unit-experiment-{index}",
                 "invocation_id": f"unit-invoke-{index}", "qualification_benefit": "unit-only mock benefit",
                 "reviewed_train_dev_source_allowlist": sources, "payload_source_allowlist": sources, "holdout_allowed": False,
                 "payload_sha256": budget.sha(payload), "software_manifest_sha256": budget.digest(software or self.software),
                 "resource_manifest_sha256": budget.digest(self.resources), "rate_evidence_sha256": "d" * 64,
                 "reviewed_data_admission_sha256": "e" * 64, "workspace_identity_evidence_sha256": "f" * 64,
                 "independent_watchdog_evidence_sha256": "a" * 64, "provider_bounds_verified": True,
                 "account_identity_verified": True, "independent_watchdog_armed": True, "gpu_count": 1,
                 "max_containers": 1, "min_containers": 0, "retries": 0, "services": False, "cron": False,
                 "expires_utc": EXPIRES, "reservation_micro_usd": amount}
        raw = budget.encoded(grant)
        evidence = {k: grant[k] for k in ("software_manifest_sha256", "rate_evidence_sha256", "reviewed_data_admission_sha256",
                    "workspace_identity_evidence_sha256", "independent_watchdog_evidence_sha256")}
        return grant, raw, budget.sha(raw), payload, evidence

    def reserve(self, index=1, amount=1_000_000):
        grant, raw, hashed, payload, evidence = self.grant_double(index, amount)
        self.journal.reserve(raw, hashed, payload, self.resources, evidence, NOW)
        self.journal.admit_unlaunched(grant["nonce"], hashed)
        return grant, hashed

    def receipt(self, grant, hashed):
        w = runner.Watchdog(30, EXPIRES, lambda: NOW, lambda: 0)
        return self.journal.start_once(grant["nonce"], hashed, w.deadlines, NOW)

    def simulate(self, mode="ok"):
        grant, hashed = self.reserve()
        clock = Clock()
        transport = FakeTransport(self.journal, grant["nonce"], clock, mode)
        stop = runner.supervise_mock(self.journal, grant["nonce"], hashed, self.software, self.environment,
                                    transport, 30, EXPIRES, SCHEMA, clock.utc, clock.mono)
        return stop, transport

    def test_production_remains_disabled_and_cpu_grant_never_gpu_permission(self):
        with self.assertRaisesRegex(budget.Denied, "REMOTE_LAUNCH_DISABLED_ZERO_SPEND"):
            runner.supervise_parent()
        raw = budget.encoded({"schema_version": "parent_cpu_engineering_authorization.v4.1", "gpu_authorized": False})
        with self.assertRaisesRegex(budget.Denied, "separate_explicit_gpu_cloud_grant_required"):
            budget.exact_parent_grant(raw, budget.sha(raw))
        with self.assertRaises(budget.Denied):
            budget.exact_parent_grant(raw, None)

    def test_duplicate_and_concurrent_reserve_single_commit(self):
        grant, raw, hashed, payload, evidence = self.grant_double()
        barrier = Barrier(2)
        def attempt():
            other = budget.ParentJournal(self.journal.path, "unit-parent", "unit-work")
            barrier.wait()
            try:
                other.reserve(raw, hashed, payload, self.resources, evidence, NOW)
                return True
            except budget.Denied:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(lambda _: attempt(), range(2))), [False, True])
        self.assertEqual(len(self.journal.snapshot()["reservations"]), 1)
        with self.assertRaisesRegex(budget.Denied, "nonce_or_reservation_replay"):
            self.journal.reserve(raw, hashed, payload, self.resources, evidence, NOW)

    def test_consumed_nonce_and_child_claim_cannot_replay(self):
        grant, hashed = self.reserve()
        receipt = self.receipt(grant, hashed)
        with self.assertRaisesRegex(budget.Denied, "single_use"):
            self.receipt(grant, hashed)
        self.journal.claim_child_once(receipt)
        self.assertEqual(self.journal.snapshot()["reservations"][0]["status"], "launch_claimed")
        with self.assertRaisesRegex(budget.Denied, "one_atomic_child_claim"):
            self.journal.claim_child_once(receipt)
        # Mutable journal events do not invalidate immutable launch receipt.
        self.assertEqual(budget.worker_read_receipt(self.journal.path, receipt)["nonce"], grant["nonce"])

    def test_another_active_or_unknown_job_blocks_start(self):
        a, ha = self.reserve(1)
        b, hb = self.reserve(2)
        receipt = self.receipt(a, ha)
        with self.assertRaisesRegex(budget.Denied, "another_active"):
            self.receipt(b, hb)
        self.journal.finalize(receipt, {"remote_stop_verified": False})
        with self.assertRaisesRegex(budget.Denied, "another_active"):
            self.receipt(b, hb)
        self.assertEqual(self.journal.exposure(self.journal.snapshot())[1], 2_000_000)

    def test_fourth_attempt_denied_even_after_stopped_or_failed_starts(self):
        for index in range(1, 4):
            grant, hashed = self.reserve(index)
            receipt = self.receipt(grant, hashed)
            self.journal.claim_child_once(receipt)
            self.journal.record_ids(receipt, {"app_id": APP})
            self.journal.finalize(receipt, {"remote_stop_verified": True, "app_id": APP})
        self.assertEqual(self.journal.snapshot()["start_count"], 3)
        with self.assertRaisesRegex(budget.Denied, "three_task_invocations_maximum"):
            self.reserve(4)

    def test_shared_ten_dollar_envelope_not_three_times_ten(self):
        self.reserve(1, 6_000_000)
        with self.assertRaisesRegex(budget.Denied, "first_experiment_total_ten"):
            self.reserve(2, 6_000_000)
        self.reserve(2, 4_000_000)
        self.assertEqual(self.journal.exposure(self.journal.snapshot())[1], 10_000_000)

    def test_existing_aggregate_cost_prevents_global_overspend(self):
        journal = budget.ParentJournal(self.root / "global.json", "unit-parent", "unit-work")
        snapshot = {**self.snapshot, "actual_task_cost_usd": 29}
        raw = budget.encoded(snapshot)
        journal.initialize(raw, budget.sha(raw))
        grant, raw, hashed, payload, evidence = self.grant_double(amount=2_000_000)
        grant["parent_journal_path"] = str(journal.path)
        raw = budget.encoded(grant)
        hashed = budget.sha(raw)
        with self.assertRaisesRegex(budget.Denied, "aggregate_task_budget_overspend"):
            journal.reserve(raw, hashed, payload, self.resources, evidence, NOW)

    def test_cost_categories_integer_ceiling_and_nonfinite_denial(self):
        self.assertEqual(budget.conservative_cost_bound(self.resources), 463600)
        for value in (-1, .5, float("nan"), True):
            resources = {**self.resources, "build_bound_micro_usd": value}
            with self.assertRaises(budget.Denied):
                budget.conservative_cost_bound(resources)

    def test_read_only_production_and_unsynchronized_journal_required(self):
        with self.assertRaisesRegex(budget.Denied, "production_aggregate_is_read_only"):
            budget.ParentJournal(budget.PRODUCTION_LEDGER, "unit-parent", "unit-work")
        with self.assertRaisesRegex(budget.Denied, "unsynchronized_local"):
            budget.ParentJournal(self.root / "OneDrive" / "journal.json", "unit-parent", "unit-work")

    def test_launch_and_cancel_strip_unrelated_secrets_and_isolate_imports(self):
        stop, transport = self.simulate()
        self.assertEqual(stop["status"], "finished")
        for call in transport.calls:
            if call[0] in ("launch", "cancel", "app_stop", "list"):
                argv, kwargs = call[1:]
                self.assertTrue(Path(argv[0]).is_absolute())
                self.assertEqual(argv[1:4], ["-I", "-S", "-B"])
                env = kwargs["env"]
                self.assertEqual(set(env), (set(self.environment) & runner.OS_ENV_ALLOWLIST) | {"PATH", "MODAL_PROFILE"})
                self.assertEqual(env["MODAL_PROFILE"], budget.PROFILE)
                self.assertEqual(env["PATH"], self.software["approved_path"])
                self.assertLessEqual(kwargs["timeout"], 240)
        self.assertFalse(stop["reservation_release_allowed"])

    def test_local_import_shadow_and_modified_software_denied(self):
        shadow = Path(self.software["cwd"]) / "modal.py"
        shadow.write_text("raise AssertionError('must not import')", encoding="utf-8")
        with self.assertRaisesRegex(budget.Denied, "local_import_shadow"):
            runner.isolated_command(self.software, "launch")
        shadow.unlink()
        (Path(self.software["cwd"]) / "modal_budget_v4.py").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(budget.Denied, "software_file_hash"):
            runner.isolated_command(self.software, "cancel", APP)

    def test_watchdog_total_startup_execution_shutdown_and_wall_rollback(self):
        clock = Clock()
        watchdog = runner.Watchdog(30, EXPIRES, clock.utc, clock.mono)
        clock.advance(331)
        clock.wall -= 10000
        with self.assertRaisesRegex(budget.Denied, "watchdog_expired"):
            watchdog.remaining("shutdown", 15)
        stop, _ = self.simulate("startup_timeout")
        self.assertEqual(stop["status"], "unknown")
        self.assertIsNotNone(self.journal.snapshot()["reservations"][0]["stop_record"])

    def test_absolute_hard_stop_cannot_be_extended(self):
        clock = Clock()
        clock.wall = budget.utc_seconds(budget.HARD_STOP) - 61
        w = runner.Watchdog(1800, EXPIRES, clock.utc, clock.mono)
        self.assertEqual(w.deadlines["hard_utc"], budget.utc_seconds(budget.HARD_STOP))
        clock.advance(62)
        with self.assertRaises(budget.Denied):
            w.remaining("shutdown", 1)

    def test_truncated_ids_and_finally_exception_persist_unknown(self):
        stop, transport = self.simulate("truncated_ids")
        self.assertEqual(stop["status"], "unknown")
        self.assertFalse(any(call[0] == "cancel" for call in transport.calls))
        self.assertIsNotNone(self.journal.snapshot()["reservations"][0]["stop_record"])

    def test_finally_exception_still_persists_stop_record(self):
        stop, _ = self.simulate("finally_exception")
        self.assertEqual(stop["status"], "unknown")
        self.assertTrue(any(e.startswith("local_terminate:") for e in stop["errors"]))
        self.assertIsNotNone(self.journal.snapshot()["reservations"][0]["stop_record"])

    def test_conflicting_duplicate_listing_and_exit_zero_are_unknown(self):
        for rows in ([listing(), listing("running", "1")], [listing(), listing()]):
            with self.assertRaisesRegex(budget.Denied, "duplicate_or_conflicting"):
                runner.parse_stopped_listing(budget.encoded(rows), APP, SCHEMA)
        self.assertFalse(runner.verify_remote_stop(budget.encoded([listing()]), APP, SCHEMA, "f" * 64, NOW, NOW))
        stop, _ = self.simulate("cli_zero_only")
        self.assertEqual(stop["status"], "unknown")

    def test_unknown_listing_schema_and_stale_provider_proof_fail_closed(self):
        with self.assertRaisesRegex(budget.Denied, "unknown_listing_schema"):
            runner.parse_stopped_listing(budget.encoded([listing()]), APP, {"known": False})
        self.assertFalse(runner.verify_remote_stop(budget.encoded([listing()]), APP, SCHEMA, "f" * 64, NOW - 20, NOW))

    def test_holdout_and_reused_snapshot_reset_denied(self):
        grant, _, _, _, _ = self.grant_double()
        grant["payload_source_allowlist"][0]["split"] = "holdout"
        raw = budget.encoded(grant)
        with self.assertRaises(budget.Denied):
            budget.exact_parent_grant(raw, budget.sha(raw))
        raw = budget.encoded(self.snapshot)
        with self.assertRaisesRegex(budget.Denied, "already_exists_no_reset"):
            self.journal.initialize(raw, budget.sha(raw))

    def test_disk_failure_reports_unknown_and_keeps_claim_active(self):
        with patch.object(self.journal, "finalize", side_effect=OSError("unit disk error")):
            stop, _ = self.simulate()
        self.assertEqual(stop["status"], "unknown")
        self.assertEqual(stop["journal_persistence_failed"], "OSError")
        self.assertEqual(self.journal.snapshot()["reservations"][0]["status"], "launch_claimed")

    def test_concurrent_child_claim_consumed_once(self):
        grant, hashed = self.reserve()
        receipt = self.receipt(grant, hashed)
        barrier = Barrier(2)
        def claim():
            journal = budget.ParentJournal(self.journal.path, "unit-parent", "unit-work")
            barrier.wait()
            try:
                journal.claim_child_once(receipt)
                return True
            except budget.Denied:
                return False
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertEqual(sorted(executor.map(lambda _: claim(), range(2))), [False, True])

    def test_grant_cannot_migrate_to_new_per_worker_budget(self):
        other = budget.ParentJournal(self.root / "other-worker.json", "unit-parent", "unit-work")
        raw = budget.encoded(self.snapshot)
        other.initialize(raw, budget.sha(raw))
        grant, raw, hashed, payload, evidence = self.grant_double()
        with self.assertRaisesRegex(budget.Denied, "one_parent_authoritative_journal_path"):
            other.reserve(raw, hashed, payload, self.resources, evidence, NOW)

    def test_compute_timeout_counts_attempt_and_verified_stop_keeps_hold(self):
        stop, _ = self.simulate("watchdog")
        self.assertEqual(stop["status"], "stopped")
        value = self.journal.snapshot()
        self.assertEqual(value["start_count"], 1)
        self.assertEqual(self.journal.exposure(value)[1], 1_000_000)
        nonce = value["reservations"][0]["nonce"]
        proof = budget.encoded({"nonce": nonce, "actual_micro_usd": 250_000, "final_attribution_verified": True})
        self.journal.settle(nonce, proof, budget.sha(proof))
        self.assertEqual(self.journal.exposure(self.journal.snapshot())[1], 250_000)
        self.assertEqual(self.journal.snapshot()["start_count"], 1)

    def test_immutable_grant_and_actual_payload_cannot_be_changed(self):
        grant, raw, hashed, payload, evidence = self.grant_double()
        changed = budget.encoded({"schema_version": "modal_train_payload.v4", "source_allowlist": [], "holdout_allowed": False})
        grant["payload_sha256"] = budget.sha(changed)
        raw = budget.encoded(grant)
        with self.assertRaisesRegex(budget.Denied, "actual_payload_exact_reviewed"):
            self.journal.reserve(raw, budget.sha(raw), changed, self.resources, evidence, NOW)
        grant, hashed = self.reserve()
        value = self.journal.snapshot()
        value["reservations"][0]["immutable_grant"]["gpu_count"] = 2
        budget.atomic_write(self.journal.path, value)
        with self.assertRaisesRegex(budget.Denied, "immutable_grant_changed"):
            self.journal.snapshot()


if __name__ == "__main__":
    unittest.main()
