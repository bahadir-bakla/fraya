"""Offline Modal hardening and mock supervision; live transport is DISABLED.

No Modal imports, token/config reads, ambient environment reads or subprocesses.
Real remote operations require a future reviewed transport and separately issued
GPU/cloud grant. CPU admission never supplies that authority.
"""
import hashlib
import json
import re
import sys
import time
from pathlib import Path

from modal_budget_v5 import (Denied, HARD_STOP, PROFILE, ROOT, PRODUCTION_LEDGER, digest,
                             encoded, load, require, sha, utc_seconds, Deadline)

REMOTE_LAUNCH_ENABLED = False
SYSTEM_PYTHON = Path("C:/Users/9bakl/AppData/Local/Programs/Python/Python311/python.exe")
SYSTEM_PYTHON_SHA256 = "5f7b89a612c9b8af1d6456cdfcd1dbe5ca630849e79aebced9bee9a6694952ec"
SDK_VERSION = "1.5.1"
SDK_ROOT = SYSTEM_PYTHON.parent / "Lib/site-packages/modal"
SDK_SCHEMA_FILES = {
    str(SDK_ROOT / "cli/app.py"): "e5c1ea117ba81189035c1b983f2535f45b8713c513d7392bf3e7a93262ec61f5",
    str(SDK_ROOT / "cli/utils.py"): "a00850568a2376c8f771fe71bebe080d2a6dac22389dd109ed93e6065b0fe58c",
}
LIST_KEYS = {"app_id", "description", "state", "tasks", "created_at", "stopped_at"}
OS_ENV_ALLOWLIST = {"SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "USERPROFILE", "APPDATA",
                    "LOCALAPPDATA", "PROGRAMDATA"}
SHUTDOWN_ALLOCATION_SECONDS = {"local_termination": 4, "recovery_journal": 4,
    "cancel": 8, "app_stop": 14, "list": 14, "durable_finalization": 6, "slack": 10}
SOFTWARE_NAMES = {"modal_budget_v5.py", "modal_runner_v5.py"}


def minimal_environment(parent_environment, approved_path):
    """Pure filter of parent-provided values; never obtains or dumps host env."""
    out = {}
    for key, value in parent_environment.items():
        name = key.upper()
        if name in OS_ENV_ALLOWLIST:
            require(name not in out and isinstance(value, str), "duplicate_or_invalid_os_environment")
            out[name] = value
    require(isinstance(approved_path, str) and bool(approved_path), "reviewed_windows_sdk_path_required")
    out["PATH"] = approved_path  # Explicitly reviewed, never inherited PATH.
    out["MODAL_PROFILE"] = PROFILE
    return out


def installed_listing_schema():
    """V5 performs no SDK reads; inherited schema pins are not fresh evidence."""
    return {"known": False, "version": None, "schema_sha256": None}


def parse_stopped_listing(raw, app_id, schema):
    """Offline inherited shape witness; caller schema is not fresh SDK evidence."""
    require(schema.get("known") is True and schema.get("version") == SDK_VERSION and
            schema.get("source_sha256") == SDK_SCHEMA_FILES and
            schema.get("schema_sha256") == digest({"version": SDK_VERSION, "source_sha256": SDK_SCHEMA_FILES}), "unknown_listing_schema")
    rows = load(raw)
    require(isinstance(rows, list) and all(isinstance(r, dict) and set(r) == LIST_KEYS for r in rows), "malformed_listing_schema")
    ids = [r["app_id"] for r in rows]
    require(all(isinstance(i, str) for i in ids) and len(ids) == len(set(ids)), "duplicate_or_conflicting_app_listing")
    matches = [r for r in rows if r["app_id"] == app_id]
    require(len(matches) == 1, "exact_single_app_observation_required")
    return matches[0]["state"] == "stopped" and matches[0]["tasks"] == "0"


def verify_remote_stop(listing_raw, app_id, schema, context_hash, observed_utc, now,
                       provider_stop_raw=None, trusted_provider_stop_sha256=None):
    """Offline proof-shape witness only; caller hashes are not authentication.

    CLI exit zero or a stopped row alone never establishes all-resource stop.
    """
    try:
        require(0 <= now - observed_utc <= 15, "stale_or_future_stop_observation")
        require(parse_stopped_listing(listing_raw, app_id, schema), "app_not_uniquely_stopped")
        require(provider_stop_raw is not None and trusted_provider_stop_sha256 is not None and
                sha(provider_stop_raw) == trusted_provider_stop_sha256, "independently_verified_provider_stop_required")
        proof = load(provider_stop_raw)
        require(proof.get("app_id") == app_id and proof.get("workspace_identity_evidence_sha256") == context_hash
                and proof.get("all_related_resources_stopped") is True and proof.get("observed_utc") == observed_utc
                and proof.get("listing_sha256") == sha(listing_raw), "all_resources_account_context_stop_proof_required")
        return True
    except (Denied, ValueError, TypeError, KeyError):
        return False


def verify_software_manifest(manifest):
    """Approved absolute staging root, exact files, pinned executable and cwd.

    -I -S avoids local/script/user-site imports and automatic site/.pth hooks.
    No unreviewed dependency root is added by this offline bootstrap.
    """
    interpreter = Path(manifest["python_path"])
    require(interpreter.is_absolute() and interpreter.resolve() == SYSTEM_PYTHON.resolve() and
            manifest["python_sha256"] == SYSTEM_PYTHON_SHA256 and sha(interpreter.read_bytes()) == SYSTEM_PYTHON_SHA256,
            "fixed_actual_system_python_hash_required")
    root, cwd = Path(manifest["software_root"]), Path(manifest["cwd"])
    require(root.is_absolute() and cwd.is_absolute() and root.resolve() == cwd.resolve() and root.is_dir(),
            "absolute_reviewed_software_cwd_allowlist_required")
    files = manifest["files"]
    require(set(files) == SOFTWARE_NAMES, "exact_reviewed_software_allowlist_required")
    require({p.name for p in root.iterdir()} == set(files), "unreviewed_local_import_shadow_or_cwd_content")
    for name, expected in files.items():
        file = root / name
        require(file.is_file() and not file.is_symlink() and file.resolve().parent == root.resolve() and
                re.fullmatch(r"[0-9a-f]{64}", expected) is not None and sha(file.read_bytes()) == expected,
                "software_file_hash_or_root_mismatch")
    return root.resolve()


BOOTSTRAP = """import hashlib,json,pathlib,sys,types
assert sys.flags.isolated and sys.flags.no_site
m=json.loads(sys.argv[1]);root=pathlib.Path(m['software_root']).resolve()
assert pathlib.Path.cwd().resolve()==root
assert {p.name for p in root.iterdir()}==set(m['files'])
for name in ('modal_budget_v5.py','modal_runner_v5.py'):
 p=root/name;raw=p.read_bytes()
 assert p.resolve().parent==root and not p.is_symlink()
 assert hashlib.sha256(raw).hexdigest()==m['files'][name]
 mod=types.ModuleType(name[:-3]);mod.__file__=str(p);sys.modules[mod.__name__]=mod
 exec(compile(raw,str(p),'exec'),mod.__dict__)
sys.modules['modal_runner_v5'].child_main(sys.argv[2:])
"""


def isolated_command(manifest, operation, app_id=None):
    root = verify_software_manifest(manifest)
    require(operation in ("launch", "cancel", "list"), "unknown_operation")
    if app_id is not None:
        require(re.fullmatch(r"ap-[A-Za-z0-9]{22}", app_id) is not None, "exact_bound_app_id_required")
    return [str(SYSTEM_PYTHON.resolve()), "-I", "-S", "-B", "-c", BOOTSTRAP,
            encoded(manifest).decode("utf-8"), operation] + ([app_id] if app_id else [])


def child_main(_arguments):
    raise Denied("remote_operations_disabled_pending_new_reviewed_transport_and_parent_gpu_grant")


def supervise_parent(*_args, **_kwargs):
    """Production entry point deliberately has no live subprocess transport."""
    raise Denied("REMOTE_LAUNCH_DISABLED_ZERO_SPEND")


class Watchdog:
    def __init__(self, compute_seconds, expires_utc, utc_clock=time.time, monotonic_clock=time.monotonic):
        require(type(compute_seconds) is int and 0 < compute_seconds <= 1800, "bounded_compute_window_required")
        self.utc, self.mono = utc_clock, monotonic_clock
        self.start_utc, self.start_mono = self.utc(), self.mono()
        require(sum(SHUTDOWN_ALLOCATION_SECONDS.values()) == 60, "shutdown_allocation_contract_required")
        total = compute_seconds + 300  # startup <=240, shutdown 60, all included.
        hard = min(self.start_utc + total, utc_seconds(HARD_STOP), utc_seconds(expires_utc))
        require(hard - self.start_utc > 60, "insufficient_total_shutdown_window")
        cancel = hard - 60
        self.deadlines = {"finalization_reserved_seconds": 6, "slack_reserved_seconds": 10,"hard_utc": hard, "cancel_utc": cancel, "startup_utc": min(self.start_utc + 240, cancel),
                          "start_utc": self.start_utc, "total_seconds": hard - self.start_utc,
                          "compute_seconds": compute_seconds}
        self.mono_hard = self.start_mono + hard - self.start_utc
        self.compute_started_mono = None

    def phase_cutoff(self, phase):
        require(phase in ("startup", "execution", "shutdown", "finalize"), "unknown_watchdog_phase")
        if phase == "startup":
            return self.deadlines["startup_utc"]
        if phase == "execution":
            return self.deadlines["cancel_utc"]
        return self.deadlines["hard_utc"] - (10 if phase == "finalize" else 16)

    def remaining(self, phase, maximum):
        utc_end = self.phase_cutoff(phase)
        mono_end = self.start_mono + utc_end - self.start_utc
        if phase == "execution" and self.compute_started_mono is not None:
            mono_end = min(mono_end, self.compute_started_mono + self.deadlines["compute_seconds"])
        remaining = min(maximum, utc_end - self.utc(), mono_end - self.mono(), self.mono_hard - self.mono())
        require(remaining > 0, "total_startup_execution_shutdown_watchdog_expired")
        return remaining

    def journal_deadline(self, phase, maximum):
        remaining = self.remaining(phase, maximum)
        return Deadline(min(self.phase_cutoff(phase), self.utc() + remaining),
                        min(self.start_mono + self.phase_cutoff(phase) - self.start_utc,
                            self.mono_hard, self.mono() + remaining), self.utc, self.mono)

    def begin_compute(self):
        self.remaining("startup", 240)
        self.compute_started_mono = self.mono()


class MockTransport:
    """Unit witness marker; no live implementation is supplied or enabled."""
    pass


def supervise_mock(journal, nonce, trusted_grant_sha256, manifest, environment, transport,
                   compute_seconds, expires_utc, schema, utc_clock=time.time, monotonic_clock=time.monotonic):
    """Synthetic temp-ledger witness only; never use as a cloud launch API.

    Finally failures independently recorded. Missing/truncated IDs are unknown,
    without regex-recovered stop targets. Disk failure cannot guarantee writing.
    """
    require(isinstance(transport, MockTransport), "mock_only_no_live_transport")
    require(journal.path.is_relative_to(Path(__import__('tempfile').gettempdir()).resolve()), "tests_require_temporary_synthetic_journal")
    watchdog = Watchdog(compute_seconds, expires_utc, utc_clock, monotonic_clock)
    commands = {op: isolated_command(manifest, op) for op in ("launch", "cancel", "list")}
    grant = next(r["immutable_grant"] for r in journal.snapshot(deadline=watchdog.journal_deadline("startup", 5))["reservations"] if r["nonce"] == nonce)
    require(digest(manifest) == grant["software_manifest_sha256"], "exact_parent_reviewed_software_manifest_required")
    environment = minimal_environment(environment, manifest["approved_path"])
    receipt = journal.start_once(nonce, trusted_grant_sha256, watchdog.deadlines, utc_clock(), deadline=watchdog.journal_deadline("startup", 5))
    process, ids, result_complete, errors = None, None, False, []
    stop = {"remote_stop_verified": False, "reservation_release_allowed": False, "app_id": None, "errors": errors,
            "evidence_kind": "mock_witness_only_not_cloud_stop"}
    try:
        journal.claim_child_once(receipt, deadline=watchdog.journal_deadline("startup", 5))
        process = transport.launch(commands["launch"], env=environment, cwd=manifest["cwd"], timeout=watchdog.remaining("startup", 240))
        raw_ids = transport.ids(timeout=watchdog.remaining("startup", 240))
        ids = load(raw_ids)
        require(ids.get("nonce") == nonce and ids.get("owner_fence") == receipt["owner_fence"], "ids_require_bound_nonce_owner")
        journal.record_ids(receipt, ids, deadline=watchdog.journal_deadline("startup", 5))
        watchdog.begin_compute()
        result_complete = process.wait(timeout=watchdog.remaining("execution", compute_seconds)) == 0
        watchdog.remaining("execution", compute_seconds)
    except BaseException as error:
        errors.append("execution:" + type(error).__name__)
    finally:
        # Local child exit is not a remote shutdown proof.
        if process is not None:
            try:
                process.terminate(timeout=watchdog.remaining("shutdown", 2))
            except BaseException as error:
                errors.append("local_terminate:" + type(error).__name__)
                try:
                    process.kill(timeout=watchdog.remaining("shutdown", 2))
                except BaseException as kill_error:
                    errors.append("local_kill:" + type(kill_error).__name__)
        try:
            row = next(r for r in journal.snapshot(deadline=watchdog.journal_deadline("shutdown", 4))["reservations"] if r["nonce"] == nonce)
            bound = row["ids"]  # Durable journal acknowledgment, not partial sidefile.
            if bound:
                app_id = bound["app_id"]
                stop["app_id"] = app_id
                for op, cap in (("cancel", 8), ("app_stop", 14), ("list", 14)):
                    try:
                        command = isolated_command(manifest, "list" if op == "list" else "cancel", app_id)
                        observation = transport.run(op, command, env=environment, cwd=manifest["cwd"], timeout=watchdog.remaining("shutdown", cap))
                        if op == "list":
                            stop["remote_stop_verified"] = verify_remote_stop(observation["raw"], app_id, schema,
                                row["immutable_grant"]["workspace_identity_evidence_sha256"], observation["observed_utc"], utc_clock(),
                                observation.get("provider_stop_raw"), observation.get("trusted_provider_stop_sha256"))
                        else:
                            stop[op + "_exit_code"] = observation.get("exit_code")
                    except BaseException as error:
                        errors.append(op + ":" + type(error).__name__)
            else:
                errors.append("remote_ids_unknown_no_authorized_stop_target")
        except BaseException as error:
            errors.append("stop_recovery:" + type(error).__name__)
        stop["result_complete"] = result_complete
        stop["remote_stop_verified"] = stop["remote_stop_verified"] is True and not any(e.startswith("stop_recovery:") for e in errors)
        try:
            stop["status"] = journal.finalize(receipt, stop, deadline=watchdog.journal_deadline("finalize", 6))
        except BaseException as error:
            stop["journal_persistence_failed"] = type(error).__name__
            stop["status"] = "unknown"
            stop["remote_stop_verified"] = False
            # Active starting/claimed record already persisted; no retry/release.
    return stop


# There is deliberately no production command-line launcher or report routine.
if __name__ == "__main__":
    supervise_parent()
