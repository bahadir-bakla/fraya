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

from modal_budget_v4 import (Denied, HARD_STOP, PROFILE, ROOT, PRODUCTION_LEDGER, digest,
                             encoded, load, require, sha, utc_seconds)

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
SOFTWARE_NAMES = {"modal_budget_v4.py", "modal_runner_v4.py"}


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
    """Read SDK source bytes and distribution metadata only, never import SDK."""
    try:
        import importlib.metadata
        require(importlib.metadata.version("modal") == SDK_VERSION, "unknown_sdk_version")
        require(all(sha(Path(path).read_bytes()) == expected for path, expected in SDK_SCHEMA_FILES.items()), "unknown_sdk_source_schema")
        return {"known": True, "version": SDK_VERSION, "source_sha256": SDK_SCHEMA_FILES,
                "keys": sorted(LIST_KEYS), "schema_sha256": digest({"version": SDK_VERSION, "source_sha256": SDK_SCHEMA_FILES})}
    except (OSError, Denied, importlib.metadata.PackageNotFoundError):
        return {"known": False, "version": None, "schema_sha256": None}


def parse_stopped_listing(raw, app_id, schema):
    """Source-verified shape only. Does not prove account identity or settlement."""
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
    """CLI exit zero or a stopped row alone never establishes all-resource stop."""
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
for name in ('modal_budget_v4.py','modal_runner_v4.py'):
 p=root/name;raw=p.read_bytes()
 assert p.resolve().parent==root and not p.is_symlink()
 assert hashlib.sha256(raw).hexdigest()==m['files'][name]
 mod=types.ModuleType(name[:-3]);mod.__file__=str(p);sys.modules[mod.__name__]=mod
 exec(compile(raw,str(p),'exec'),mod.__dict__)
sys.modules['modal_runner_v4'].child_main(sys.argv[2:])
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
        total = compute_seconds + 300  # startup <=240, shutdown 60, all included.
        hard = min(self.start_utc + total, utc_seconds(HARD_STOP), utc_seconds(expires_utc))
        require(hard - self.start_utc > 60, "insufficient_total_shutdown_window")
        cancel = hard - 60
        self.deadlines = {"hard_utc": hard, "cancel_utc": cancel, "startup_utc": min(self.start_utc + 240, cancel),
                          "start_utc": self.start_utc, "total_seconds": hard - self.start_utc,
                          "compute_seconds": compute_seconds}
        self.mono_hard = self.start_mono + hard - self.start_utc
        self.compute_started_mono = None

    def remaining(self, phase, maximum):
        utc_deadline = self.deadlines["startup_utc"] if phase == "startup" else self.deadlines["cancel_utc"] if phase == "execution" else self.deadlines["hard_utc"]
        monotonic_deadline = self.start_mono + utc_deadline - self.start_utc
        if phase == "execution" and self.compute_started_mono is not None:
            monotonic_deadline = min(monotonic_deadline, self.compute_started_mono + self.deadlines["compute_seconds"])
        remaining = min(maximum, utc_deadline - self.utc(), monotonic_deadline - self.mono(), self.mono_hard - self.mono())
        require(remaining > 0, "total_startup_execution_shutdown_watchdog_expired")
        return remaining

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
    require(str(journal.path).startswith(str(Path(__import__('tempfile').gettempdir()).resolve())), "tests_require_temporary_synthetic_journal")
    commands = {op: isolated_command(manifest, op) for op in ("launch", "cancel", "list")}
    grant = next(r["immutable_grant"] for r in journal.snapshot()["reservations"] if r["nonce"] == nonce)
    require(digest(manifest) == grant["software_manifest_sha256"], "exact_parent_reviewed_software_manifest_required")
    environment = minimal_environment(environment, manifest["approved_path"])
    watchdog = Watchdog(compute_seconds, expires_utc, utc_clock, monotonic_clock)
    receipt = journal.start_once(nonce, trusted_grant_sha256, watchdog.deadlines, utc_clock())
    process, ids, result_complete, errors = None, None, False, []
    stop = {"remote_stop_verified": False, "reservation_release_allowed": False, "app_id": None, "errors": errors,
            "evidence_kind": "mock_witness_only_not_cloud_stop"}
    try:
        journal.claim_child_once(receipt)
        process = transport.launch(commands["launch"], env=environment, cwd=manifest["cwd"], timeout=watchdog.remaining("startup", 240))
        raw_ids = transport.ids(timeout=watchdog.remaining("startup", 240))
        ids = load(raw_ids)
        require(ids.get("nonce") == nonce and ids.get("owner_fence") == receipt["owner_fence"], "ids_require_bound_nonce_owner")
        journal.record_ids(receipt, ids)
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
            row = next(r for r in journal.snapshot()["reservations"] if r["nonce"] == nonce)
            bound = row["ids"]  # Durable journal acknowledgment, not partial sidefile.
            if bound:
                app_id = bound["app_id"]
                stop["app_id"] = app_id
                for op, cap in (("cancel", 10), ("app_stop", 15), ("list", 15)):
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
            stop["status"] = journal.finalize(receipt, stop)
        except BaseException as error:
            stop["journal_persistence_failed"] = type(error).__name__
            stop["status"] = "unknown"
            stop["remote_stop_verified"] = False
            # Active starting/claimed record already persisted; no retry/release.
    return stop


def main(verification=None):
    opus_path = ROOT / "analysis/night-opus-learned-v3-r3.json"
    astra_path = ROOT / "analysis/learned-layer-design.checkpoint10-admission-budget.json"
    opus, astra = load(opus_path.read_bytes()), load(astra_path.read_bytes())
    budget_raw = PRODUCTION_LEDGER.read_bytes()
    require(sha(budget_raw) == "87423d458ab5b8767291f7773c1078fde6d4e522b0c791184d1316b14e7d832f", "production_ledger_changed_review_required")
    protected = {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in (opus_path, astra_path, PRODUCTION_LEDGER)}
    # Hash-only inspection of frozen adapter sources and previously reviewed packets.
    frozen = sorted((ROOT / "integrations/learned-dialogue").glob("modal_narrow*"))
    reviewed = [ROOT / p for p in (
        "research/customer-benchmark/semantic-v3-collection/label-free-primary-review-packet.json",
        "research/customer-benchmark/semantic-v3-collection/label-free-date-review-packet.json",
        "analysis/night-v3-fresh-reviewer-a.json", "analysis/night-v3-fresh-reviewer-b.json", "analysis/night-v3-fresh-adjudication.json")]
    protected.update({str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in frozen + reviewed if p.is_file()})
    for p in frozen:
        relative = p.relative_to(ROOT).as_posix()
        if p.is_file() and relative in opus["source_manifest"]:
            require(sha(p.read_bytes()) == opus["source_manifest"][relative]["sha256"], "frozen_opus_audited_adapter_changed:" + relative)
    report = {"schema_version": "modal_hardening.v4", "status": "BLOCKED_ZERO_SPEND", "remote_launch_enabled": False,
              "cloud_actions": 0, "GPU_jobs": 0, "spend_usd": 0, "production_ledger_writes": 0,
              "CPU_grant_is_GPU_permission": False, "parent_gpu_grant_created": False,
              "verification": verification or {"status": "unit results must be supplied from an actual test run", "suite": "test_modal_v4"},
              "implementation_sha256": {name: sha((Path(__file__).parent / name).read_bytes()) for name in
                                        ("modal_budget_v4.py", "modal_runner_v4.py", "test_modal_v4.py")},
              "protected_source_sha256": protected, "budget_profile": load(budget_raw)["profile"],
              "credential_profile_files_read": False, "secret_environment_values_read": False,
              "explicit_host_environment_reads": False, "environment_witnesses": "synthetic sentinel values only; standard-library temporary-directory selection used",
              "profile_credential_hashes": "not inspected; token/config files deliberately not read or written",
              "native_opus_elapsed_seconds": opus["elapsed_seconds"], "cpu_audit_observations": len(opus["cpu_witnesses"]),
              "audit_findings": [f for f in opus["review"]["findings"] if f["id"] in ("F1", "F2", "F6")],
              "astra_decision": astra["decision"], "installed_listing_schema": installed_listing_schema(),
              "transaction": "One parent/one host, grant-pinned unsynchronized authoritative journal path, Windows OS byte lock + fsync + atomic replace; production aggregate stays read-only in workers.",
              "states": "reserved -> admitted_unlaunched -> starting -> launch_claimed -> finished/stopped/unknown; nonce and lifetime starting count never refunded",
              "budgets": {"task_target_usd": 30, "task_hard_cap_usd": 35, "shared_first_experiment_usd": 10,
                           "all_task_attempts_maximum": 3, "active_GPU_jobs_maximum": 1,
                           "cost_categories": ["GPU", "CPU", "memory", "disk", "build", "storage", "egress", "other"]},
              "watchdog": {"hard_stop_utc": HARD_STOP, "startup_seconds_max": 240, "compute_seconds_max": 1800,
                           "total_window_seconds_max": 2100, "shutdown_reserved_seconds": 60, "retries": 0},
              "isolation": "Launch/cancel/list share allowlisted OS environment, pinned profile and explicit PATH; actual absolute system Python -I -S -B, only hash-reviewed files in exact staging cwd.",
              "stop_policy": "Duplicate/conflicting/unknown/stale listing or missing account/all-resource provider proof => unknown; CLI exit 0 never releases budget. Unknown retains global active slot and full hold.",
              "limits": ["No live transport implemented or enabled; no Modal/API subprocess invoked.",
                         "Local CAS does not guarantee exactly-once cloud creation or cutoff during host/provider/network failure.",
                         "No current rates/account/billing/provider resource bounds or live independent guardian verified; parent evidence is still required.",
                         "Caller identity/file ACLs and rollback protection across coordinator restart need parent deployment; class APIs cannot authenticate caller.",
                         "File persistence cannot be guaranteed during disk/OS failure; persisted active claim blocks subsequent launches.",
                         "Listing source shape verified without importing SDK; source shape alone does not verify workspace, zero billing resources or settled cost."],
              "handoff": "Parent creates fresh exact-payload GPU/cloud grants only after real benefit, reviewed TRAIN/dev allowlist, no holdout, provider maxima/cost/account evidence, trusted software and independent guardian are reviewed. Existing primary CPU-only grant is insufficient."}
    out = ROOT / "analysis/night-modal-v4-hardening.json"
    out.write_bytes(json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8") + b"\n")
    text = ["Modal v4 hardening: BLOCKED, ZERO SPEND. No live cloud transport or GPU grant.",
            "Shared first experiment: USD10 across all <=3 lifetime starting attempts; task target30/hard35; one active GPU job.",
            "Parent Windows-lock/fsync/replace local journal; workers do not mutate production modal-budget.json.",
            "Single-use nonce consumption followed by atomic child launch_claimed transition; unknown outcomes retain budget and active slot.",
            "Whitelist launch/cancel/list environments; actual system Python -I -S -B; exact hash-reviewed staging/cwd allowlist.",
            "Fixed TOTAL startup/compute/shutdown watchdog; hard stop " + HARD_STOP + "; no retries/services/cron/min containers.",
            "Installed Modal1.5.1 snake_case listing schema source inspected; conflicting duplicates or CLI exit0 are not stop proof.",
            "Outer finally persists stop/unknown where filesystem works; unresolved IDs never regex-authorize a stop target.",
            "No token/profile files or secret environment values inspected; environment witnesses use synthetic values; profile credential hashes unknown/uninspected.",
            "CPU-only admission is not GPU/cloud permission. Parent creates actual grants later.",
            "Unit verification: " + json.dumps(report["verification"], sort_keys=True),
            "JSON SHA256 " + sha(out.read_bytes()), "", "Protected input/source SHA256:"]
    text.extend(p + " " + h for p, h in protected.items())
    (ROOT / "analysis/night-modal-v4-hardening.txt").write_bytes(("\n".join(text) + "\n").encode("utf-8"))
    print(json.dumps({"status": report["status"], "listing_schema_known": report["installed_listing_schema"]["known"]}))


if __name__ == "__main__":
    main()
