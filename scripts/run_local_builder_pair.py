"""Local classic/V2 repair from the same real recorded speech and public seed.

Automatic builder generation, never Freya publication or simulation. Recorded
positive examples are explicitly not relabelled as failed calls. No expected
ledgers, model EVAL labels or secret-bearing system payloads enter the packet.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "competition"))
import builder

SEED = "20261011-090256-a12ce9"
REPORT = ROOT / "analysis/official-a-v10.json"
REPORT_SHA = "20f506b354a6bf62dceb261eb4bd8c593e9d79007e35ac8a234c4a74f9ce272c"
CALL_IDS = ("be3cb51b-8ce9-4b1d-bf5e-30d27edff552",
            "5a7b3e31-21f5-4c53-800d-508762e0ba27")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def observations():
    if sha(REPORT) != REPORT_SHA:
        raise ValueError("Historical report pin mismatch")
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    bound = {v["call_id"]: v for v in report["bindings"]}
    source = ROOT / report["source"]
    records, hashes = [], {REPORT.relative_to(ROOT).as_posix(): REPORT_SHA}
    for cid in CALL_IDS:
        path = source / (cid + ".json")
        saved = json.loads(path.read_text(encoding="utf-8"))["call"]
        binding = bound[cid]
        if saved["id"] != cid or saved["entityVersionNumber"] != binding["actual_version"] or saved["assistantId"] != binding["actual_agent_id"]:
            raise ValueError("Recorded call/version binding mismatch")
        messages = []
        for item in saved["messages"]:
            role = item.get("role")
            if role in ("user", "assistant") and isinstance(item.get("message"), str):
                messages.append({"role": role, "message": item["message"]})
            else:
                # Preserve actual interruption boundaries without tool arguments,
                # variable snapshots, headers, secrets or success/judge payloads.
                messages.append({"role": "system", "message": "recorded event boundary"})
        records.append({"call_id": cid, "actual_version": binding["actual_version"],
                        "scope": "Actual recorded speech, positive example; not a failed-call relabel",
                        "messages": messages})
        hashes[path.relative_to(ROOT).as_posix()] = sha(path)
    return records, hashes


class ComparisonRun(builder.Run):
    def prepare(self):
        super().prepare()
        records, hashes = observations()
        path = self.work / "previous-failed-calls.json"
        # The existing helper discovers this legacy filename. The packet and
        # prompt explicitly retain positive-example scope; it is not score data.
        builder.write_json(path, self.clean(records))
        self.recorded_packet_hash = sha(path)
        self.feedback.append({"read_file": path.name, "scope": "Real observed positive examples from same A10; legacy filename is not a failure verdict",
                              "source_hashes": hashes,
                              "instruction": "Use these actual speech turns as language examples only, not as failed scores or bank-policy truth. Preserve the current pinned policy. Apply source-general guide repairs to the existing graph and advertised extractor contract; prefer minimal repairs and finish workflow/policy/coverage promptly. No case IDs, names, fixture amounts or expected outcomes may be hardcoded. Never use model proposals as identity, permission, consent or receipt authority. Existing hosted PUB06 failure was a forbidden amount clarification and repeated overdue wording, not a ledger failure. Local generation is not proof that this hosted failure is repaired."})
        self.event("recorded_repair_examples", source_hashes=hashes, calls=len(records),
                   packet_sha256=self.recorded_packet_hash, actual_recordings=True,
                   positive_examples=True, failed_relabel=False)

    def check_pinned_evidence(self):
        super().check_pinned_evidence()
        if sha(self.work / "previous-failed-calls.json") != self.recorded_packet_hash:
            raise ValueError("Recorded language packet changed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("classic", "v2"), required=True)
    parser.add_argument("--minutes", type=float, default=8)
    parser.add_argument("--semantic-python", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Never overwrite comparison evidence")
    # A10 was generated from the active kit's unchanged CRLF bytes. Practice
    # repair requires byte identity, not just the same original ZIP text.
    command = ["builder.py", str(builder.KIT / "briefs/brief-a.md"),
               "--practice-repair", SEED, "--repair-first", "--local-only",
               "--slot", "local-pair-a-" + args.arm, "--minutes", str(args.minutes),
               "--rounds", "1", "--semantic-assist", "auto", "--dialogue-assist", "off",
               "--finetuned-assist", "off" if args.arm == "classic" else "required",
               "--finetuned-version", "v2", "--semantic-python", args.semantic_python,
               "--model", "gpt-6.1-sol"]
    old = sys.argv
    try:
        sys.argv = command
        parsed = builder.arguments()
    finally:
        sys.argv = old
    # Original builder's model child also drops credentials. This local
    # orchestration does not import or invoke freya or obtain a key.
    for name in tuple(os.environ):
        if any(word in name.upper() for word in ("API_KEY", "TEAM_KEY", "TOKEN", "SECRET", "PASSWORD")):
            os.environ.pop(name)
    with builder.slot_lock(ROOT / "competition/.state/slots" / (parsed.slot + ".lock")):
        run = ComparisonRun(parsed)
        success, failure = False, None
        try:
            success = run.execute()
        except Exception as error:
            failure = type(error).__name__
            if run.status.get("phase") != "failed":
                run.phase("failed", ended=builder.stamp(), error=run.clean(str(error)))
        events = [json.loads(line) for line in run.trace.read_text(encoding="utf-8").splitlines()]
        ready = [e for e in events if e["kind"] == "finetuned_assist" and e.get("status") == "ready"]
        result = {"status": "COMPLETED_LOCAL_VALIDATION" if success else "INCOMPLETE_OR_FAILED",
                  "arm": args.arm, "run_id": run.id, "source_seed": SEED,
                  "original_status": copy.deepcopy(run.status), "failure_type": failure,
                  "finetuned_model_ready": bool(ready), "finetuned_events": ready,
                  "recorded_examples": [e for e in events if e["kind"] == "recorded_repair_examples"],
                  "Freya_calls": 0, "published": False, "bank_score": None,
                  "scope": "One automatic local generation per arm; no hosted/voice pass rate or causal benefit claim."}
        if success:
            if args.arm == "v2" and not ready:
                raise ValueError("V2 was not actually invoked")
            result["artifact_sha256"] = {name: sha(run.work / name) for name in ("workflow.json", "policy.json", "coverage.json")}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"arm": args.arm, "run_id": run.id, "status": result["status"],
                          "finetuned_model_ready": bool(ready)}), flush=True)
        return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
