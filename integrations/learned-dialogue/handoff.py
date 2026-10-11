"""Content-addressed first CPU handoff. Never changes original evidence."""
import hashlib
import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

from build_data import encoded, freeze
from inference import HEADS
from train_eval import HERE, PREFIX, ROOT, load_data, read_json


def main():
    records, oracle, manifest, check = load_data()
    original_eval = read_json(ROOT / "analysis/night-learned-dialogue.eval.json")
    original_train = read_json(ROOT / "analysis/night-learned-dialogue.train.json")
    controls = read_json(ROOT / "analysis/night-learned-dialogue.smoke.json")
    export = read_json(ROOT / "analysis/night-learned-dialogue.export.json")
    paths = sorted(list(HERE.glob("*.py")) + [HERE / "README.md", HERE / "model.json"]
                   + list(PREFIX.parent.glob("learned-dialogue-data.*"))
                   + [ROOT / "analysis" / ("night-learned-dialogue." + suffix) for suffix in ("train.json", "eval.json", "smoke.json", "export.json")])
    hashes = {str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern="test_*.py")
    results = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    holdout = original_eval["holdout"]
    held_by_id = {r["id"]: r for r in records if r["split"] == "holdout"}
    accepted_families = {held_by_id[r["id"]]["scenario_family"] for r in holdout["rows"] if not r["abstain"]}
    handoff = {"created_utc": datetime.now(timezone.utc).isoformat(),
               "first_work_started_utc": "2026-10-11T01:27:34Z", "status": "usable_offline_cpu_prototype_smoke_complete",
               "interface": {"call": "predict(input_snapshot, model_bundle) -> SemanticProposal v1",
                             "module": "integrations/learned-dialogue/inference.py",
                             "required_input": ["utterance", "turn_id", "state_revision", "policy_hash", "raw_text_provenance"],
                             "semantic_candidate_fields": list(HEADS),
                             "binding": ["turn_id", "state_revision", "policy_hash", "input_sha256"],
                             "qualification": "research_only always true; external reducer/policy permission unaffected",
                             "components": "Lexical evidence only, untrained target/component completion/polarity/correction/consent masks; no canonical values",
                             "exception_contract": "Invalid input or bundle is rejection; caller must retain existing guards and treat as abstention"},
               "data": {"counts": manifest["split_counts"], "oracle_sha256": manifest["oracle_sha256"], "records_sha256": manifest["record_sha256"],
                        "sources": "research/customer-benchmark/learned-dialogue-data.sources.json",
                        "license": "Official PolyAI Banking77 pinned CC-BY-4.0 notice actually hash-verified",
                        "source_scope": "Four public samples rewritten as fictional training inspiration only; no raw sample text or customer facts uploaded",
                        "independence_limit": "Same Sol author across packs. Source-pack/family disjointness is mechanically verified; author-independent source/semantic OOD qualification remains unmet. No augmentation used."},
               "actual_metrics": {"fit_seconds_original": original_train["fit_seconds"], "train_raw_joint_exact": original_train["pre_calibration_raw_metrics"]["raw_joint_exact_accuracy"],
                                  "holdout_n": holdout["n"], "holdout_raw_head_accuracy": holdout["raw_head_accuracy"], "holdout_raw_joint_exact_accuracy": holdout["raw_joint_exact_accuracy"],
                                  "holdout_accepted": holdout["accepted"], "holdout_coverage": holdout["coverage"], "accepted_errors": holdout["accepted_joint_errors"],
                                  "accepted_error_row_wilson_95_upper": holdout["accepted_error_wilson_95_upper"],
                                  "uncertain_abstained": holdout["uncertain_abstained"], "uncertain_n": holdout["uncertain_n"],
                                  "accepted_declared_scenario_groups": len(accepted_families),
                                  "zero_error_one_sided_95_upper_if_groups_independent": 1 - .05 ** (1 / len(accepted_families)) if accepted_families else None,
                                  "bound_is_qualification": False},
               "smoke": {"tests_run": results.testsRun, "failures": len(results.failures), "errors": len(results.errors), "skips": len(results.skipped),
                         "passed": results.wasSuccessful(), "interpreter": sys.executable, "output": stream.getvalue()},
               "controls_summary": {"guards_only_uncertainty_recall": controls["guards_only"]["uncertainty_abstention_recall"],
                                    "shuffled_raw_joint_exact": controls["shuffled_train_labels_fixed_calibration"]["raw_joint_exact_accuracy"],
                                    "shuffled_accepted_errors": controls["shuffled_train_labels_fixed_calibration"]["accepted_joint_errors"],
                                    "scope": "Already inspected v1 holdout reused diagnostically; no unseen test claim"},
               "export": export, "latency": controls["latency"], "split_integrity": check,
               "changed_files": list(hashes), "file_sha256": hashes,
               "protected_artifacts_unchanged": controls["v1_artifacts_preserved"] and hashes["integrations/learned-dialogue/model.json"] == original_eval["model_sha256"],
               "v2_review_questions": ["Adjudicated context/phase/question/spoken-offer labels and immutable offer revision references", "Completion, polarity and correction scope as independent dimensions", "Multilabel administrative acts and explicit untrained/missing-label masks", "Independent authors and connected template/source/scenario lineage across development/calibration-fit/calibration-risk/confirmation", "Trusted latest delivered raw-turn runtime binding and competition eligibility", "Component/target/offer ranking coverage and deterministic reducer contract"],
               "modal_gate": "Adapter preparation only after Astra objective/data/eval recommendation. No GPU start until parent records verified account auth plus job reservation under shared $35 hard total cap.",
               "actions_performed": "Local stdlib data freezing, training, scoring, tests and export only; no Freya calls, live workflow/guide/currentcandidate edits, external runtime inference, GPU, install, secrets or commits"}
    if not results.wasSuccessful() or not handoff["protected_artifacts_unchanged"]:
        raise SystemExit("Handoff verification failed")
    freeze(ROOT / "analysis/night-learned-dialogue.handoff.json", encoded(handoff))
    text = ("CPU learned dialogue v1 first handoff\n"
            "20/20 smoke tests pass; all original model/train/eval snapshots preserved.\n"
            "52 train / 22 calibration / 22 holdout; pre-fit hash-pinned synthetic oracle.\n"
            "Holdout raw joint: 10/22 (45.45%). Accepted: 4/22 (18.18%), zero observed accepted errors.\n"
            "Row Wilson 95% upper accepted-error bound: 48.99%; exploratory only. Uncertain abstained: 13/13.\n"
            "Export: 357336 UTF-8 bytes, 31131 lossless coefficients, json/re imports only; 96/96 decisions match.\n"
            "Full interface, hashes, changed files, source/license, control/latency evidence and V2 questions: .handoff.json.\n"
            "README: integrations/learned-dialogue/README.md. CLI and reproducible test commands are documented there.\n"
            "Shared author/templates and reused calibration prevent qualification. No bank-policy/generalization/Freya runtime success claim.\n"
            "Modal GPU starts remain parent-owned auth+budget-gated.\n")
    freeze(ROOT / "analysis/night-learned-dialogue.handoff.txt", text.encode())
    print(json.dumps({"tests": results.testsRun, "passed": results.wasSuccessful(), "original_artifacts_preserved": handoff["protected_artifacts_unchanged"],
                      "changed_files": handoff["changed_files"], "handoff": "analysis/night-learned-dialogue.handoff.json"}, indent=2))


if __name__ == "__main__":
    main()
