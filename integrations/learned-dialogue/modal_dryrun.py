"""Read-only cost/admission planning. No Modal import or remote launch path.

Only parent may change the global ledger or authorize reservations/data gates.
No local authentication material is read. Account verification is parent-owned.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from build_data import encoded, freeze
from train_v2 import ROOT, strict_json

POSTED_GPU_RATES = {"H100": .001097, "H200": .001261}
POSTED_RATE_SOURCE = "https://modal.com/pricing"
POSTED_RATE_VERIFIED_UTC = "2026-10-11T01:51:42Z"
GPU_BILLING_SOURCE = "https://modal.com/docs/guide/gpu"
TIMEOUT_SOURCE = "https://modal.com/docs/guide/timeouts"


def evaluate_admission(budget, plan, now_utc, data_gate=None, reservation_id=None):
    envelope = plan["job_envelope"]
    cost = plan["cost_envelope"]
    # Automatic H100->H200 upgrades retain H100 billing. The maximum posted
    # rate is an extra conservative reservation envelope, not that billing rule.
    effective_rate = (max(POSTED_GPU_RATES.values()) + 2 * cost["posted_physical_cpu_core_per_second_usd"] + 16 * cost["posted_host_gib_per_second_usd"])
    seconds = sum(row["compute_timeout_seconds"] + envelope["load_and_shutdown_reserve_seconds_per_invocation"] for row in envelope["invocations"])
    estimated = effective_rate * seconds
    reasons = []
    if any(type(budget.get(key)) not in (int, float) or not (0 <= budget[key] < float("inf")) for key in ("actual_task_cost_usd", "target_usd", "hard_cap_usd")):
        raise ValueError("Nonnegative finite global budget values required")
    stop = datetime.fromisoformat(budget["cloud_stop_utc"].replace("Z", "+00:00"))
    if now_utc >= stop:
        reasons.append("cloud_stop_deadline_passed")
    if budget.get("profile") != "businessforever2338" or budget.get("single_job_at_a_time") is not True or budget.get("max_gpus_per_job") != 1:
        reasons.append("parent_profile_or_serial_resource_contract_missing")
    if budget.get("actual_task_cost_verified") is not True:
        reasons.append("actual_global_spend_unverified")
    reservations = budget.get("reservations", [])
    if any(type(row.get("reserved_usd", row.get("amount_usd", 0))) not in (int, float) or not (0 <= row.get("reserved_usd", row.get("amount_usd", 0)) < float("inf")) for row in reservations):
        raise ValueError("Nonnegative finite reservation values required")
    committed = sum(float(row.get("reserved_usd", row.get("amount_usd", 0))) for row in reservations if row.get("status", "reserved") not in {"released", "closed", "cancelled"})
    global_projected = float(budget.get("actual_task_cost_usd", 0)) + committed
    reservation = next((row for row in reservations if row.get("reservation_id") == reservation_id), None) if reservation_id else None
    if reservation is None or reservation.get("authorized_by_parent") is not True:
        reasons.append("parent_reservation_authorization_missing")
        global_projected += cost["experiment_reservation_usd"]
    elif float(reservation.get("reserved_usd", reservation.get("amount_usd", 0))) < cost["experiment_reservation_usd"]:
        reasons.append("reservation_below_bounded_envelope")
    if global_projected > min(30, float(budget["target_usd"])):
        reasons.append("global_target_30_would_be_exceeded")
    if global_projected > min(35, float(budget["hard_cap_usd"])):
        reasons.append("global_hard_cap_35_would_be_exceeded")
    if any(row.get("status") in {"running", "starting", "stopping"} for row in budget.get("invocations", [])):
        reasons.append("another_job_active")
    if not data_gate or data_gate.get("authorized_by_parent") is not True or data_gate.get("reviewed_data_gate") is not True:
        reasons.append("reviewed_data_gate_not_authorized")
    if not data_gate or not data_gate.get("effective_rate_verified_by_parent"):
        reasons.append("effective_account_resource_rates_not_verified")
    if data_gate and data_gate.get("effective_rate_verified_by_parent") and (not isinstance(data_gate.get("effective_resource_rate_usd_per_second"), (int, float)) or data_gate["effective_resource_rate_usd_per_second"] < effective_rate):
        reasons.append("verified_rate_does_not_cover_h100_h200_resources")
    if data_gate and (data_gate.get("train_independent_reviewed_groups", 0) < 100 or data_gate.get("minimum_reviewed_positive_groups_per_trained_class", 0) < 20):
        reasons.append("designer_data_readiness_floor_unmet")
    if not data_gate or data_gate.get("sdk_version_and_capabilities_verified_by_parent") is not True:
        reasons.append("actual_sdk_timeout_retry_stop_capabilities_unverified")
    if not data_gate or data_gate.get("parent_total_wall_and_remote_cancel_verified") is not True:
        reasons.append("parent_total_wall_and_independent_remote_stop_unverified")
    return {"mode": "dry_run_only", "remote_launch_available": False,
            "admission_conditions_met": not reasons, "reasons": sorted(set(reasons)),
            "gpu_type": "H100", "max_gpus": 1, "max_concurrent_jobs": 1, "max_invocations": 3,
            "planned_max_billed_seconds": seconds, "posted_resource_rate_usd_per_second": effective_rate,
            "gpu_rate_basis": {"posted_gpu_rates": POSTED_GPU_RATES, "maximum_used": max(POSTED_GPU_RATES.values()),
                               "source": POSTED_RATE_SOURCE, "verified_utc": POSTED_RATE_VERIFIED_UTC,
                               "automatic_h100_h200_upgrade_billed_at_h100": True,
                               "upgrade_billing_source": GPU_BILLING_SOURCE,
                               "maximum_rate_is_extra_conservative_not_upgrade_billing_rule": True,
                               "account_effective_rate_is_separate_parent_gate": True},
            "illustrative_compute_cost_usd": estimated, "requested_parent_reservation_usd": cost["experiment_reservation_usd"],
            "projected_global_reserved_total_usd": global_projected, "global_target_usd": 30, "global_hard_usd": 35,
            "no_endpoint": True, "no_cron": True, "min_containers": 0, "automatic_retries": 0,
            "cloud_stop_utc": budget["cloud_stop_utc"],
            "timeout_contract": {"source": TIMEOUT_SOURCE, "function_timeout_excludes_scheduling": True,
                                 "function_timeout_is_per_attempt": True, "startup_timeout_min_sdk_version": "1.1.4",
                                 "unset_startup_timeout_uses_function_timeout": True,
                                 "planned_startup_scheduling_seconds": 240, "planned_shutdown_seconds": 60,
                                 "per_job_total_wall_seconds": [row["compute_timeout_seconds"] + 300 for row in envelope["invocations"]],
                                 "parent_bounds_wall_before_submission_and_verifies_remote_stop": True,
                                 "scheduling_consumes_wall_budget_shorten_or_skip_compute": True,
                                 "sdk_actual_installed_version_verified_here": False},
            "scope": "Posted resource arithmetic only; account rates, actual billed idle/start/build/storage/egress remain parent verification gates; no credit-balance assertion"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=Path, default=ROOT / "local-runs/autonomous-rd/modal-budget.json")
    args = parser.parse_args()
    design = strict_json((ROOT / "analysis/learned-layer-design.json").read_bytes())
    budget = strict_json(args.budget.read_bytes())
    report = evaluate_admission(budget, design["bounded_modal_h100_experiment"], datetime.now(timezone.utc))
    output = ROOT / "analysis/night-learned-dialogue.modal-dryrun-v3.json"
    if not output.exists():
        freeze(output, encoded(report))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
