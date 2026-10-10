"""Bounded, read-only offline triage of customer-benchmark snapshots.

No runner/scorer imports, credential discovery, network calls, or reevaluation.
Only immediate run manifest/results and evidence/*.json files are read. Hashes
identify exact bytes read; absent/bounded-out evidence never proves agent failure.
Run: python -B integrations/customer-datasets/failure_triage.py
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

REPO = Path(__file__).resolve().parents[2]
WITHHELD = "[WITHHELD sensitive text]"
SENSITIVE = re.compile(
    r"authorization|proxy.authorization|headers?|cookies?|password|passwd|secret|"
    r"token|api.?key|private.?key|credential|\bkey\b|client.?secret", re.I)
TOKEN = re.compile(r"(?:fak_|sk-|sk_)[A-Za-z0-9_\-]+|\bBearer\s+\S+", re.I)
ACTOR = re.compile(
    r"materially different simulated customer|simulated customer.{0,180}"
    r"(?:deviat|did not follow|failed to follow)|customer behavior.{0,100}deviat", re.I | re.S)
PARSE = re.compile(r"unterminated string|json.?decode|json.{0,30}pars|"
                   r"expecting (?:value|property name|',' delimiter)|invalid json", re.I)
DIAGNOSTICS = {
    "extraction_error": "Inspect the model extraction response envelope and JSON escaping at the cited event; replay only the format boundary offline. Then rerun the unchanged hosted case. Below-floor kernel behavior is untested by this error.",
    "policy_receipt_ledger_failure": "Compare the cited recorded ledger/receipt and failed scorer checks with the unchanged case contract and ordered tool events; determine the first mismatch without changing the score.",
    "judged_actor_divergence": "Compare the judge's actor-divergence claim with the cited user turns and original actor script. Preserve the failed judge outcome; diagnose actor adherence separately.",
    "infrastructure_incomplete": "Recover or finish the bounded run/evidence collection and verify call bindings before attributing behavior. Unexecuted or missing repetitions are not agent failures.",
    "unknown": "Inspect the cited judge reason, call events, and scorer checks to establish a mechanism. Keep attribution unknown until direct evidence supports it.",
}


@dataclass(frozen=True)
class Limits:
    max_runs: int = 100
    max_files: int = 2000
    max_file_bytes: int = 16 * 1024 * 1024
    max_total_bytes: int = 128 * 1024 * 1024
    max_directory_entries: int = 4096
    max_records: int = 10000
    max_messages: int = 10000
    max_seconds: float = 45


def safe(value, depth=0, max_items=100):
    """Redact recursively, including JSON encoded inside arbitrary strings.

    Text containing sensitive fields is withheld in full, including malformed,
    escaped, nested JSON. Redact BEFORE taking excerpts so truncation cannot leak.
    """
    if depth > 16:
        return "[WITHHELD depth limit]"
    if isinstance(value, dict):
        return {WITHHELD if TOKEN.search(str(k)) else str(k):
                WITHHELD if SENSITIVE.search(str(k)) or TOKEN.search(str(k))
                else safe(v, depth + 1, max_items) for k, v in value.items()}
    if isinstance(value, list):
        selected = value if max_items is None else value[:max_items]
        return [safe(v, depth + 1, max_items) for v in selected]
    if isinstance(value, str):
        if SENSITIVE.search(value) or TOKEN.search(value):
            return WITHHELD
        # Parse nested strings only within a small bound; large text is withheld.
        if len(value) > 16384:
            return "[WITHHELD large text]"
        stripped = value.strip()
        if stripped.startswith(("{", "[", '"')):
            try:
                parsed = json.loads(stripped)
            except (ValueError, RecursionError):
                return value
            if parsed != value:
                return json.dumps(safe(parsed, depth + 1, max_items), ensure_ascii=True)
        return value
    return value if value is None or isinstance(value, (int, float, bool)) else str(value)


def excerpt(value, length=300):
    value = safe(value)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True, sort_keys=True)
    return text[:length] + ("..." if len(text) > length else "")


def linked(path):
    try:
        info = path.lstat()
        return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0)
                                        & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return False


class Reader:
    def __init__(self, root, limits):
        self.root = Path(root).absolute()
        self.limits = limits
        self.started = time.monotonic()
        self.bytes = 0
        self.sources = {}
        self.issues = []
        self.cache = {}

    def expired(self):
        return time.monotonic() - self.started >= self.limits.max_seconds

    def entries(self, directory):
        result = []
        if linked(directory):
            self.issues.append({"path": str(directory), "status": "link_refused"})
            return result
        try:
            with os.scandir(directory) as entries:
                for i, entry in enumerate(entries):
                    if i >= self.limits.max_directory_entries or self.expired():
                        self.issues.append({"path": str(directory), "status": "directory_budget_exhausted"})
                        break
                    result.append(Path(entry.path))
        except OSError:
            self.issues.append({"path": str(directory), "status": "directory_unavailable"})
        return sorted(result, key=lambda p: p.name)

    def read(self, path):
        path = Path(path).absolute()
        key = str(path)
        if key in self.cache:
            return self.cache[key]
        source = {"path": key, "relative_path": path.relative_to(self.root).as_posix(),
                  "sha256": None, "hash_method": "sha256_exact_file_bytes", "bytes": None}
        self.sources[key] = source
        data = None
        try:
            if any(linked(p) for p in (self.root, path.parent, path)):
                source["status"] = "link_refused"
            elif len(self.cache) >= self.limits.max_files or self.expired():
                source["status"] = "collection_budget_exhausted"
            else:
                before = path.stat()
                source["bytes"] = before.st_size
                if before.st_size > self.limits.max_file_bytes or self.bytes + before.st_size > self.limits.max_total_bytes:
                    source["status"] = "byte_budget_exhausted"
                else:
                    with path.open("rb") as stream:
                        raw = stream.read(min(self.limits.max_file_bytes, self.limits.max_total_bytes - self.bytes) + 1)
                    self.bytes += len(raw)
                    after = path.stat()
                    if len(raw) != before.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        source["status"] = "changed_during_read"
                    else:
                        source["sha256"] = hashlib.sha256(raw).hexdigest()
                        try:
                            data = json.loads(raw.decode("utf-8-sig"))
                            source["status"] = "read" if isinstance(data, dict) else "invalid_structure"
                            if not isinstance(data, dict):
                                data = None
                        except (UnicodeError, ValueError, RecursionError):
                            source["status"] = "invalid_or_truncated_json"
        except FileNotFoundError:
            source["status"] = "missing"
        except OSError:
            source["status"] = "unavailable"
        if source["status"] != "read":
            self.issues.append(dict(source))
        self.cache[key] = data
        return data

    def ref(self, path, pointer, value):
        source = self.sources[str(Path(path).absolute())]
        return {"path": source["path"], "sha256": source["sha256"],
                "json_pointer": pointer, "excerpt": excerpt(value)}


def integer(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def mode(manifest, call):
    scope = " ".join(str(source.get(key, "")) for source in (manifest, call)
                     for key in ("scope", "mode", "execution_mode", "execution_status", "type", "source"))
    if any(word in scope.lower() for word in ("offline", "kernel", "replay")):
        return "offline_or_kernel"
    if call.get("type") == "simulationCall":
        return "hosted_text_simulation" if call.get("modality") == "text" else "hosted_simulation_unknown_modality"
    return "voice" if call.get("modality") in ("voice", "audio") else "unknown"


def version(manifest, call):
    declared = manifest.get("tested_version", {})
    if not isinstance(declared, dict):
        declared = {}
    return {"workflow_id": call.get("assistantWorkflowId", declared.get("workflow_id")),
            "published_version_id": call.get("entityVersionId", declared.get("published_version_id")),
            "published_version_number": call.get("entityVersionNumber", declared.get("published_version_number"))}


def classify(reader, path, evidence, job):
    """Return evidence-grounded classification; never derive failure from absence."""
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    if evidence is None:
        return "infrastructure_incomplete", "missing_or_unreadable_evidence", [], []
    call, judge, ledger = (evidence.get(k) for k in ("call", "judge", "ledger"))
    binding = evidence.get("binding")
    if not all(isinstance(v, dict) for v in (call, judge, ledger, binding)):
        return "infrastructure_incomplete", "incomplete_evidence_structure", [], []
    for k in ("id", "variant_id", "rep", "call_id"):
        if job.get(k) is not None and binding.get(k) != job[k]:
            return "infrastructure_incomplete", "evidence_binding_mismatch", [], []
    cid = job.get("call_id", binding.get("call_id"))
    if not cid or call.get("id") != cid or judge.get("callId") != cid:
        return "infrastructure_incomplete", "evidence_call_binding_mismatch", [], []
    refs, types = [], []
    messages = call.get("messages")
    if not isinstance(messages, list) or len(messages) > reader.limits.max_messages:
        return "infrastructure_incomplete", "missing_or_bounded_call_events", [], []
    mechanism = None
    malformed_events = False
    terminal_seen = False
    for i, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "system":
            continue
        raw = message.get("message")
        if isinstance(raw, dict):
            event = raw
        else:
            try:
                event = json.loads(raw)
            except (ValueError, TypeError, RecursionError):
                malformed_events = True
                continue
        if not isinstance(event, dict):
            continue
        name = event.get("event", "")
        if name == "call_ended":
            terminal_seen = True
        if name == "extraction_error" or (name in ("variable_extraction_error", "extraction_failed") and event.get("error")):
            types.append("extraction_error")
            mechanism = "model_format_outer_json_parse_error" if PARSE.search(str(event.get("error", ""))) else "explicit_extraction_error"
            refs.append(reader.ref(path, f"/call/messages/{i}/message", {k: event[k] for k in ("event", "variables", "error") if k in event}))
        if name == "route_evaluated" and event.get("target") in ("safe_exit", "safe_close"):
            refs.append(reader.ref(path, f"/call/messages/{i}/message", {k: event.get(k) for k in ("event", "from_node", "target")}))
        if name in ("policy_error", "receipt_error", "ledger_error", "receipt_mismatch"):
            types.append("policy_receipt_ledger_failure")
            refs.append(reader.ref(path, f"/call/messages/{i}/message", {k: event.get(k) for k in ("event", "error")}))
    reason = judge.get("reason", "")
    if judge.get("outcome") == "fail":
        refs.append(reader.ref(path, "/judge", {"outcome": "fail", "reason": reason}))
        if ACTOR.search(str(reason)):
            types.append("judged_actor_divergence")
            # Direct user-turn evidence, referenced as claims rather than adjudication.
            users = [(i, x) for i, x in enumerate(messages) if isinstance(x, dict) and x.get("role") == "user"]
            for i, x in sorted(users, key=lambda pair: len(str(pair[1].get("message", ""))), reverse=True)[:2]:
                refs.append(reader.ref(path, f"/call/messages/{i}/message", x.get("message", "")))
    # A syntactically valid but cut-short snapshot cannot establish a behavioral
    # ledger mismatch. Explicit extraction events remain direct observations.
    if "extraction_error" not in types and (malformed_events or not terminal_seen or not isinstance(ledger.get("calls"), list)):
        return "infrastructure_incomplete", "incomplete_call_or_ledger", [], refs
    failed = result.get("pass") is False or judge.get("outcome") == "fail"
    if result.get("ledger_and_trace_pass") is False:
        types.append("policy_receipt_ledger_failure")
    if failed and ledger.get("ok") is False:
        types.append("policy_receipt_ledger_failure")
    calls = ledger.get("calls", [])
    if isinstance(calls, list):
        for i, item in enumerate(calls[:reader.limits.max_records]):
            if not isinstance(item, dict):
                continue
            receipt = item.get("result", {})
            if failed and isinstance(receipt, dict) and receipt.get("ok") is False:
                types.append("policy_receipt_ledger_failure")
                refs.append(reader.ref(path, f"/ledger/calls/{i}", {k: item.get(k) for k in ("n", "tool", "status", "result")}))
            if item.get("tool") == "close_call":
                refs.append(reader.ref(path, f"/ledger/calls/{i}", {k: item.get(k) for k in ("n", "tool", "args", "status", "result")}))
    if types or result.get("pass") is False or judge.get("outcome") == "fail":
        refs.append(reader.ref(path, "/ledger", {k: ledger.get(k) for k in ("outcome", "reason", "promises", "notes", "callbacks", "transfers")}))
    if "extraction_error" in types:
        primary = "extraction_error"
    elif "judged_actor_divergence" in types:
        primary = "judged_actor_divergence"
    elif "policy_receipt_ledger_failure" in types:
        primary = "policy_receipt_ledger_failure"
    elif malformed_events or not messages or judge.get("outcome") not in ("pass", "fail"):
        primary, mechanism = "infrastructure_incomplete", "incomplete_call_or_judge"
    elif result.get("pass") is False or judge.get("outcome") == "fail":
        primary = "unknown"
    else:
        return None, None, [], []
    return primary, mechanism or primary, sorted(set(types)), refs


def collect(root=REPO / "local-runs/customer-benchmark", limits=None):
    limits = limits or Limits()
    if any(value <= 0 for value in asdict(limits).values()):
        raise ValueError("all collection bounds must be positive")
    reader = Reader(root, limits)
    backlog = {}
    runs = []
    seen_calls = set()

    def add(kind, mechanism, manifest, job, refs, evidence=None, secondary=None):
        call = (evidence or {}).get("call", {})
        judge = (evidence or {}).get("judge", {})
        call = call if isinstance(call, dict) else {}
        judge = judge if isinstance(judge, dict) else {}
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        variant = job.get("variant_id", "unknown")
        key = (variant, kind, mechanism)
        group = backlog.setdefault(key, {
            "backlog_id": hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16],
            "case_id": job.get("id"), "variant_id": variant,
            "failure_type": kind, "mechanism": mechanism,
            "suggested_next_diagnostic": DIAGNOSTICS[kind], "occurrences": [],
        })
        occurrence = {"run_id": manifest.get("run_id"), "case_id": job.get("id"),
                      "variant_id": variant, "rep": job.get("rep"), "call_id": job.get("call_id"),
                      "source_version": version(manifest, call), "mode": mode(manifest, call),
                      "original_score_pass": result.get("pass"), "original_judge_outcome": judge.get("outcome"),
                      "original_ledger_and_trace_pass": result.get("ledger_and_trace_pass"),
                      "original_transcript_pass": result.get("transcript_pass"),
                      "agent_failure_attribution": "unknown" if kind in ("unknown", "infrastructure_incomplete", "judged_actor_divergence") else "observed_failure_mechanism_only",
                      "below_floor_kernel_outcome": "unobserved" if kind == "extraction_error" else "not_adjudicated",
                      "secondary_failure_types": secondary or [], "evidence": refs}
        if occurrence not in group["occurrences"]:
            group["occurrences"].append(occurrence)

    directories = [p for p in reader.entries(reader.root) if p.is_dir() and not linked(p)]
    if len(directories) > limits.max_runs:
        reader.issues.append({"status": "run_budget_exhausted", "unread_runs": len(directories) - limits.max_runs})
    # Newest runs win when bounded. No following paths supplied inside artifacts.
    for directory in reversed(directories[-limits.max_runs:]):
        if reader.expired():
            reader.issues.append({"status": "time_budget_exhausted", "path": str(directory)})
            break
        mp, rp = directory / "manifest.json", directory / "results.json"
        manifest = reader.read(mp)
        results = reader.read(rp)
        effective = dict(manifest or {}, run_id=directory.name)
        if results:
            effective["scope"] = str(effective.get("scope", "")) + " " + str(results.get("scope", ""))
            effective["execution_status"] = results.get("execution_status")
        jobs = (manifest or {}).get("jobs", [])
        rows = (results or {}).get("final", [])
        if not isinstance(jobs, list):
            jobs = []
        if not isinstance(rows, list):
            rows = []
        if len(jobs) > limits.max_records or len(rows) > limits.max_records:
            reader.issues.append({"path": str(directory), "status": "record_budget_exhausted"})
        jobs, rows = jobs[:limits.max_records], rows[:limits.max_records]
        ep = directory / "evidence"
        evidence_paths = [p for p in reader.entries(ep) if p.suffix == ".json" and p.is_file()]
        evidence_map = {"evidence/" + p.name: (p, reader.read(p)) for p in evidence_paths}
        refs = [reader.ref(mp, "/status", (manifest or {}).get("status")), reader.ref(rp, "/execution_status", (results or {}).get("execution_status"))]
        if manifest is None or results is None:
            add("infrastructure_incomplete", "missing_or_invalid_run_metadata", effective, {}, refs)
        by_variant = {}
        evidence_seen = set()
        for index, job in enumerate(jobs):
            if reader.expired():
                reader.issues.append({"status": "time_budget_exhausted", "path": str(mp), "json_pointer": f"/jobs/{index}"})
                break
            if not isinstance(job, dict):
                continue
            variant = job.get("variant_id", "unknown")
            by_variant.setdefault(variant, []).append(job)
            name = job.get("evidence")
            matched = evidence_map.get(name) if isinstance(name, str) else None
            if matched:
                path, evidence = matched
                evidence_seen.add(name)
            else:
                path, evidence = None, None
                # Retain a missing file's direct path, but never follow arbitrary
                # manifest paths (including traversal to credential files).
                if isinstance(name, str) and re.fullmatch(r"evidence/[A-Za-z0-9_.-]+\.json", name):
                    path = directory / name
                    reader.read(path)
            # Pending jobs with no call are coverage gaps, never individual failures.
            if not matched and not job.get("call_id") and job.get("state") != "scored":
                continue
            kind, mechanism, secondary, direct = classify(reader, path, evidence, job)
            if kind:
                direct += [reader.ref(mp, f"/jobs/{index}/result", job.get("result"))]
                if path:
                    direct.append(reader.ref(path, "/binding", {k: job.get(k) for k in ("id", "variant_id", "rep", "call_id")}))
                add(kind, mechanism, effective, job, direct, evidence, secondary)
            if kind != "infrastructure_incomplete" and evidence is not None:
                seen_calls.add((job.get("call_id"), mode(effective, evidence.get("call", {}))))
        # Retain orphan evidence as an observation without fabricating a scored job.
        for name, (path, evidence) in evidence_map.items():
            if reader.expired():
                reader.issues.append({"status": "time_budget_exhausted", "path": str(path)})
                break
            if name in evidence_seen:
                continue
            if not isinstance(evidence, dict):
                add("infrastructure_incomplete", "orphan_unreadable_evidence", effective, {}, [reader.ref(path, "", "Unreadable evidence; contents withheld")])
                continue
            binding = evidence.get("binding")
            if not isinstance(binding, dict):
                add("infrastructure_incomplete", "orphan_unbound_evidence", effective, {}, [reader.ref(path, "", "Unbound evidence")])
                continue
            job = {k: binding.get(k) for k in ("id", "variant_id", "rep", "call_id")}
            kind, mechanism, secondary, direct = classify(reader, path, evidence, job)
            if kind:
                add(kind, mechanism, effective, job, direct, evidence, secondary)
        coverage = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            variant = row.get("variant_id")
            variant_jobs = by_variant.get(variant, [])
            scored = {}
            for job in variant_jobs:
                result = job.get("result")
                if job.get("state") == "scored" and isinstance(result, dict) and isinstance(result.get("pass"), bool):
                    identity = job.get("call_id") or (effective["run_id"], variant, job.get("rep"))
                    scored.setdefault(identity, result["pass"])
            required = integer(row.get("required_repetitions", effective.get("reps")))
            unobserved = max(0, required - len(scored)) if required is not None else None
            coverage.append({"case_id": row.get("id"), "variant_id": variant,
                             "required_repetitions": required,
                             "reported_completed_repetitions": row.get("completed_repetitions"),
                             "reported_passes": row.get("passes"), "original_summary_pass": row.get("pass"),
                             "observed_scored_repetitions": len(scored),
                             "observed_passed_scores": sum(value is True for value in scored.values()),
                             "observed_failed_scores": sum(value is False for value in scored.values()),
                             "unobserved_scored_repetitions": unobserved})
            if unobserved or (required is None and row.get("pass") is False and not scored):
                add("infrastructure_incomplete", "unobserved_repetitions", effective,
                    {"id": row.get("id"), "variant_id": variant},
                    [reader.ref(rp, f"/final/{i}", row)])
        runs.append({"run_id": directory.name, "declared_run_id": (manifest or {}).get("run_id"),
                     "execution_status": (results or {}).get("execution_status"),
                     "manifest_status": (manifest or {}).get("status"), "error_code": (manifest or {}).get("error_code"),
                     "source_version": version(effective, {}), "pack_sha256": effective.get("pack_sha256"),
                     "kit_version": effective.get("verified_pack_manifest", {}).get("base_pack", {}).get("kit_version") if isinstance(effective.get("verified_pack_manifest"), dict) else None,
                     "original_pass": (results or {}).get("pass"), "original_passed": (results or {}).get("passed"),
                     "original_total": (results or {}).get("total"), "scope": (results or {}).get("scope"),
                     "observed_scored_repetitions": sum(row["observed_scored_repetitions"] for row in coverage),
                     "observed_passed_scores": sum(row["observed_passed_scores"] for row in coverage),
                     "coverage": coverage, "sources": [str(mp), str(rp)]})
    items = sorted(backlog.values(), key=lambda g: (list(DIAGNOSTICS).index(g["failure_type"]), str(g["variant_id"])))
    for group in items:
        observations = group["occurrences"]
        calls = {o["call_id"] for o in observations if o["call_id"] and group["failure_type"] != "infrastructure_incomplete"}
        group["observed_failure_calls"] = len(calls)
        group["source_run_count"] = len({o["run_id"] for o in observations})
        group["repetition_status"] = "repeated_observed" if len(calls) > 1 else "single_observed" if calls else "unobserved_or_incomplete"
    notable = []
    for group in items:
        if group["failure_type"] == "extraction_error":
            per_run = {}
            for occurrence in group["occurrences"]:
                per_run.setdefault(occurrence["run_id"], set()).add(occurrence["call_id"])
            notable.append({"failure_type": group["failure_type"], "variant_id": group["variant_id"],
                            "mechanism": group["mechanism"], "distinct_calls_by_run": {k: len(v) for k, v in per_run.items()},
                            "diagnostic_limit": "Observed model-format failure; below-floor kernel outcome remains unobserved."})
    return safe({"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
                 "input_root": str(reader.root), "limits": asdict(limits), "bytes_read": reader.bytes,
                 "collection_complete": not reader.issues, "collection_issues": reader.issues,
                 "scope": "Offline triage of original hosted artifacts; no reevaluation, no hidden-case or voice claims. Direct parse errors do not test below-floor kernel outcomes.",
                 "deduplication": "Backlog groups use variant/type/mechanism; observed failure repetitions count distinct call IDs. Source occurrences and original failed outcomes are retained.",
                 "observed_call_modes": dict(Counter(m for _, m in seen_calls)),
                 "failure_group_counts": dict(Counter(g["failure_type"] for g in items)),
                 "notable_findings": notable,
                 "runs": runs, "backlog": items, "sources": list(reader.sources.values())}, max_items=None)


def render_text(report):
    lines = ["CUSTOMER BENCHMARK FAILURE TRIAGE", report["scope"],
             "Generated: " + report["generated_at"],
             "Collection complete: " + str(report["collection_complete"]),
             "Bounds: " + json.dumps(report["limits"], sort_keys=True),
             "Observed modes: " + json.dumps(report["observed_call_modes"], sort_keys=True),
             "Repetitions are observations, never extrapolations. Original scores/judges are retained.",
             "Run original_summary counts fully satisfied variants; observed_scores counts actual call repetitions.",
             "", "TOP MODEL-FORMAT FINDINGS"]
    lines += [json.dumps(finding, sort_keys=True) for finding in report["notable_findings"]]
    lines += ["", "RUN COVERAGE"]
    for run in report["runs"]:
        lines.append(f"{run['run_id']} status={run['execution_status']} observed_scores={run['observed_passed_scores']}/{run['observed_scored_repetitions']} original_summary={run['original_passed']}/{run['original_total']} pass={run['original_pass']} version={json.dumps(run['source_version'], sort_keys=True)}")
        for row in run["coverage"]:
            lines.append(f"  {row['variant_id']}: observed scored={row['observed_scored_repetitions']} failed scores={row['observed_failed_scores']} required={row['required_repetitions']} unobserved={row['unobserved_scored_repetitions']} original pass={row['original_summary_pass']}")
    lines += ["", "DEDUPLICATED ACTIONABLE BACKLOG"]
    for group in report["backlog"]:
        lines += [f"{group['backlog_id']} {group['variant_id']} {group['failure_type']} / {group['mechanism']}",
                  f"  distinct observed failure calls={group['observed_failure_calls']}; runs={group['source_run_count']}; {group['repetition_status']}",
                  "  Next diagnostic: " + group["suggested_next_diagnostic"]]
        for occurrence in group["occurrences"]:
            lines.append("  Source: " + json.dumps({k: v for k, v in occurrence.items() if k != "evidence"}, sort_keys=True))
            for ref in occurrence["evidence"]:
                lines.append(f"    {ref['path']}#{ref['json_pointer']} sha256={ref['sha256']} excerpt={ref['excerpt']}")
    lines += ["", "SOURCE SNAPSHOT HASHES (exact bytes; null means unobserved)"]
    lines += [f"{s['path']} sha256={s['sha256']} bytes={s['bytes']} status={s['status']}" for s in report["sources"]]
    lines += ["", "COLLECTION ISSUES", json.dumps(report["collection_issues"], sort_keys=True)]
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO / "local-runs/customer-benchmark")
    parser.add_argument("--json-output", type=Path, default=REPO / "analysis/failure-triage.json")
    parser.add_argument("--text-output", type=Path, default=REPO / "analysis/failure-triage.txt")
    parser.add_argument("--max-seconds", type=float, default=45)
    args = parser.parse_args(argv)
    report = collect(args.root, Limits(max_seconds=args.max_seconds))
    args.json_output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    args.text_output.write_text(render_text(report), encoding="utf-8")
    print(json.dumps({"runs": len(report["runs"]), "backlog_groups": len(report["backlog"]),
                      "failure_types": report["failure_group_counts"], "collection_complete": report["collection_complete"]}))


if __name__ == "__main__":
    main()
