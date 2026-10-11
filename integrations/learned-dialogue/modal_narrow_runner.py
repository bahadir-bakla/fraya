"""Parent-only ephemeral run/watchdog/cancel utilities. Default is dry-run.

This worker does not execute --parent-launch/--parent-cancel. Parent owns the
reservation transaction, independent watchdog and authentication environment.
No global budget/profile file is modified; output files use exclusive creation.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from modal_narrow_core import (ABSOLUTE_STOP, PROFILE, admission, canonical, digest,
                               load, make_payload, stamp, validate_payload)


def write_new(path, value):
    with Path(path).open("xb") as handle:
        handle.write(canonical(value))
        handle.flush()
        os.fsync(handle.fileno())


def prepare(train_path, packet_path, reviews_path, authorization_path, model_path,
            dev_path, source_manifest_path, lineage_overlay_path):
    # New checkpoint05 assessor consumes reviews; does not annotate or relabel.
    from build_data import encoded
    from modal_narrow_review import assess_reviews_v3
    blobs = {"train":Path(train_path).read_bytes(), "packet":Path(packet_path).read_bytes(),
             "reviews":Path(reviews_path).read_bytes(), "authorization":Path(authorization_path).read_bytes(),
             "model":Path(model_path).read_bytes(), "dev":Path(dev_path).read_bytes(),
             "source_manifest":Path(source_manifest_path).read_bytes(), "lineage_overlay":Path(lineage_overlay_path).read_bytes()}
    values = {k:load(v) for k,v in blobs.items()}
    for key in ("packet", "reviews"):
        if blobs[key] != encoded(values[key]):
            raise ValueError("Frozen review assessor requires exact canonical packet/reviews bytes")
    if values["packet"]["source_train_sha256"] != digest(blobs["train"]):
        raise ValueError("Review packet not bound to exact TRAIN pack")
    if values["authorization"].get("packet_sha256") != digest(blobs["packet"]) or values["authorization"].get("reviews_sha256") != digest(blobs["reviews"]) or values["reviews"].get("packet_sha256") != digest(blobs["packet"]) or values["reviews"].get("task") != "primary_is_payment_proposal":
        raise ValueError("Exact packet/reviews authorization/task binding required")
    if values["lineage_overlay"].get("source_train_sha256") != digest(blobs["train"]) or values["lineage_overlay"].get("source_dev_sha256") != digest(blobs["dev"]):
        raise ValueError("Lineage overlay must pin exact TRAIN/dev bytes")
    assessment = assess_reviews_v3(values["packet"], values["reviews"], values["authorization"],
                                  values["train"], values["dev"], blobs["source_manifest"], values["lineage_overlay"])
    if not assessment["admitted"]:
        raise ValueError("Existing blind review gate closed: " + ",".join(assessment["reasons"]))
    from modal_narrow_core import CONTRACT
    sources = {"train_sha256":digest(blobs["train"]), "packet_sha256":digest(blobs["packet"]),
               "reviews_sha256":digest(blobs["reviews"]), "review_authorization_sha256":digest(blobs["authorization"]),
               "model_manifest_sha256":digest(blobs["model"]), "adapter_contract_sha256":digest(canonical(CONTRACT)),
               "source_manifest_sha256":digest(blobs["source_manifest"]), "lineage_overlay_sha256":digest(canonical(values["lineage_overlay"]))}
    return canonical(make_payload(values["train"], assessment["eligible_rows_with_canonical_group"], sources)), assessment


def dry_run(payload_blob, budget, grant, now=None):
    now = now or datetime.now(timezone.utc)
    result = admission(payload_blob, budget, grant, now)
    return dict(result, mode="dry_run", cloud_actions=0, payload_bytes=len(payload_blob),
                payload_sha256=digest(payload_blob), whole_directory_upload=False,
                remote_validator="modal_narrow_core.validate_payload before Torch import/download",
                parent_global_transaction_required=True)


def stop_commands(app_id):
    if not re.fullmatch(r"ap-[A-Za-z0-9]+", app_id):
        raise ValueError("Exact Modal app ID required; names/wildcards forbidden")
    return [[sys.executable, "-m", "modal", "app", "stop", "--yes", app_id],
            [sys.executable, "-m", "modal", "app", "list", "--json"]]


def stopped_from_listing(blob, app_id):
    # This exact table schema is verified against installed SDK 1.5.1 source.
    # Missing row/unknown/malformed response never proves termination.
    rows = load(blob)
    if type(rows) is not list:
        return False
    return any(type(row) is dict and row.get("app_id") == app_id and row.get("state") == "stopped" and str(row.get("tasks")) == "0" for row in rows)


def cancel_parent(app_id, call_id=None, subprocess_run=subprocess.run):
    commands = stop_commands(app_id)
    env = dict(os.environ, MODAL_PROFILE=PROFILE)
    cancel_attempt = None
    # Cancellation API is isolated in a timeout-bounded subprocess so a blocked
    # network RPC cannot consume the shutdown reserve. No arbitrary IDs/names.
    if call_id is not None:
        if not re.fullmatch(r"fc-[A-Za-z0-9]+", call_id):
            raise ValueError("Exact function-call ID required")
        script = "import modal,sys; modal.FunctionCall.from_id(sys.argv[1]).cancel(terminate_containers=True)"
        try:
            cancel_attempt = subprocess_run([sys.executable, "-B", "-c", script, call_id], env=env,
                                            capture_output=True, timeout=10).returncode
        except subprocess.TimeoutExpired:
            cancel_attempt = "rpc_timeout"
    try:
        stopped = subprocess_run(commands[0], env=env, capture_output=True, timeout=15).returncode == 0
        listing = subprocess_run(commands[1], env=env, capture_output=True, timeout=15)
        verified = listing.returncode == 0 and stopped_from_listing(listing.stdout, app_id)
    except (subprocess.TimeoutExpired, ValueError, TypeError):
        stopped, verified = False, False
    return {"app_id":app_id, "call_cancel_return":cancel_attempt, "app_stop_acknowledged":stopped,
            "remote_stop_verified":verified, "reservation_release_allowed":False,
            "parent_must_reconcile_billing_and_independently_confirm_stop":True}


def child_run(payload_path, budget_path, grant_path, model_path, ids_path, result_path):
    payload = Path(payload_path).read_bytes()
    budget, grant = load(Path(budget_path).read_bytes()), load(Path(grant_path).read_bytes())
    checked = admission(payload, budget, grant, datetime.now(timezone.utc))
    if not checked["admitted"]:
        raise ValueError("Parent launch gate closed: " + ",".join(checked["reasons"]))
    manifest = load(Path(model_path).read_bytes())
    if digest(canonical(manifest)) != validate_payload(payload)["sources"]["model_manifest_sha256"]:
        raise ValueError("Manifest changed after payload freeze")
    from modal_narrow_app import create_app
    app, job = create_app(grant["compute_seconds"])
    with app.run(detach=False):
        # Save ID before scheduling; then separate exact call ID immediately.
        write_new(ids_path, {"app_id":app.app_id, "payload_sha256":digest(payload)})
        call = job.spawn(payload, digest(payload), manifest, grant["compute_seconds"],
                         stamp(checked["cancel_at_utc"]).timestamp())
        write_new(str(ids_path)+".call.json", {"app_id":app.app_id, "call_id":call.object_id})
        left = stamp(checked["cancel_at_utc"]).timestamp()-time.time()
        if left <= 0:
            call.cancel(terminate_containers=True)
            raise TimeoutError("Scheduling exhausted reserved wall")
        try:
            raw_result = call.get(timeout=left)
            result = load(raw_result)
            if result["payload_sha256"] != digest(payload) or result["qualified"] is not False:
                raise ValueError("Remote result binding/qualification mismatch")
            write_new(result_path, result)
        finally:
            call.cancel(terminate_containers=True)


def supervised_parent(args):
    payload = Path(args.payload).read_bytes()
    budget, grant = load(Path(args.budget).read_bytes()), load(Path(args.grant).read_bytes())
    checked = admission(payload, budget, grant, datetime.now(timezone.utc))
    if not checked["admitted"]:
        raise ValueError("No remote action: " + ",".join(checked["reasons"]))
    if any(Path(p).exists() for p in (args.ids, str(args.ids)+".call.json", args.result)):
        raise ValueError("Run outputs must be new paths")
    child_args = [sys.executable, "-B", str(Path(__file__).resolve()), "--child", "--payload",args.payload,
                  "--budget",args.budget, "--grant",args.grant,"--model",args.model,"--ids",args.ids,"--result",args.result]
    child = subprocess.Popen(child_args, env=dict(os.environ, MODAL_PROFILE=PROFILE),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        child.wait(timeout=max(.1, stamp(checked["cancel_at_utc"]).timestamp()-time.time()))
    except subprocess.TimeoutExpired:
        child.terminate()
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            child.kill()
    finally:
        if Path(args.ids).exists():
            ids = load(Path(args.ids).read_bytes())
            call_file = Path(str(args.ids)+".call.json")
            call = load(call_file.read_bytes()).get("call_id") if call_file.exists() else None
            termination = cancel_parent(ids["app_id"], call)
        else:
            termination = {"remote_stop_verified":False, "reservation_release_allowed":False,
                           "reason":"No app ID recovered; independent parent recovery required; client exit is not stop proof"}
        write_new(str(args.ids)+".stop.json", termination)
    return dict(termination, child_exit_code=child.returncode, result_saved=Path(args.result).exists())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload")
    parser.add_argument("--budget")
    parser.add_argument("--grant")
    parser.add_argument("--model", default=str(Path(__file__).with_name("modal_narrow_model.json")))
    parser.add_argument("--ids")
    parser.add_argument("--result")
    parser.add_argument("--parent-launch", action="store_true")
    parser.add_argument("--parent-cancel", action="store_true")
    parser.add_argument("--app-id")
    parser.add_argument("--call-id")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--train")
    parser.add_argument("--dev")
    parser.add_argument("--source-manifest")
    parser.add_argument("--lineage-overlay")
    parser.add_argument("--packet")
    parser.add_argument("--reviews")
    parser.add_argument("--review-authorization")
    args = parser.parse_args()
    if args.prepare:
        blob, assessment = prepare(args.train,args.packet,args.reviews,args.review_authorization,args.model,
                                   args.dev,args.source_manifest,args.lineage_overlay)
        with Path(args.payload).open("xb") as handle:
            handle.write(blob)
        print(json.dumps({"payload_sha256":digest(blob),"bytes":len(blob),"review_assessment":{k:v for k,v in assessment.items() if k != "eligible_rows_with_canonical_group"}},indent=2))
    elif args.parent_cancel:
        print(json.dumps(cancel_parent(args.app_id, args.call_id), indent=2))
    elif args.child:
        child_run(args.payload,args.budget,args.grant,args.model,args.ids,args.result)
    elif args.parent_launch:
        print(json.dumps(supervised_parent(args), indent=2))
    else:
        report = dry_run(Path(args.payload).read_bytes(), load(Path(args.budget).read_bytes()), load(Path(args.grant).read_bytes()))
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
