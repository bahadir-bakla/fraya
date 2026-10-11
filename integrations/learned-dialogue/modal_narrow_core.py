"""Offline, fail-closed TRAIN payload and parent reservation checks. No SDK/I/O.

Hashes bind bytes; they do not authenticate reviewers, callers or Freya turns.
The existing review assessor remains frozen. This adapter adds the user's strict
>20 positive-group floor, never weakening its 20 additional-negative-group floor.
"""
import hashlib
import json
import math
import re
from datetime import datetime, timezone, timedelta

TASK = "primary_is_payment_proposal"
FORMAT = "narrow_modal_train.v3"
MAX_BYTES = 1_000_000
MAX_ROWS = 512
MAX_TEXT = 8192
POSITIVE_FLOOR = 21
NEGATIVE_FLOOR = 20
PROFILE = "businessforever2338"
ABSOLUTE_STOP = "2026-10-11T06:13:01Z"
ROW_KEYS = {"id", "group", "split", "fictional", "input_sha256", "text", "y", "view_sha256", "source_segments", "privacy_evidence_sha256"}
PAYLOAD_KEYS = {"format", "task", "sources", "rows", "row_manifest", "contract"}
SOURCE_KEYS = {"train_sha256", "packet_sha256", "reviews_sha256", "review_authorization_sha256", "model_manifest_sha256", "adapter_contract_sha256", "source_manifest_sha256", "lineage_overlay_sha256"}
CONTRACT = {"sequence_cap": 256, "epochs": 3, "max_steps": 1000,
            "batch_size": 16, "seed": 1729, "head_lr": .001,
            "objective": "group_mean_unweighted_masked_binary_ce",
            "encoder": "frozen", "fine_tune": False,
            "positive_group_floor": POSITIVE_FLOOR,
            "additional_negative_group_floor": NEGATIVE_FLOOR,
            "qualified": False, "calibrated": False}


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def load(blob):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result
    def bad(value):
        raise ValueError("Nonfinite JSON")
    return json.loads(blob, object_pairs_hook=pairs, parse_constant=bad)


def hash_ok(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def stamp(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("UTC-aware time required")
    return result.astimezone(timezone.utc)


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def source_view(snapshot, privacy_review):
    """Minimal fictional context. No labels, model outputs or oracle spans.

    Exact identifiers are provenance only, never features. Numeric values in
    legitimate language remain language; predictions cannot authorize amounts.
    Full raw user suffix is retained; tokenizer overflow rejects the record.
    """
    if privacy_review.get("whole_turn_and_question_nonsecurity_value_free") is not True or privacy_review.get("no_account_identifiers") is not True or not hash_ok(privacy_review.get("parent_evidence_sha256")):
        raise ValueError("Reviewed value-free source eligibility required before text hash/cache")
    utterance = snapshot["utterance"]
    if utterance["source"] != "authored_fixture" or utterance["source_turn_id"] != snapshot["turn_id"] or utterance["complete_transport"] is not True:
        raise ValueError("Complete source-bound fictional TRAIN snapshot required")
    question = snapshot.get("question") or {}
    if snapshot["phase"] == "security" or question.get("role") == "security":
        raise ValueError("Security turn requires separate reviewed value-redaction overlay; no raw security cache")
    targets = snapshot.get("targets", [])
    indices = [t["index"] for t in targets]
    if any(type(i) is not int or i < 0 for i in indices) or len(set(indices)) != len(indices):
        raise ValueError("Unique actual target indices required")
    asked = question.get("target_indices", [])
    if any(type(i) is not int or i not in indices for i in asked) or len(set(asked)) != len(asked):
        raise ValueError("Question target membership mismatch")
    pending = snapshot.get("pending", [])
    by_target = {}
    for row in pending:
        index = row["target_index"]
        if type(index) is not int or index not in indices or index in by_target:
            raise ValueError("Pending target membership/uniqueness mismatch")
        by_target[index] = row
    descriptors = []
    for target in targets:
        row = by_target.get(target["index"], {})
        components = row.get("components", {})
        statuses = {name:component["status"] for name,component in sorted(components.items())}
        if any(name not in ("amount", "date", "time", "security_answer", "recipient", "allocation") or type(status) is not str for name,status in statuses.items()):
            raise ValueError("Unsupported typed component status")
        descriptors.append({"relationship":"current_question_target" if target["index"] in asked else "sibling",
                            "type":target["type"], "component_statuses":statuses,
                            "unresolved_components":sorted(row.get("unresolved_components", []))})
    # Relative relationships and nested statuses only: no product IDs, opaque
    # tokens, values or regex substitutions across typed serialized target maps.
    context = {"phase": snapshot["phase"], "question_role": question.get("role"),
               "targets":sorted(descriptors,key=canonical),
               "spoken_offer_presence":"present_unqualified" if question.get("spoken_offer_id") else "none",
               "readback_presence":"present_unqualified" if snapshot.get("active_readback") else "none"}
    segments = []
    def lexical(text, event, kind):
        pieces, cursor = [], 0
        for match in re.finditer(r"\d+",text):
            if match.start() > cursor:
                pieces.append(text[cursor:match.start()])
                segments.append({"kind":kind,"source_event_id":event,"start":cursor,"end":match.start(),"transformation":"literal"})
            pieces.append("<number>")
            segments.append({"kind":kind,"source_event_id":event,"start":match.start(),"end":match.end(),"transformation":"number_marker"})
            cursor=match.end()
        if cursor < len(text):
            pieces.append(text[cursor:])
            segments.append({"kind":kind,"source_event_id":event,"start":cursor,"end":len(text),"transformation":"literal"})
        return "".join(pieces)
    qtext=lexical(question.get("text", ""),question.get("spoken_turn_id"),"spoken_question")
    utext=lexical(utterance["text"],snapshot["turn_id"],"latest_user")
    text = "query: context: " + canonical(context).decode().strip() + "\nspoken_question: "+qtext+"\nlatest_user: " + utext
    if len(text) > MAX_TEXT:
        raise ValueError("Character overflow; suffix must not be truncated")
    return {"text":text,"source_segments":segments,"privacy_evidence_sha256":privacy_review["parent_evidence_sha256"]}


def role_text(snapshot, privacy_review):
    return source_view(snapshot,privacy_review)["text"]


def make_payload(train, eligible_rows, sources):
    originals = {r["example_id"]:r for r in train["records"]}
    rows = []
    for eligible in sorted(eligible_rows, key=lambda r:r["id"]):
        original = originals[eligible["id"]]
        if original["split"] != "train" or original["source"].get("fictional") is not True or original["lineage_group_id"] != eligible["original_group"] or original["input"] != eligible["snapshot"]:
            raise ValueError("Exact fictional TRAIN source membership required")
        view=source_view(original["input"],eligible["privacy_review"])
        rows.append({"id":eligible["id"], "group":eligible["group"], "split":"train", "fictional":True,
                     "input_sha256":digest(canonical(original["input"])), "view_sha256":digest(canonical(view)),
                     "text":view["text"], "source_segments":view["source_segments"],
                     "privacy_evidence_sha256":view["privacy_evidence_sha256"], "y":eligible["y"]})
    payload = {"format":FORMAT, "task":TASK, "sources":sources, "rows":rows,
               "row_manifest":{r["id"]:digest(canonical(r)) for r in rows}, "contract":CONTRACT}
    validate_payload(canonical(payload))
    return payload


def validate_payload(blob, expected_sha256=None):
    """Executed independently before importing Torch or downloading the model."""
    if type(blob) is not bytes or len(blob) > MAX_BYTES:
        raise ValueError("Serialized byte payload <=1MB required")
    if expected_sha256 is not None and digest(blob) != expected_sha256:
        raise ValueError("Parent payload hash mismatch")
    payload = load(blob)
    if set(payload) != PAYLOAD_KEYS or payload["format"] != FORMAT or payload["task"] != TASK or payload["contract"] != CONTRACT:
        raise ValueError("Unknown payload field/task/contract")
    if set(payload["sources"]) != SOURCE_KEYS or not all(hash_ok(v) for v in payload["sources"].values()):
        raise ValueError("Immutable source hashes required")
    if payload["sources"]["adapter_contract_sha256"] != digest(canonical(CONTRACT)):
        raise ValueError("Exact adapter objective/config hash required")
    rows = payload["rows"]
    if not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("TRAIN row count outside bounded envelope")
    ids, positive, negative = set(), set(), set()
    for row in rows:
        if set(row) != ROW_KEYS or row["split"] != "train" or row["fictional"] is not True or type(row["y"]) is not int or row["y"] not in (0, 1):
            raise ValueError("Only explicitly reviewed fictional TRAIN binary rows allowed")
        if any(type(row[k]) is not str or not row[k] or len(row[k]) > 256 for k in ("id", "group")) or row["id"] in ids:
            raise ValueError("Unique bounded source identifiers required")
        if not hash_ok(row["input_sha256"]) or type(row["text"]) is not str or not row["text"].startswith("query: context: ") or not 1 <= len(row["text"]) <= MAX_TEXT:
            raise ValueError("Bounded source text/hash required")
        if payload["row_manifest"].get(row["id"]) != digest(canonical(row)):
            raise ValueError("Row changed after manifest freeze")
        view={k:row[k] for k in ("text", "source_segments", "privacy_evidence_sha256")}
        if not hash_ok(row["privacy_evidence_sha256"]) or row["view_sha256"] != digest(canonical(view)):
            raise ValueError("Exact transformed source-view/privacy binding required")
        if type(row["source_segments"]) is not list or len(row["source_segments"]) > 512:
            raise ValueError("Explicit bounded lexical source-map required")
        for segment in row["source_segments"]:
            if set(segment) != {"kind","source_event_id","start","end","transformation"} or segment["kind"] not in ("latest_user","spoken_question") or segment["transformation"] not in ("literal","number_marker") or type(segment["source_event_id"]) is not str or not segment["source_event_id"] or type(segment["start"]) is not int or type(segment["end"]) is not int or not 0 <= segment["start"] < segment["end"] <= MAX_TEXT:
                raise ValueError("Source-map span/event/type mismatch")
        ids.add(row["id"])
        (positive if row["y"] else negative).add(row["group"])
    if set(payload["row_manifest"]) != ids:
        raise ValueError("Manifest has omitted or extraneous records")
    if len(positive) < POSITIVE_FLOOR or len(negative-positive) < NEGATIVE_FLOOR:
        raise ValueError("Reviewed class-group floor closed: need >=21 positive and >=20 additional negative")
    return payload


def admission(payload_blob, budget, grant, now):
    """Read-only reservation check; parent must serialize the global transaction.

    A local JSON grant is authorization evidence supplied by the parent, not a
    cryptographic identity proof. SDK verification never reads installed tokens.
    """
    reasons = []
    try:
        validate_payload(payload_blob, grant.get("payload_sha256"))
    except (ValueError, KeyError, TypeError):
        reasons.append("payload_or_review_group_gate_closed")
    for key in ("parent_authorized_launch", "reviewed_data_gate", "independent_annotations_verified", "parent_adjudication_verified", "effective_rates_verified", "sdk_and_stop_capabilities_verified", "independent_watchdog_armed", "dependency_image_reviewed", "gpu_benefit_over_cpu_verified", "canonical_lineage_closure_verified", "reviewed_dev_frozen", "sparse_cpu_and_phase_controls_complete", "v3_source_reference_controls_passed", "actual_detector_false_candidate_audit_passed"):
        if grant.get(key) is not True:
            reasons.append(key + "_missing")
    if budget.get("profile") != PROFILE or grant.get("profile") != PROFILE or budget.get("single_job_at_a_time") is not True or budget.get("max_gpus_per_job") != 1:
        reasons.append("profile_or_serial_gpu_contract")
    if grant.get("budget_snapshot_sha256") != digest(canonical(budget)):
        reasons.append("global_budget_snapshot_changed")
    if budget.get("actual_task_cost_verified") is not True or not all(finite(budget.get(k)) for k in ("actual_task_cost_usd", "target_usd", "hard_cap_usd")):
        reasons.append("verified_finite_global_spend_missing")
    reservations = budget.get("reservations", [])
    active = [r for r in reservations if r.get("status", "reserved") not in ("released", "closed", "cancelled")]
    reservation = next((r for r in active if r.get("reservation_id") == grant.get("reservation_id")), None)
    if any(not finite(r.get("reserved_usd")) for r in active):
        reasons.append("malformed_global_reservations")
    if not reservation or reservation.get("authorized_by_parent") is not True or not finite(reservation.get("reserved_usd")) or reservation["reserved_usd"] < 10:
        reasons.append("parent_transaction_10_dollar_reservation_missing")
    projected = budget.get("actual_task_cost_usd", 0) + sum(r.get("reserved_usd", 0) for r in active if finite(r.get("reserved_usd")))
    if projected > min(30, budget.get("target_usd", 0)) or projected > min(35, budget.get("hard_cap_usd", 0)):
        reasons.append("global_budget_cap")
    if any(r.get("status") in ("starting", "running", "stopping") for r in budget.get("invocations", [])):
        reasons.append("another_job_active")
    mode = grant.get("mode")
    compute = grant.get("compute_seconds")
    cap = 120 if mode == "smoke" else 1800 if mode == "primary" else 0
    if type(compute) is not int or not 1 <= compute <= cap or grant.get("startup_seconds") != 240 or grant.get("shutdown_seconds") != 60:
        reasons.append("bounded_timeout_contract")
    if grant.get("cloud_stop_utc") != ABSOLUTE_STOP or budget.get("cloud_stop_utc") != ABSOLUTE_STOP:
        reasons.append("absolute_cloud_stop_binding")
    safe_compute = compute if type(compute) is int and 1 <= compute <= 1800 else 0
    end = min(stamp(ABSOLUTE_STOP), now + timedelta(seconds=safe_compute+300))
    if (end-now).total_seconds() < (compute if type(compute) is int else 0)+300:
        reasons.append("insufficient_total_wall_before_absolute_stop")
    rate = grant.get("effective_resource_rate_usd_per_second")
    # H100 automatically upgrades at the same H100 price. This is an explicitly
    # extra-conservative H200-posted envelope, not a claim about upgrade billing.
    conservative_rate = .001261 + 2*.0000131 + 16*.00000222
    extras = grant.get("build_storage_egress_reserve_usd")
    if not finite(rate) or rate < conservative_rate or not finite(extras) or extras < 1:
        reasons.append("effective_rate_and_other_resource_reserve_missing")
    elif reservation and finite(reservation.get("reserved_usd")) and rate*(safe_compute+300)+extras > reservation["reserved_usd"]:
        reasons.append("resource_envelope_exceeds_reservation")
    if grant.get("automatic_retries") != 0 or grant.get("gpu") != "H100" or grant.get("invocation_ordinal") not in (1, 2, 3):
        reasons.append("manual_serial_no_retry_contract")
    return {"admitted":not reasons, "reasons":sorted(set(reasons)), "projected_global_usd":projected,
            "cancel_at_utc":(end-timedelta(seconds=60)).isoformat(),
            "hard_stop_utc":end.isoformat(), "reservation_release_allowed":False,
            "local_validation_is_not_authenticated_cloud_stop":True}
