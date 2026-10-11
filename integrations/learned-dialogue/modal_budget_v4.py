"""Parent-only durable single-host budget coordinator; no Modal/credential imports.

Never uses modal-budget.json as a mutable worker ledger. The parent must choose
an unsynchronized local journal and separately issue exact-hash GPU grants.
Single-use nonces establish local replay protection, not remote exactly-once.
"""
import copy
import base64
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PROFILE = "businessforever2338"
HARD_STOP = "2026-10-11T06:13:01Z"
MICRO = 1_000_000
TARGET, HARD_CAP, FIRST_ENVELOPE = 30 * MICRO, 35 * MICRO, 10 * MICRO
MAX_INVOCATIONS = 3
ACTIVE = {"starting", "launch_claimed", "unknown"}
STATES = {"reserved", "admitted_unlaunched", "starting", "launch_claimed", "finished", "stopped", "unknown"}
ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_LEDGER = ROOT / "local-runs/autonomous-rd/modal-budget.json"


class Denied(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Denied(reason)


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(encoded(value))


def load(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out, "duplicate_json_key")
            out[key] = value
        return out
    def invalid(_):
        raise Denied("nonfinite_json")
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def utc_seconds(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, "timezone_required")
    return parsed.timestamp()


def uint(value):
    require(type(value) is int and value >= 0, "nonnegative_integer_micro_usd_required")
    return value


def exact_parent_grant(raw, trusted_sha256):
    require(raw is not None and trusted_sha256 is not None and sha(raw) == trusted_sha256,
            "externally_trusted_exact_parent_gpu_grant_required")
    grant = load(raw)
    require(grant.get("schema_version") == "parent_modal_gpu_grant.v4" and grant.get("issuer") == "parent"
            and grant.get("gpu_authorized") is True and grant.get("cloud_authorized") is True
            and grant.get("profile") == PROFILE, "separate_explicit_gpu_cloud_grant_required")
    require(re.fullmatch(r"[0-9a-f]{32,128}", grant.get("nonce", "")) is not None, "parent_128_bit_unique_nonce_required")
    require(bool(grant.get("qualification_benefit")) and bool(grant.get("reviewed_train_dev_source_allowlist")),
            "qualification_benefit_and_reviewed_source_allowlist_required")
    require(grant.get("holdout_allowed") is False and grant.get("reviewed_train_dev_source_allowlist") == grant.get("payload_source_allowlist"),
            "exact_train_dev_allowlist_no_holdout_required")
    for entry in grant["payload_source_allowlist"]:
        require(entry.get("split") in ("train", "dev") and entry.get("reviewed") is True and
                re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")) is not None and bool(entry.get("path")),
                "reviewed_train_dev_source_binding_required")
    for field in ("payload_sha256", "software_manifest_sha256", "resource_manifest_sha256", "rate_evidence_sha256",
                  "reviewed_data_admission_sha256", "workspace_identity_evidence_sha256", "independent_watchdog_evidence_sha256"):
        require(re.fullmatch(r"[0-9a-f]{64}", grant.get(field, "")) is not None, "exact_gpu_evidence_binding_required:" + field)
    require(grant.get("provider_bounds_verified") is True and grant.get("account_identity_verified") is True
            and grant.get("independent_watchdog_armed") is True, "verified_provider_account_watchdog_evidence_required")
    require(grant.get("gpu_count") == 1 and grant.get("max_containers") == 1
            and grant.get("min_containers") == 0 and grant.get("retries") == 0
            and grant.get("services") is False and grant.get("cron") is False, "single_ephemeral_gpu_no_retries_services_required")
    return grant


def conservative_cost_bound(resources):
    """Integer microUSD upper bound, using externally verified rate ceilings.

    No prices are guessed. A valid arithmetic bound alone is not a launch grant.
    Resource/rate evidence must be separately bound by the parent and enforceable
    remotely, including image-build and cancellation-failure exposure.
    """
    require(resources.get("gpu_count") == 1 and resources.get("max_containers") == 1,
            "one_gpu_one_container_required")
    def ceil_div(a, b):
        return (a + b - 1) // b
    gpu = uint(resources["gpu_rate_micro_per_second"]) * uint(resources["gpu_billable_seconds_max"])
    cpu = ceil_div(uint(resources["cpu_rate_micro_per_core_second"]) * uint(resources["cpu_millicores_max"]) *
                   uint(resources["cpu_billable_seconds_max"]), 1000)
    ram = ceil_div(uint(resources["ram_rate_micro_per_gib_second"]) * uint(resources["memory_mib_max"]) *
                   uint(resources["ram_billable_seconds_max"]), 1024)
    disk = uint(resources["disk_rate_micro_per_gib_second"]) * uint(resources["disk_gib_max"]) * uint(resources["disk_billable_seconds_max"])
    extras = sum(uint(resources[name]) for name in ("build_bound_micro_usd", "storage_bound_micro_usd",
                                                  "egress_bound_micro_usd", "other_bound_micro_usd"))
    require(all(resources[name] > 0 for name in ("gpu_billable_seconds_max", "cpu_millicores_max", "memory_mib_max")),
            "positive_resource_maxima_required")
    return gpu + cpu + ram + disk + extras


def atomic_write(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


@contextmanager
def file_transaction(path, timeout_seconds=5):
    """OS-enforced lock on a stable companion file, across replace and processes.

    Windows msvcrt byte-range lock; POSIX fallback is for portable unit tests.
    The lock is single-host only; OneDrive is explicitly rejected by ParentJournal.
    """
    lock_path = Path(str(path) + ".lock")
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        acquired = False
        while not acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                require(time.monotonic() < deadline, "parent_transaction_lock_timeout")
                time.sleep(.01)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


class ParentJournal:
    """Only the parent owns this writer; do not expose it to a child process.

    File ACLs, one coordinator/host, and externally authenticated trust anchors
    are deployment obligations. A Python class cannot authenticate its caller.
    """
    def __init__(self, path, coordinator_id, work_id):
        self.path = Path(path).resolve()
        require(self.path != PRODUCTION_LEDGER.resolve() and self.path.name.lower() != "modal-budget.json",
                "production_aggregate_is_read_only")
        require(not any(part.lower().startswith("onedrive") for part in self.path.parts), "unsynchronized_local_parent_journal_required")
        require(self.path.parent.is_dir(), "parent_owned_journal_directory_required")
        self.coordinator_id, self.work_id = coordinator_id, work_id
        self.seen_revision = -1

    def initialize(self, production_snapshot_raw, trusted_snapshot_sha256):
        require(sha(production_snapshot_raw) == trusted_snapshot_sha256, "production_snapshot_hash_mismatch")
        snapshot = load(production_snapshot_raw)
        require(snapshot.get("profile") == PROFILE and snapshot.get("target_usd") == 30 and
                snapshot.get("hard_cap_usd") == 35 and snapshot.get("cloud_stop_utc") == HARD_STOP,
                "existing_task_budget_contract_required")
        require(snapshot.get("actual_task_cost_verified") is True and type(snapshot.get("actual_task_cost_usd")) is int,
                "existing_actual_cost_requires_reconciliation")
        require(snapshot.get("reservations") == [] and snapshot.get("invocations") == [], "existing_task_activity_requires_parent_migration")
        base = uint(snapshot["actual_task_cost_usd"]) * MICRO
        require(base <= TARGET, "global_target_exceeded")
        with file_transaction(self.path):
            require(not self.path.exists(), "parent_journal_already_exists_no_reset")
            value = {"schema_version": "parent_modal_journal.v4", "work_id": self.work_id,
                     "coordinator_id": self.coordinator_id, "production_snapshot_sha256": trusted_snapshot_sha256,
                     "profile": PROFILE, "target_micro_usd": TARGET, "hard_cap_micro_usd": HARD_CAP,
                     "first_experiment_envelope_micro_usd": FIRST_ENVELOPE, "base_verified_cost_micro_usd": base,
                     "hard_stop_utc": HARD_STOP, "revision": 0, "start_count": 0, "reservations": [], "events": []}
            atomic_write(self.path, value)

    def _read(self):
        value = load(self.path.read_bytes())
        require(value.get("schema_version") == "parent_modal_journal.v4" and value.get("work_id") == self.work_id
                and value.get("coordinator_id") == self.coordinator_id and value.get("profile") == PROFILE,
                "single_parent_work_identity_mismatch")
        revision = uint(value["revision"])
        require(revision >= self.seen_revision and revision == len(value["events"]), "journal_revision_rollback_or_event_gap")
        require(value["target_micro_usd"] == TARGET and value["hard_cap_micro_usd"] == HARD_CAP and
                value["first_experiment_envelope_micro_usd"] == FIRST_ENVELOPE and value["hard_stop_utc"] == HARD_STOP,
                "task_budget_cannot_be_reset_by_worker")
        rows = value["reservations"]
        for field in ("nonce", "reservation_id", "invocation_id"):
            require(len({r[field] for r in rows}) == len(rows), "duplicate_journal_identity")
        require(all(r["status"] in STATES for r in rows), "unknown_journal_state")
        require(all(type(r["started"]) is bool and digest(r["immutable_grant"]) == r["immutable_grant_sha256"]
                    and sha(base64.b64decode(r["grant_raw_base64"], validate=True)) == r["grant_sha256"]
                    and load(base64.b64decode(r["grant_raw_base64"], validate=True)) == r["immutable_grant"] for r in rows),
                "immutable_grant_changed_or_invalid_start_flag")
        require(value["start_count"] == sum(r["started"] for r in rows) <= MAX_INVOCATIONS, "invocation_counter_mismatch_or_cap")
        require(sum(r["status"] in ACTIVE for r in rows) <= 1, "multiple_active_gpu_jobs")
        self.seen_revision = revision
        return value

    def snapshot(self):
        with file_transaction(self.path):
            return copy.deepcopy(self._read())

    @staticmethod
    def exposure(value):
        holds = sum(uint(r["upper_bound_micro_usd"]) if not r["settled"] else uint(r["actual_micro_usd"])
                    for r in value["reservations"])
        return uint(value["base_verified_cost_micro_usd"]) + holds, holds

    def _commit(self, value, operation, nonce):
        value["events"].append({"sequence": value["revision"] + 1, "operation": operation, "nonce": nonce})
        value["revision"] += 1
        atomic_write(self.path, value)
        self.seen_revision = value["revision"]

    def reserve(self, grant_raw, trusted_grant_sha256, payload_raw, resources, evidence, now):
        grant = exact_parent_grant(grant_raw, trusted_grant_sha256)
        require(grant["work_id"] == self.work_id and grant["coordinator_id"] == self.coordinator_id, "parent_grant_work_owner_mismatch")
        require(grant.get("parent_journal_path") == str(self.path), "one_parent_authoritative_journal_path_required")
        require(sha(payload_raw) == grant["payload_sha256"] and digest(resources) == grant["resource_manifest_sha256"], "exact_payload_resource_binding_required")
        payload = load(payload_raw)
        require(payload.get("schema_version") == "modal_train_payload.v4" and
                payload.get("source_allowlist") == grant["payload_source_allowlist"] and payload.get("holdout_allowed") is False,
                "actual_payload_exact_reviewed_train_dev_allowlist_required")
        require(evidence == {k: grant[k] for k in ("software_manifest_sha256", "rate_evidence_sha256", "reviewed_data_admission_sha256",
                "workspace_identity_evidence_sha256", "independent_watchdog_evidence_sha256")}, "actual_parent_gpu_evidence_required")
        require(now < utc_seconds(grant["expires_utc"]) <= utc_seconds(HARD_STOP), "expired_or_late_gpu_grant")
        upper = conservative_cost_bound(resources)
        require(upper <= uint(grant["reservation_micro_usd"]) <= FIRST_ENVELOPE, "cost_bound_exceeds_subreservation")
        with file_transaction(self.path):
            value = self._read()
            require(not any(r["nonce"] == grant["nonce"] or r["reservation_id"] == grant["reservation_id"]
                            or r["invocation_id"] == grant["invocation_id"] for r in value["reservations"]), "nonce_or_reservation_replay")
            require(len(value["reservations"]) < MAX_INVOCATIONS and value["start_count"] < MAX_INVOCATIONS, "three_task_invocations_maximum")
            projected, experiment = self.exposure(value)
            amount = grant["reservation_micro_usd"]
            require(projected + amount <= TARGET and projected + amount <= HARD_CAP, "aggregate_task_budget_overspend")
            require(experiment + amount <= FIRST_ENVELOPE, "first_experiment_total_ten_dollar_gate")
            value["reservations"].append({"nonce": grant["nonce"], "reservation_id": grant["reservation_id"],
                "invocation_id": grant["invocation_id"], "grant_sha256": trusted_grant_sha256,
                "grant_raw_base64": base64.b64encode(grant_raw).decode("ascii"),
                "immutable_grant": grant, "immutable_grant_sha256": digest(grant), "status": "reserved", "started": False, "child_claimed": False,
                "settled": False, "upper_bound_micro_usd": amount, "actual_micro_usd": None,
                "owner_fence": None, "ids": None, "stop_record": None})
            self._commit(value, "reserve", grant["nonce"])

    def _entry(self, value, nonce):
        entries = [r for r in value["reservations"] if r["nonce"] == nonce]
        require(len(entries) == 1, "unknown_nonce")
        return entries[0]

    def admit_unlaunched(self, nonce, trusted_grant_sha256):
        with file_transaction(self.path):
            value = self._read()
            row = self._entry(value, nonce)
            require(row["status"] == "reserved" and row["grant_sha256"] == trusted_grant_sha256, "unlaunched_admission_binding_required")
            row["status"] = "admitted_unlaunched"
            self._commit(value, "admit_unlaunched", nonce)

    def start_once(self, nonce, trusted_grant_sha256, deadlines, now):
        with file_transaction(self.path):
            value = self._read()
            row = self._entry(value, nonce)
            require(row["status"] == "admitted_unlaunched" and not row["started"] and row["grant_sha256"] == trusted_grant_sha256,
                    "single_use_admitted_unlaunched_nonce_required")
            require(not any(r["status"] in ACTIVE for r in value["reservations"]), "another_active_or_unknown_gpu_job")
            require(value["start_count"] < MAX_INVOCATIONS, "three_task_invocations_maximum")
            require(now < utc_seconds(row["immutable_grant"]["expires_utc"]) and deadlines["hard_utc"] <= utc_seconds(HARD_STOP)
                    and deadlines["hard_utc"] <= utc_seconds(row["immutable_grant"]["expires_utc"])
                    and deadlines["cancel_utc"] <= deadlines["hard_utc"] - 60 and now < deadlines["startup_utc"] <= deadlines["cancel_utc"],
                    "fixed_startup_compute_shutdown_deadlines_required")
            require(deadlines["startup_utc"] - now <= 240 and deadlines["hard_utc"] - now <= 2100 and
                    0 < deadlines["compute_seconds"] <= 1800, "total_wall_resource_ceiling_required")
            value["start_count"] += 1
            row.update(status="starting", started=True, ordinal=value["start_count"], owner_fence=uuid.uuid4().hex, deadlines=deadlines)
            self._commit(value, "starting", nonce)
            return {"nonce": nonce, "grant_sha256": row["grant_sha256"], "invocation_id": row["invocation_id"],
                    "owner_fence": row["owner_fence"], "ordinal": row["ordinal"], "deadlines": copy.deepcopy(deadlines)}

    def claim_child_once(self, receipt):
        with file_transaction(self.path):
            value = self._read()
            row = self._entry(value, receipt["nonce"])
            require(row["status"] == "starting" and not row["child_claimed"] and
                    all(row[field] == receipt[field] for field in ("grant_sha256", "invocation_id", "owner_fence", "ordinal", "deadlines")),
                    "one_atomic_child_claim_required")
            row["child_claimed"] = True
            row["status"] = "launch_claimed"
            self._commit(value, "child_claim_once", row["nonce"])

    def record_ids(self, receipt, ids):
        require(re.fullmatch(r"ap-[A-Za-z0-9]{22}", ids.get("app_id", "")) is not None, "exact_bound_app_id_required")
        with file_transaction(self.path):
            value = self._read()
            row = self._entry(value, receipt["nonce"])
            require(row["status"] == "launch_claimed" and row["child_claimed"] and row["owner_fence"] == receipt["owner_fence"]
                    and row["ids"] is None, "id_ack_requires_unique_claimed_owner")
            row["ids"] = copy.deepcopy(ids)
            self._commit(value, "durable_remote_id_ack", row["nonce"])

    def finalize(self, receipt, stop_record):
        with file_transaction(self.path):
            value = self._read()
            row = self._entry(value, receipt["nonce"])
            require(row["status"] in ("starting", "launch_claimed") and row["owner_fence"] == receipt["owner_fence"], "finalize_requires_starting_owner")
            # Stop/cost proof must originate in separately trusted parent evidence.
            verified = stop_record.get("remote_stop_verified") is True and bool(row["ids"]) and stop_record.get("app_id") == row["ids"]["app_id"]
            row["status"] = ("finished" if stop_record.get("result_complete") is True else "stopped") if verified else "unknown"
            row["stop_record"] = copy.deepcopy(stop_record)
            self._commit(value, "stop_record_" + row["status"], row["nonce"])
            return row["status"]

    def settle(self, nonce, billing_raw, trusted_billing_sha256):
        require(sha(billing_raw) == trusted_billing_sha256, "externally_verified_billing_hash_required")
        billing = load(billing_raw)
        with file_transaction(self.path):
            value = self._read()
            row = self._entry(value, nonce)
            require(row["status"] in ("finished", "stopped") and not row["settled"] and billing.get("nonce") == nonce
                    and billing.get("final_attribution_verified") is True, "verified_stop_and_final_cost_required")
            row["actual_micro_usd"] = uint(billing["actual_micro_usd"])
            row["settled"] = True
            row["billing_sha256"] = trusted_billing_sha256
            value["budget_breached"] = self.exposure(value)[0] > TARGET
            self._commit(value, "settled_actual_cost", nonce)


def worker_read_receipt(journal_path, receipt):
    """Read-only worker check of this invocation; no mutable global hash equality.

    The parent must already atomically claim this one child. A read check alone
    does not authorize a second child and this function performs no cloud action.
    """
    value = load(Path(journal_path).read_bytes())
    matches = [r for r in value["reservations"] if r["nonce"] == receipt["nonce"]]
    require(len(matches) == 1, "worker_unknown_nonce")
    row = matches[0]
    require(sha(base64.b64decode(row["grant_raw_base64"], validate=True)) == receipt["grant_sha256"] and
            load(base64.b64decode(row["grant_raw_base64"], validate=True)) == row["immutable_grant"] and
            row["immutable_grant"].get("parent_journal_path") == str(Path(journal_path).resolve()),
            "worker_immutable_exact_parent_grant_required")
    require(row["status"] == "launch_claimed" and row["child_claimed"] is True and
            all(row[k] == receipt[k] for k in ("grant_sha256", "invocation_id", "owner_fence", "ordinal", "deadlines")),
            "worker_exact_claimed_receipt_required")
    return copy.deepcopy(row["immutable_grant"])
