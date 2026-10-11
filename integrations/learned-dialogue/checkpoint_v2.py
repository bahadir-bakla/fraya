"""Freeze reproducible local checkpoint evidence; no live workflow or remote I/O."""
import ast
import hashlib
import io
import json
import socket
import subprocess
import time
import unittest
from collections import Counter
from datetime import datetime, timezone
from unittest.mock import patch

from build_data import encoded, freeze
from context_v2 import BindingContext, binding_v2, candidate_spans_v2, predict_v2
from export_v2 import export_v2
from train_v2 import HERE, ROOT, load_worker_records, strict_json
from validate_v2 import validate_v2


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out = ROOT / "analysis/night-learned-dialogue.v2.checkpoint.json"
    if out.exists():
        raise ValueError("Checkpoint already frozen")
    archive = strict_json((HERE / "v1-frozen-archive.manifest.json").read_bytes())
    drift = [p for p, h in archive["files"].items() if sha(ROOT / p) != h]
    if drift or sha(HERE / "v1-frozen-archive.zip") != archive["archive_sha256"]:
        raise ValueError("Frozen v1 archive/file drift: " + str(drift))
    raw = (HERE / "model_v2.json").read_bytes()
    bundle = {"model_id": hashlib.sha256(raw).hexdigest(), "model": strict_json(raw)}
    rows = []
    for name, field in (("train", "train_sha256"), ("dev", "development_sha256")):
        records, h = load_worker_records(ROOT / ("research/customer-benchmark/context-semantic-v2-" + name + ".json"))
        if h != bundle["model"]["source_binding"][field]:
            raise ValueError("Worker data drift after model freeze")
        rows += records
    source, export = export_v2(bundle, HERE / "runtime_context_v2.py")
    imports = [node.names[0].name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import)]
    if set(imports) - {"json", "re", "datetime"}:
        raise ValueError("Unsupported runtime imports")
    namespace = {}
    cold_start = time.perf_counter()
    exec(compile(source, "context-v2-export", "exec"), {"__builtins__": __builtins__}, namespace)
    cold_ms = (time.perf_counter() - cold_start) * 1000
    parity, schema_valid, statuses, span_proposal_counts = 0, 0, Counter(), Counter()
    latencies = []
    for record in rows:
        snapshot = record["input"]
        context = BindingContext(binding_v2(snapshot), bundle["model_id"])
        start = time.perf_counter()
        with patch("builtins.open", side_effect=AssertionError("file I/O")), patch.object(socket, "socket", side_effect=AssertionError("network")), patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            proposal = predict_v2(snapshot, bundle, context)
            embedded = namespace["predict_context_embedded"](snapshot, context.binding())
        latencies.append((time.perf_counter() - start) * 1000)
        if proposal != embedded:
            raise ValueError("Export parity mismatch: " + record["example_id"])
        parity += 1
        schema_valid += validate_v2(proposal, snapshot, bundle, context)
        statuses[proposal["status"]] += 1
        for candidate in candidate_spans_v2(snapshot):
            span_proposal_counts[candidate["name"]] += 1
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=1).run(unittest.defaultTestLoader.discover(str(HERE), pattern="test*.py"))
    if not result.wasSuccessful():
        raise ValueError(stream.getvalue())
    files = sorted(p for p in HERE.iterdir() if p.is_file() and (p.name.endswith("_v2.py") or p.name in {"model_v2.json", "contract_v2.json", "interface_v2.json", "README_v2.txt", "modal_dryrun.py", "test_modal_dryrun.py", "runtime_context_v2.py"}))
    ordered = sorted(latencies)
    diagnostic = strict_json((ROOT / "analysis/night-learned-dialogue.v2.diagnostic.json").read_bytes())
    report = {"checkpoint_utc": datetime.now(timezone.utc).isoformat(), "model_id": bundle["model_id"],
              "source_binding": bundle["model"]["source_binding"], "split_integrity": diagnostic["split_integrity"],
              "offline_inspectable_model_json_bytes": len(raw), "fit_seconds": diagnostic["fit_seconds"],
              "deployment_size_basis": "Exact runtime export includes compact lossless weights, metadata, features and inference source; offline JSON is inspectable training artifact",
              "train_raw_head_accuracy": diagnostic["train"]["raw_head_accuracy"],
              "development_raw_head_accuracy": diagnostic["development"]["raw_head_accuracy"],
              "train_head_n": diagnostic["train"]["head_n"], "development_head_n": diagnostic["development"]["head_n"],
              "qualification": bundle["model"]["qualification"], "component_support": bundle["model"].get("component_support"), "calibration_fitted": False,
              "runtime_status_counts": dict(statuses), "qualified_acceptance": 0, "accepted_group_count": 0,
              "one_sided_risk_upper": None, "risk_reason": "No qualified accepted groups or IID sampling assumption established",
              "persistence_export": dict(export, parity_rows=parity, strict_schema_valid_rows=schema_valid, observed_imports=imports,
                                         actual_disk_bytes=(HERE / "runtime_context_v2.py").stat().st_size, cold_load_ms=cold_ms),
              "lexical_candidate_counts": dict(span_proposal_counts),
              "guarded_local_two_predictions_latency_ms": {"p50": ordered[len(ordered)//2], "p95": ordered[int((len(ordered)-1)*.95)],
                                                         "scope": "Includes patch setup and both native/export predictions; local research only"},
              "smoke": {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "output": stream.getvalue(),
                        "file_socket_process_access_blocked_for_all_parity_rows": True},
              "v1": {"archived_files": len(archive["files"]), "archive_sha256": archive["archive_sha256"], "byte_drift": drift,
                     "additive_export_correction": {"reported_lf_serialization_bytes": 357336, "actual_frozen_windows_file_bytes": (HERE / "runtime_embedded.py").stat().st_size,
                                                    "original_report_and_file_unchanged": True}},
              "new_file_hashes": {str(p.relative_to(ROOT)): sha(p) for p in files},
              "known_limits": ["Single-author fictional train/development proposals; no independent gold or hidden/OOD result",
                               "Component scoring uses supplied oracle spans; lexical span detection and target/clause identity remain untrained",
                               "No calibration-fit/risk/confirmation sets; all envelope decisions abstain",
                               "Raw latest-turn ingress in Freya remains unqualified; caller source enum is not authentication",
                               "No Modal job, hosted inference, live workflow change or GPU ceiling claim"]}
    freeze(out, encoded(report))
    text = "Context v2 local CPU checkpoint\n" + json.dumps({k: report[k] for k in ("checkpoint_utc", "model_id", "source_binding", "split_integrity", "train_raw_head_accuracy", "development_raw_head_accuracy", "persistence_export", "smoke", "v1", "known_limits")}, indent=2) + "\n"
    freeze(ROOT / "analysis/night-learned-dialogue.v2.checkpoint.txt", text.encode("utf8"))
    print(json.dumps({"checkpoint": str(out), "model_id": bundle["model_id"], "export": export, "parity": parity,
                      "smoke_tests": result.testsRun, "v1_drift": drift, "development": report["development_raw_head_accuracy"]}, indent=2))


if __name__ == "__main__":
    main()
