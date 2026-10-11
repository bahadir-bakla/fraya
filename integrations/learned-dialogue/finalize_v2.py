"""Fixed final-handoff refit; preserves prior v2/v1 artifacts and source bytes."""
import ast
import copy
import hashlib
import io
import json
import random
import socket
import subprocess
import time
import unittest
from collections import Counter
from datetime import datetime, timezone
from unittest.mock import patch

from audit_v2 import audit_splits, verify_manifest
from build_data import encoded, freeze
from context_v2 import BindingContext, binding_v2, predict_v2, reference_candidate_v2
from export_v2 import export_v2
from train_v2 import HERE, ROOT, evaluate_v2, fit_v2, prepare_examples, strict_json
from validate_v2 import validate_v2


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def support(examples):
    result = {}
    for row in examples:
        if row["head"] == "secondary":
            continue
        component = row["candidate"]["name"] if row["candidate"] else "utterance"
        key = row["head"] + ":" + component + ":" + row["label"]
        entry = result.setdefault(key, {"rows": 0, "groups": set()})
        entry["rows"] += 1
        entry["groups"].add(row["group"])
    return {key: {"rows": row["rows"], "lineage_groups": len(row["groups"])} for key, row in result.items()}


def main():
    output = ROOT / "analysis/night-learned-dialogue.v2-final.handoff.json"
    model_path = HERE / "model_v2_final.json"
    if output.exists() or model_path.exists():
        raise ValueError("Final handoff already frozen; never overwrite")
    start = time.perf_counter()
    archive = strict_json((HERE / "v1-frozen-archive.manifest.json").read_bytes())
    if any(sha((ROOT / path).read_bytes()) != digest for path, digest in archive["files"].items()):
        raise ValueError("V1 byte drift")
    pilot_report = (ROOT / "analysis/night-learned-dialogue.v2.checkpoint.json").read_bytes()
    pilot_model = (HERE / "model_v2.json").read_bytes()
    base = ROOT / "research/customer-benchmark"
    blobs = {name: (base / ("context-semantic-v2-" + name + ".json")).read_bytes() for name in ("train", "dev", "manifest")}
    hashes = verify_manifest(strict_json(blobs["manifest"]), blobs["train"], blobs["dev"])
    snapshot = HERE / "v2-final-data"
    snapshot.mkdir(exist_ok=True)
    for name, blob in blobs.items():
        freeze(snapshot / (name + ".json"), blob)
    for name in ("json", "txt"):
        freeze(snapshot / ("worker-handoff." + name), (ROOT / ("analysis/night-context-data." + name)).read_bytes())
    author_path = ROOT / strict_json(blobs["manifest"])["authoring_source"]["path"]
    author_bytes = author_path.read_bytes()
    if sha(author_bytes) != strict_json(blobs["manifest"])["authoring_source"]["sha256"]:
        raise ValueError("Worker authoring-source drift")
    freeze(snapshot / "authoring-source.py.txt", author_bytes)
    records, dev_records = strict_json(blobs["train"])["records"], strict_json(blobs["dev"])["records"]
    integrity = audit_splits(records, dev_records)
    train, tr = prepare_examples(records, "train")
    dev, dr = prepare_examples(dev_records, "development")
    fit_start = time.perf_counter()
    model, losses = fit_v2(train, epochs=80, seed=1729, include_context=True, max_features=384)
    fit_seconds = time.perf_counter() - fit_start
    model["source_binding"] = {"train_sha256": hashes["train"], "development_sha256": hashes["development"],
                               "manifest_sha256": sha(blobs["manifest"]), "authoring_source_sha256": sha(author_bytes),
                               "snapshot_directory": "integrations/learned-dialogue/v2-final-data",
                               "qualification_labels_read": False, "independent_gold_rows": 0,
                               "experiment": "final-handoff-refit-same-80epoch-384feature-1729seed-config-no-tuning"}
    raw = encoded(model)
    bundle = {"model_id": sha(raw), "model": model}
    train_eval, dev_eval = evaluate_v2(model, train), evaluate_v2(model, dev)
    no_context, _ = fit_v2(train, epochs=80, seed=1729, include_context=False, max_features=384)
    shuffled = copy.deepcopy(train)
    rng = random.Random(4313)
    for name in sorted({row["head"] for row in shuffled}):
        selected = [row for row in shuffled if row["head"] == name]
        labels = [row["label"] for row in selected]
        rng.shuffle(labels)
        for row, label in zip(selected, labels):
            row["label"] = label
    null_model, _ = fit_v2(shuffled, epochs=80, seed=1729, include_context=True, max_features=384)
    controls = {"learned_only": dev_eval, "no_context": evaluate_v2(no_context, dev),
                "shuffled_train_labels": evaluate_v2(null_model, dev),
                "guards_only": {"raw_primary_accuracy": None, "qualified_acceptance": 0,
                                "reason": "Deterministic authority has no learned semantic classifier; no semantic acceptance"}}
    source, export = export_v2(bundle, HERE / "runtime_context_v2_final.py")
    imports = [node.names[0].name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Import)]
    if set(imports) - {"json", "re", "datetime"}:
        raise ValueError("Unqualified runtime import")
    namespace = {}
    cold_start = time.perf_counter()
    exec(compile(source, "context-v2-final", "exec"), {"__builtins__": __builtins__}, namespace)
    cold_ms = (time.perf_counter() - cold_start) * 1000
    statuses, runtime_rows, parity = Counter(), [], 0
    for record in records + dev_records:
        state = record["input"]
        context = BindingContext(binding_v2(state), bundle["model_id"])
        with patch("builtins.open", side_effect=AssertionError("file")), patch.object(socket, "socket", side_effect=AssertionError("socket")), patch.object(subprocess, "Popen", side_effect=AssertionError("process")):
            proposal = predict_v2(state, bundle, context)
            embedded = namespace["predict_context_embedded"](state, context.binding())
        if proposal != embedded:
            raise ValueError("Parity mismatch: " + record["example_id"])
        validate_v2(proposal, state, bundle, context)
        parity += 1
        statuses[proposal["status"]] += 1
        runtime_rows.append({"id": record["example_id"], "split": record["split"], "raw_primary": proposal["primary"]["label"] if proposal["primary"] else None,
                             "status": proposal["status"], "reasons": [a["reason"] for a in proposal["abstentions"]]})
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream).run(unittest.defaultTestLoader.discover(str(HERE), pattern="test*.py"))
    if not result.wasSuccessful():
        raise ValueError(stream.getvalue())
    if (HERE / "model_v2.json").read_bytes() != pilot_model or (ROOT / "analysis/night-learned-dialogue.v2.checkpoint.json").read_bytes() != pilot_report:
        raise ValueError("Pilot v2 drift")
    if any(sha((ROOT / path).read_bytes()) != digest for path, digest in archive["files"].items()):
        raise ValueError("V1 byte drift after fit")
    freeze(model_path, raw)
    freeze(ROOT / "analysis/night-learned-dialogue.v2-final.train.json", encoded({"model_id": bundle["model_id"], "epoch_head_losses": losses, "metrics": train_eval, "data": tr, "support": support(train)}))
    freeze(ROOT / "analysis/night-learned-dialogue.v2-final.dev.json", encoded({"model_id": bundle["model_id"], "metrics": dev_eval, "data": dr, "support": support(dev)}))
    freeze(ROOT / "analysis/night-learned-dialogue.v2-final.controls.json", encoded(controls))
    freeze(ROOT / "analysis/night-learned-dialogue.v2-final.runtime.json", encoded({"rows": runtime_rows, "export": export}))
    weak_stops = [row for row in runtime_rows if next(r for r in records + dev_records if r["example_id"] == row["id"])["labels"]["primary_intent"] == "stop_request"]
    refs = [{"id": r["example_id"], "reference_diagnosis": reference_candidate_v2(r["input"], "readback_affirmation")}
            for r in records if r["labels"]["primary_intent"] == "readback_affirmation"]
    label_review = [r for r in records if r["example_id"].replace('-', '').endswith('E0025') or r["example_id"] == "CSv2-E-0025"]
    sources = strict_json((ROOT / "research/customer-benchmark/learned-dialogue-data.sources.json").read_bytes())
    changed = [p for p in HERE.rglob('*') if p.is_file() and p.relative_to(ROOT).as_posix() not in archive["files"] and '__pycache__' not in p.parts]
    report = {"status": "Frozen offline diagnostic only; not calibration, qualification or deployment", "utc": datetime.now(timezone.utc).isoformat(),
              "model_id": bundle["model_id"], "model_file": model_path.relative_to(ROOT).as_posix(), "offline_model_json_bytes": len(raw),
              "source_binding": model["source_binding"], "frozen_schema_sha256": sha((HERE / 'contract_v2.json').read_bytes()),
              "interface": "integrations/learned-dialogue/interface_v2.json", "wire": "semantic_proposal.v1",
              "train_data": tr, "development_data": dr, "split_integrity": integrity, "fit_seconds": fit_seconds,
              "train_raw_accuracy": train_eval["raw_head_accuracy"], "development_raw_accuracy": dev_eval["raw_head_accuracy"],
              "controls_raw_accuracy": {k:v["raw_head_accuracy"] for k,v in controls.items() if "raw_head_accuracy" in v},
              "component_support": model['component_support'], "observed_train_label_support": support(train), "observed_development_label_support": support(dev),
              "qualified_accepted_groups": 0, "risk_upper": None, "runtime_status_counts": dict(statuses),
              "export": dict(export, actual_disk_bytes=(HERE / 'runtime_context_v2_final.py').stat().st_size, parity_rows=parity, strict_schema_valid_rows=parity, cold_load_ms=cold_ms),
              "smoke": {"tests": result.testsRun, "failures": 0, "errors": 0, "no_file_socket_process_for_all_parity_rows": True, "output": stream.getvalue()},
              "preservation": {"v1_files_byte_verified": len(archive['files']), "v1_archive_sha256": archive['archive_sha256'], 'pilot_v2_model_sha256':sha(pilot_model),'pilot_v2_checkpoint_sha256':sha(pilot_report),'byte_drift':[]},
              "specific_diagnostics": {"stop_training_rows": weak_stops, "readback_reference_rows": refs,
                                       "CSv2_E0025_label_review_pending_literal_snapshot": [r['labels'] for r in label_review]},
              "data_sources_license": {'v1_banking77':sources['banking77'],'v2':strict_json(blobs['manifest'])['license']},
              "remaining_questions": [
                  'Authenticated current-turn code ingress and freshness remain unqualified; conversation template or caller source enum is not authentication.',
                  'Primary-is-payment-proposal binary subset may be next; first independently blind review/adjudicate >=20 positive and >=20 negative TRAIN groups with hard negatives. Negative means not this PRIMARY, not no payment or permission. No such review occurred here.',
                  'Resolve CSv2-E-0025 next-week linguistic completeness versus date normalization uncertainty in a new label version or explicit mask; frozen labels unchanged.',
                  'Component scoring uses oracle spans. Absent/no-evidence and discontinuous spans are masked. Development lacks complete amount/security/allocation, resolved offer references and affirmative/qualified consent; rare/critical heads remain unqualified.',
                  'Secondary empty-set, polarity asserted and completion complete baselines can explain high/low marginal scores; no scope competence or CPU ceiling claim.',
                  'Clause/target/correction relations and permutation-invariant nonconflicting joins are untrained; correction ordering must follow raw speech spans/relations, never array order.',
                  'Define readback validity across revision advance and component-specific opaque deferred-refusal revisions; current strict readback binding remains conservative.',
                  'Separate independent calibration-fit/risk/confirmation after freeze. Disjoint authored lineages alone do not establish IID; zero qualified groups gives no risk estimate.',
                  'No cloud readiness or reservation authorized here; parent owns actual SDK/rates/wall/cancellation/budget gates. Automatic H100-to-H200 upgrade retains H100 GPU billing; max-H200 estimate is extra conservative.'
              ], "changed_file_hashes": {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in changed},
              "total_checkpoint_seconds": time.perf_counter()-start,
              "no_live_workflow_permission_api_external_inference_changes": True}
    freeze(output, encoded(report))
    freeze(ROOT / "analysis/night-learned-dialogue.v2-final.handoff.txt", ("Frozen context sparse v2 final handoff\n" + json.dumps({k:report[k] for k in ('utc','model_id','source_binding','train_raw_accuracy','development_raw_accuracy','controls_raw_accuracy','export','smoke','remaining_questions')}, indent=2) + '\n').encode())
    print(json.dumps({k:report[k] for k in ('model_id','source_binding','fit_seconds','development_raw_accuracy','controls_raw_accuracy','export','smoke','total_checkpoint_seconds')}, indent=2))


if __name__ == '__main__':
    main()
