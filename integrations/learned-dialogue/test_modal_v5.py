"""Pure CPU synthetic witnesses; fixture hashes are NOT parent/provider authority.

No network, subprocess, credentials, production journal or training operations.
"""
import base64
import copy
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import modal_budget_v5 as b
import modal_runner_v5 as r


class Clock:
    def __init__(self):
        self.wall = b.utc_seconds(b.HARD_STOP) - 3600
        self.mono = 1000.0
    def utc(self):
        return self.wall
    def monotonic(self):
        return self.mono
    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds


class Fixture:
    def __init__(self, root, base=0):
        self.root = Path(root)
        self.clock = Clock()
        self.journal = b.ParentJournal(self.root / 'synthetic-journal.json', 'unit-parent', 'unit-work')
        snapshot = b.encoded({'profile': b.PROFILE, 'target_usd': 30, 'hard_cap_usd': 35,
                             'cloud_stop_utc': b.HARD_STOP, 'actual_task_cost_verified': True,
                             'actual_task_cost_usd': base, 'reservations': [], 'invocations': []})
        self.journal.initialize(snapshot, b.sha(snapshot))
        self.resources = {'gpu_count': 1, 'max_containers': 1, 'gpu_rate_micro_per_second': 1,
            'gpu_billable_seconds_max': 1, 'cpu_rate_micro_per_core_second': 0, 'cpu_millicores_max': 1,
            'cpu_billable_seconds_max': 1, 'ram_rate_micro_per_gib_second': 0, 'memory_mib_max': 1,
            'ram_billable_seconds_max': 1, 'disk_rate_micro_per_gib_second': 0, 'disk_gib_max': 0,
            'disk_billable_seconds_max': 0, 'build_bound_micro_usd': 0, 'storage_bound_micro_usd': 0,
            'egress_bound_micro_usd': 0, 'other_bound_micro_usd': 0}
        self.hashes = {}
    def reserve(self, number, amount=b.MICRO, software_hash='1' * 64, admit=True):
        # Descriptors only: no source data is created or read.
        sources = [{'path': 'synthetic/train-only', 'sha256': '2' * 64, 'reviewed': True, 'split': 'train'}]
        payload = b.encoded({'schema_version': 'modal_train_payload.v5', 'source_allowlist': sources, 'holdout_allowed': False})
        nonce = f'{number:032x}'
        grant = {'schema_version': 'parent_modal_gpu_grant.v5', 'issuer': 'parent', 'gpu_authorized': True,
            'cloud_authorized': True, 'profile': b.PROFILE, 'nonce': nonce, 'qualification_benefit': 'synthetic unit double',
            'reviewed_train_dev_source_allowlist': sources, 'payload_source_allowlist': sources, 'holdout_allowed': False,
            'payload_sha256': b.sha(payload), 'software_manifest_sha256': software_hash,
            'resource_manifest_sha256': b.digest(self.resources), 'rate_evidence_sha256': '3' * 64,
            'reviewed_data_admission_sha256': '4' * 64, 'workspace_identity_evidence_sha256': '5' * 64,
            'independent_watchdog_evidence_sha256': '6' * 64, 'provider_bounds_verified': True,
            'account_identity_verified': True, 'independent_watchdog_armed': True, 'gpu_count': 1,
            'max_containers': 1, 'min_containers': 0, 'retries': 0, 'services': False, 'cron': False,
            'work_id': 'unit-work', 'coordinator_id': 'unit-parent', 'parent_journal_path': str(self.journal.path),
            'expires_utc': b.HARD_STOP, 'reservation_micro_usd': amount,
            'reservation_id': f'unit-reservation-{number}', 'invocation_id': f'unit-invocation-{number}',
            'experiment_id': f'distinct-unit-experiment-{number}'}
        evidence = {key: grant[key] for key in ('software_manifest_sha256', 'rate_evidence_sha256',
            'reviewed_data_admission_sha256', 'workspace_identity_evidence_sha256', 'independent_watchdog_evidence_sha256')}
        raw = b.encoded(grant)
        self.hashes[nonce] = b.sha(raw)
        self.journal.reserve(raw, b.sha(raw), payload, self.resources, evidence, self.clock.utc())
        if admit:
            self.journal.admit_unlaunched(nonce, b.sha(raw))
        return nonce
    def watchdog(self):
        return r.Watchdog(30, b.HARD_STOP, self.clock.utc, self.clock.monotonic)
    def start(self, nonce):
        watch = self.watchdog()
        return self.journal.start_once(nonce, self.hashes[nonce], watch.deadlines, self.clock.utc(),
            deadline=watch.journal_deadline('startup', 5))
    def finish(self, nonce):
        receipt = self.start(nonce)
        self.journal.claim_child_once(receipt)
        app = 'ap-' + 'a' * 22
        self.journal.record_ids(receipt, {'app_id': app})
        # This is a synthetic parent boundary, never authenticated provider proof.
        self.journal.finalize(receipt, {'app_id': app, 'remote_stop_verified': True})
        return receipt
    def settle(self, nonce, amount):
        billing = b.encoded({'nonce': nonce, 'final_attribution_verified': True, 'actual_micro_usd': amount})
        self.journal.settle(nonce, billing, b.sha(billing))
    def stage(self):
        stage = self.root / 'stage'
        stage.mkdir()
        for name in r.SOFTWARE_NAMES:
            (stage / name).write_bytes(('unit file ' + name).encode())
        interpreter = self.root / 'synthetic-python.exe'
        interpreter.write_bytes(b'never executable')
        manifest = {'python_path': str(interpreter), 'python_sha256': b.sha(interpreter.read_bytes()),
            'software_root': str(stage), 'cwd': str(stage), 'approved_path': 'synthetic-explicit-path',
            'files': {name: b.sha((stage / name).read_bytes()) for name in r.SOFTWARE_NAMES}}
        return interpreter, manifest


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='modal-v5-test-')
        self.addCleanup(self.temp.cleanup)
        self.f = Fixture(self.temp.name)
    def assert_start_blocked(self, nonce):
        count = self.f.journal.snapshot()['start_count']
        with self.assertRaisesRegex(b.Denied, 'budget_hold_external_reconciliation'):
            self.f.start(nonce)
        self.assertEqual(self.f.journal.snapshot()['start_count'], count)
        self.assertEqual(self.f.journal.snapshot()['reservations'][-1]['status'], 'admitted_unlaunched')
    def test_exact_native_experiment_12_settlement(self):
        a = self.f.reserve(1)
        second = self.f.reserve(2)
        self.f.finish(a)
        self.f.settle(a, 11 * b.MICRO)
        self.assertEqual(b.ParentJournal.exposure(self.f.journal.snapshot()), (12 * b.MICRO, 12 * b.MICRO))
        self.assert_start_blocked(second)
        guard = self.f.journal.snapshot()["budget_guard"]
        self.assertEqual(guard["incurred_micro_usd"], 11 * b.MICRO)
        self.assertEqual(guard["held_micro_usd"], b.MICRO)
        self.assertIn("shared_experiment_ten_dollar_ceiling", guard["violations"])
    def test_exact_native_global_36_5_settlement(self):
        self.temp.cleanup()
        self.temp = tempfile.TemporaryDirectory(prefix='modal-v5-test-')
        self.addCleanup(self.temp.cleanup)
        self.f = Fixture(self.temp.name, base=29)
        a = self.f.reserve(1, b.MICRO // 2)
        second = self.f.reserve(2, b.MICRO // 2)
        self.f.finish(a)
        self.f.settle(a, 7 * b.MICRO)
        self.assertEqual(b.ParentJournal.exposure(self.f.journal.snapshot()), (36_500_000, 7_500_000))
        self.assert_start_blocked(second)
        reasons = self.f.journal.snapshot()['ceiling_violations']
        self.assertIn('global_thirty_five_dollar_hard_cap', reasons)
        self.assertIn('global_thirty_dollar_launch_ceiling', reasons)
    def test_transactional_start_independent_global_ceiling_with_coherent_rows(self):
        nonce = self.f.reserve(1, 2 * b.MICRO)
        value = self.f.journal.snapshot()
        # Synthetic other-task incurred-cost update, no row exceeds its ceiling.
        value['base_verified_cost_micro_usd'] = 29 * b.MICRO
        b.atomic_write(self.f.journal.path, value)
        self.assert_start_blocked(nonce)
        violations = self.f.journal.snapshot()['budget_guard']['violations']
        self.assertIn('global_thirty_dollar_launch_ceiling', violations)
        self.assertFalse(any(x.startswith('actual_over_reservation') for x in violations))
    def test_exact_ten_and_thirty_boundaries_start(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root, 20)
            nonce = f.reserve(1, 10 * b.MICRO)
            self.assertEqual(b.ParentJournal.exposure(f.journal.snapshot()), (30 * b.MICRO, 10 * b.MICRO))
            self.assertEqual(f.start(nonce)['ordinal'], 1)
    def test_child_claim_recomputes_budget_after_start(self):
        nonce = self.f.reserve(1)
        receipt = self.f.start(nonce)
        value = self.f.journal.snapshot()
        value['base_verified_cost_micro_usd'] = 35 * b.MICRO
        b.atomic_write(self.f.journal.path, value)
        with self.assertRaisesRegex(b.Denied, 'budget_hold_external_reconciliation'):
            self.f.journal.claim_child_once(receipt)
        self.assertEqual(self.f.journal.snapshot()['reservations'][0]['status'], 'starting')
    def test_shared_envelope_accounts_partial_unknown_incurring_cost(self):
        nonce = self.f.reserve(1, 2 * b.MICRO)
        value = self.f.journal.snapshot()
        value['reservations'][0]['actual_micro_usd'] = b.MICRO
        guard = b.ParentJournal.accounting(value)
        self.assertEqual((guard['incurred_micro_usd'], guard['held_micro_usd']), (b.MICRO, b.MICRO))
        self.assertEqual(guard['shared_experiment_exposure_micro_usd'], 2 * b.MICRO)
        value['reservations'][0]['actual_micro_usd'] = 3 * b.MICRO
        guard = b.ParentJournal.accounting(value)
        self.assertEqual(guard['global_exposure_micro_usd'], 3 * b.MICRO)
        self.assertTrue(any(x.startswith('actual_over_reservation') for x in guard['violations']))
    def test_worker_readonly_check_rejects_budget_violation(self):
        nonce = self.f.reserve(1)
        receipt = self.f.start(nonce)
        self.f.journal.claim_child_once(receipt)
        self.assertEqual(b.worker_read_receipt(self.f.journal.path, receipt)['nonce'], nonce)
        value = self.f.journal.snapshot()
        value['budget_breached'] = True
        b.atomic_write(self.f.journal.path, value)
        with self.assertRaisesRegex(b.Denied, 'worker_budget_hold'):
            b.worker_read_receipt(self.f.journal.path, receipt)
    def test_negative_control_coherent_reserved_start(self):
        first = self.f.reserve(1, 2 * b.MICRO)
        second = self.f.reserve(2, 2 * b.MICRO)
        self.f.finish(first)
        self.f.settle(first, b.MICRO)
        receipt = self.f.start(second)
        self.assertEqual(receipt['ordinal'], 2)
        self.assertEqual(b.ParentJournal.exposure(self.f.journal.snapshot()), (3 * b.MICRO, 3 * b.MICRO))
    def test_actual_over_reservation_below_all_dollar_caps(self):
        first = self.f.reserve(1)
        second = self.f.reserve(2)
        self.f.finish(first)
        self.f.settle(first, 1_100_000)
        self.assert_start_blocked(second)
    def test_start_recomputes_even_if_breach_flags_erased(self):
        first = self.f.reserve(1)
        second = self.f.reserve(2)
        self.f.finish(first)
        self.f.settle(first, 11 * b.MICRO)
        value = self.f.journal.snapshot()
        value['budget_breached'] = False
        value['ceiling_violations'] = []
        b.atomic_write(self.f.journal.path, value)  # Local corruption witness only.
        self.assert_start_blocked(second)
    def test_latched_flag_without_current_excess_stays_blocked(self):
        nonce = self.f.reserve(1)
        value = self.f.journal.snapshot()
        value['budget_breached'] = True
        b.atomic_write(self.f.journal.path, value)
        self.assert_start_blocked(nonce)
    def test_no_external_reconciliation_by_boolean_reset(self):
        nonce = self.f.reserve(1)
        value = self.f.journal.snapshot()
        value['ceiling_violations'] = ['provider_bound_violation_requires_external_reconciliation']
        value['budget_breached'] = False
        b.atomic_write(self.f.journal.path, value)
        self.assert_start_blocked(nonce)
    def test_shared_ten_across_distinct_experiment_ids(self):
        self.f.reserve(1, 6 * b.MICRO)
        with self.assertRaisesRegex(b.Denied, 'ten_dollar'):
            self.f.reserve(2, 5 * b.MICRO)
    def test_global_thirty_launch_ceiling(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root, 29)
            f.reserve(1)
            with self.assertRaisesRegex(b.Denied, 'aggregate_task_budget'):
                f.reserve(2, b.MICRO // 2)
    def test_unknown_keeps_full_hold_and_global_slot(self):
        first = self.f.reserve(1)
        second = self.f.reserve(2)
        receipt = self.f.start(first)
        self.f.journal.finalize(receipt, {'remote_stop_verified': False})
        self.assertEqual(b.ParentJournal.exposure(self.f.journal.snapshot()), (2 * b.MICRO, 2 * b.MICRO))
        with self.assertRaisesRegex(b.Denied, 'active_or_unknown'):
            self.f.start(second)
    def test_three_lifetime_attempts_not_refunded(self):
        for number in range(1, 4):
            nonce = self.f.reserve(number)
            self.f.finish(nonce)
            self.f.settle(nonce, 0)
        self.assertEqual(self.f.journal.snapshot()['start_count'], 3)
        with self.assertRaisesRegex(b.Denied, 'three_task_invocations'):
            self.f.reserve(4)
    def test_nonce_start_and_child_claim_single_use(self):
        nonce = self.f.reserve(1)
        with self.assertRaisesRegex(b.Denied, 'replay'):
            self.f.reserve(1)
        receipt = self.f.start(nonce)
        with self.assertRaisesRegex(b.Denied, 'single_use'):
            self.f.start(nonce)
        self.f.journal.claim_child_once(receipt)
        with self.assertRaisesRegex(b.Denied, 'one_atomic_child_claim'):
            self.f.journal.claim_child_once(receipt)
    def test_os_lock_concurrent_child_claim(self):
        receipt = self.f.start(self.f.reserve(1))
        def claim(_):
            try:
                self.f.journal.claim_child_once(receipt)
                return 'claimed'
            except b.Denied:
                return 'denied'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(claim, range(2))), ['claimed', 'denied'])
    def test_same_instance_rollback_rejected(self):
        old = self.f.journal.path.read_bytes()
        self.f.reserve(1)
        self.f.journal.path.write_bytes(old)
        with self.assertRaisesRegex(b.Denied, 'rollback'):
            self.f.journal.snapshot()
    def test_restart_can_read_coherent_rollback_but_cannot_start(self):
        nonce = self.f.reserve(1)
        old = self.f.journal.path.read_bytes()
        self.f.start(nonce)
        self.f.journal.path.write_bytes(old)
        restarted = b.ParentJournal(self.f.journal.path, 'unit-parent', 'unit-work')
        self.assertEqual(restarted.snapshot()['start_count'], 0)  # Honest local-file limitation.
        watch = self.f.watchdog()
        with self.assertRaisesRegex(b.Denied, 'authenticated_external_checkpoint'):
            restarted.start_once(nonce, self.f.hashes[nonce], watch.deadlines, self.f.clock.utc())
    def test_cpu_authority_not_gpu_and_live_entrypoints_reject(self):
        raw = b.encoded({'issuer': 'parent', 'cpu_authorized': True})
        with self.assertRaises(b.Denied):
            b.exact_parent_grant(raw, b.sha(raw))
        with self.assertRaises(b.Denied):
            r.supervise_parent(raw, b.sha(raw))
        with self.assertRaises(b.Denied):
            r.child_main(['launch'])
        self.assertFalse(r.REMOTE_LAUNCH_ENABLED)
    def test_production_named_ledger_rejected_without_read(self):
        with self.assertRaisesRegex(b.Denied, 'production_aggregate'):
            b.ParentJournal(Path(self.temp.name) / 'modal-budget.json', 'unit-parent', 'unit-work')


class DeadlineSecurityTests(unittest.TestCase):
    def test_explicit_shutdown_allocation(self):
        c = Clock()
        w = r.Watchdog(30, b.HARD_STOP, c.utc, c.monotonic)
        self.assertEqual(w.deadlines['hard_utc'] - w.deadlines['cancel_utc'], 60)
        self.assertEqual(w.deadlines['finalization_reserved_seconds'], 6)
        self.assertEqual(w.deadlines['slack_reserved_seconds'], 10)
        self.assertEqual(sum(r.SHUTDOWN_ALLOCATION_SECONDS.values()), 60)
        c.advance(314)  # Total330, transport cutoff314, finalize cutoff320.
        with self.assertRaises(b.Denied):
            w.remaining('shutdown', 1)
        self.assertEqual(w.journal_deadline('finalize', 6).remaining(99), 6)
        c.advance(6)
        with self.assertRaises(b.Denied):
            w.journal_deadline('finalize', 6)
    def test_monotonic_clock_prevents_wall_rollback_extension(self):
        c = Clock()
        w = r.Watchdog(30, b.HARD_STOP, c.utc, c.monotonic)
        c.mono += 400
        c.wall -= 400
        with self.assertRaises(b.Denied):
            w.remaining('finalize', 6)
    def test_fallback_deadline_does_not_extend_absolute_cutoff(self):
        with patch.object(b.time, 'time', side_effect=[10, 11]):
            deadline = b.absolute_utc_deadline(14, maximum=5)
        self.assertEqual(deadline.utc_end, 14)
    def test_journal_deadline_never_extends_original_monotonic_cutoff(self):
        c = Clock()
        w = r.Watchdog(30, b.HARD_STOP, c.utc, c.monotonic)
        c.advance(313)
        # Time advances between remaining() and constructing the Deadline.
        def moving_mono():
            c.mono += .1
            return c.mono
        w.mono = moving_mono
        deadline = w.journal_deadline('shutdown', 4)
        self.assertLessEqual(deadline.mono_end, w.start_mono + 314)
        self.assertLessEqual(deadline.utc_end, w.start_utc + 314)
    def test_direct_child_claim_after_startup_deadline_rejects(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            receipt = f.start(f.reserve(1))
            with patch.object(b.time, 'time', return_value=receipt['deadlines']['startup_utc'] + 1):
                with self.assertRaisesRegex(b.Denied, 'absolute_journal_deadline'):
                    f.journal.claim_child_once(receipt)
            self.assertEqual(f.journal.snapshot()['reservations'][0]['status'], 'starting')
    def test_expired_journal_deadline_does_not_mutate(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            before = f.journal.path.read_bytes()
            expired = b.Deadline(f.clock.wall, f.clock.mono, f.clock.utc, f.clock.monotonic)
            with self.assertRaisesRegex(b.Denied, 'absolute_journal_deadline'):
                f.journal.snapshot(deadline=expired)
            self.assertEqual(before, f.journal.path.read_bytes())
    def test_contended_windows_lock_uses_remaining_absolute_deadline(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'synthetic-lock-journal'
            with b.file_transaction(path):
                end = b.Deadline(time.time() + .035, time.monotonic() + .035)
                started = time.monotonic()
                def wait():
                    with self.assertRaises(b.Denied):
                        with b.file_transaction(path, timeout_seconds=5, deadline=end):
                            self.fail('contended lock acquired')
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(wait).result(timeout=1)
                self.assertLess(time.monotonic() - started, .5)
    def test_fsync_overrun_detected_without_replace(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'synthetic.json'
            b.atomic_write(path, {'old': True})
            c = Clock()
            end = b.Deadline(c.wall + 1, c.mono + 1, c.utc, c.monotonic)
            with patch.object(b.os, 'fsync', side_effect=lambda _: c.advance(2)):
                with self.assertRaises(b.Denied):
                    b.atomic_write(path, {'new': True}, deadline=end)
            self.assertEqual(b.load(path.read_bytes()), {'old': True})
    def test_replace_overrun_can_persist_before_exception(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            nonce = f.reserve(1)
            watch = f.watchdog()
            end = watch.journal_deadline('startup', 1)
            actual_replace = b.os.replace
            def late_replace(source, target):
                actual_replace(source, target)
                f.clock.advance(2)
            with patch.object(b.os, 'replace', side_effect=late_replace):
                with self.assertRaises(b.Denied):
                    f.journal.start_once(nonce, f.hashes[nonce], watch.deadlines, f.clock.utc(), deadline=end)
            row = f.journal.snapshot()['reservations'][0]
            self.assertEqual(row['status'], 'starting')
            self.assertTrue(row['started'])  # Uncertain commit holds slot/count, no retry.
    def test_unrelated_secrets_removed_from_child_and_cancel_env(self):
        source = {name: 'synthetic-sentinel' for name in ('MODAL_TOKEN_ID', 'MODAL_TOKEN_SECRET', 'FREYA_KEY',
            'ZEP_KEY', 'LLM_TOKEN', 'OTHER_PASSWORD', 'PYTHONPATH', 'PYTHONHOME', 'HTTP_PROXY', 'PATH')}
        source.update({'USERPROFILE': 'synthetic-user', 'APPDATA': 'synthetic-appdata', 'SYSTEMROOT': 'synthetic-windows'})
        result = r.minimal_environment(source, 'synthetic-approved-path')
        self.assertEqual(set(result), {'USERPROFILE', 'APPDATA', 'SYSTEMROOT', 'PATH', 'MODAL_PROFILE'})
        self.assertEqual(result['MODAL_PROFILE'], b.PROFILE)
    def test_software_shadow_and_hash_change_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            interpreter, manifest = f.stage()
            with patch.object(r, 'SYSTEM_PYTHON', interpreter), patch.object(r, 'SYSTEM_PYTHON_SHA256', manifest['python_sha256']):
                command = r.isolated_command(manifest, 'cancel')
                self.assertEqual(command[1:4], ['-I', '-S', '-B'])
                shadow = Path(manifest['cwd']) / 'sitecustomize.py'
                shadow.write_bytes(b'unit shadow')
                with self.assertRaisesRegex(b.Denied, 'import_shadow'):
                    r.isolated_command(manifest, 'launch')
                shadow.unlink()
                (Path(manifest['cwd']) / 'modal_budget_v5.py').write_bytes(b'changed')
                with self.assertRaisesRegex(b.Denied, 'software_file_hash'):
                    r.isolated_command(manifest, 'cancel')
    def test_conflicting_duplicate_listing_never_stop_proof(self):
        schema = {'known': True, 'version': r.SDK_VERSION, 'source_sha256': r.SDK_SCHEMA_FILES,
                  'schema_sha256': b.digest({'version': r.SDK_VERSION, 'source_sha256': r.SDK_SCHEMA_FILES})}
        app = 'ap-' + 'a' * 22
        row = dict(app_id=app, description='unit', state='stopped', tasks='0', created_at='', stopped_at='')
        self.assertTrue(r.parse_stopped_listing(b.encoded([row]), app, schema))
        self.assertFalse(r.verify_remote_stop(b.encoded([row]), app, schema, '5' * 64, 100, 100))
        other = dict(row, state='running')
        with self.assertRaisesRegex(b.Denied, 'conflicting'):
            r.parse_stopped_listing(b.encoded([row, other]), app, schema)
        self.assertFalse(r.installed_listing_schema()['known'])
    def test_finally_exception_persists_unknown_and_passes_deadlines(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            interpreter, manifest = f.stage()
            nonce = f.reserve(1, software_hash=b.digest(manifest))
            class Broken(r.MockTransport):
                def launch(self, *args, **kwargs):
                    raise RuntimeError('synthetic creation uncertainty')
            observed = []
            actual_transaction = b.file_transaction
            def witness(*args, **kwargs):
                observed.append(kwargs.get('deadline'))
                return actual_transaction(*args, **kwargs)
            with patch.object(r, 'SYSTEM_PYTHON', interpreter), patch.object(r, 'SYSTEM_PYTHON_SHA256', manifest['python_sha256']), patch.object(b, 'file_transaction', side_effect=witness):
                stop = r.supervise_mock(f.journal, nonce, f.hashes[nonce], manifest,
                    {'MODAL_TOKEN_SECRET': 'synthetic'}, Broken(), 30, b.HARD_STOP, {'known': False},
                    f.clock.utc, f.clock.monotonic)
            self.assertEqual(stop['status'], 'unknown')
            self.assertFalse(stop['remote_stop_verified'])
            self.assertIn('execution:RuntimeError', stop['errors'])
            self.assertTrue(all(isinstance(x, b.Deadline) for x in observed))
            self.assertEqual(f.journal.snapshot()['reservations'][0]['status'], 'unknown')
            self.assertEqual(b.ParentJournal.exposure(f.journal.snapshot()), (b.MICRO, b.MICRO))
    def test_finalization_disk_failure_preserves_active_claim(self):
        with tempfile.TemporaryDirectory() as root:
            f = Fixture(root)
            interpreter, manifest = f.stage()
            nonce = f.reserve(1, software_hash=b.digest(manifest))
            class Broken(r.MockTransport):
                def launch(self, *args, **kwargs):
                    raise RuntimeError('synthetic')
            with patch.object(r, 'SYSTEM_PYTHON', interpreter), patch.object(r, 'SYSTEM_PYTHON_SHA256', manifest['python_sha256']), patch.object(f.journal, 'finalize', side_effect=OSError('synthetic disk failure')):
                stop = r.supervise_mock(f.journal, nonce, f.hashes[nonce], manifest, {}, Broken(),
                    30, b.HARD_STOP, {'known': False}, f.clock.utc, f.clock.monotonic)
            self.assertEqual(stop['status'], 'unknown')
            self.assertEqual(stop['journal_persistence_failed'], 'OSError')
            self.assertEqual(f.journal.snapshot()['reservations'][0]['status'], 'launch_claimed')


if __name__ == '__main__':
    unittest.main()
