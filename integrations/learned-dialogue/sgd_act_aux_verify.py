"""Artifact/runtime checks without reopening or selecting on EVAL source data."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "analysis"


def pin(path):
    raw = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as f:
        f.write(value)


def main():
    receipt = json.loads((OUT / "sgd-act-aux-receipt.json").read_bytes())
    checked = []
    for item in receipt["files"]:
        assert pin(ROOT / item["path"]) == item
        checked.append(item["path"])
    report_path = ROOT / receipt["report"]["path"]
    assert pin(report_path) == receipt["report"]
    report = json.loads(report_path.read_bytes())
    for arm in report["fit"]["presentations_per_head"].values():
        for act, n in arm.items():
            stats = report["data"]["TRAIN"]["per_class"][act]
            assert n == 3 * (stats["positive"] + stats["negative"])
    spec = importlib.util.spec_from_file_location("sgd_aux_verify_runtime", HERE / "sgd_act_aux_runtime.py")
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    weights = HERE / "sgd_act_aux_weights.json"
    calibration = HERE / "sgd_act_aux_calibration.json"
    proposer = runtime.ActProposer(weights, calibration, receipt["weights"]["sha256"], receipt["calibration"]["sha256"])
    observed = {"speaker": "USER", "utterance": "Yes, that works for me.",
                "earlier_context": [{"speaker": "USER", "text": "An older observed turn"},
                                    {"speaker": "SYSTEM", "text": "Would you like that option?"}]}
    expected = proposer.propose(observed)
    changed = {**observed, "earlier_context": [{"speaker": "USER", "text": "Poison older context: negate request"}, observed["earlier_context"][-1]],
               "targets": {"frames": [{"actions": [{"act": "NEGATE"}]}]}, "current_gold": "transfer approved"}
    assert proposer.propose(changed) == expected
    assert expected["bank_authority"] is None and expected["financial_authorization"] == "UNKNOWN"
    invalid_rejected = 0
    for bad in ({}, {"speaker": "SYSTEM", "utterance": "yes", "earlier_context": []},
                {"speaker": "USER", "utterance": None, "earlier_context": []}):
        try:
            proposer.propose(bad)
        except ValueError:
            invalid_rejected += 1
    assert invalid_rejected == 3
    try:
        runtime.ActProposer(weights, calibration, "0" * 64)
        raise AssertionError("Wrong hash accepted")
    except ValueError:
        pass
    # Isolated interpreter excludes site packages: the actual proposal must run.
    code = "import runpy,sys,json; m=runpy.run_path(sys.argv[1]); p=m['ActProposer'](sys.argv[2],sys.argv[3],sys.argv[4],sys.argv[5]); r=p.propose({'speaker':'USER','utterance':'Yes please','earlier_context':[{'speaker':'SYSTEM','text':'Would you like this?'}]}); assert r['bank_authority'] is None; assert not any(x in sys.modules for x in ['numpy','scipy','sklearn']); print('stdlib-only proposal passed')"
    child = subprocess.run([sys.executable, "-I", "-S", "-B", "-c", code,
                            str(HERE / "sgd_act_aux_runtime.py"), str(weights), str(calibration),
                            receipt["weights"]["sha256"], receipt["calibration"]["sha256"]],
                           check=True, capture_output=True, text=True, timeout=10)
    checks = {"status": "passed", "artifact_pins_verified": checked,
              "three_epochs_all_known_TRAIN_rows_every_head": True,
              "older_context_and_target_injection_invariant": True,
              "malformed_observed_inputs_rejected": invalid_rejected,
              "wrong_weights_hash_rejected": True, "isolated_stdlib_runtime": child.stdout.strip(),
              "EVAL_source_reopened": False, "EVAL_selection_or_refit": False,
              "verifier": pin(Path(__file__)), "report": pin(report_path)}
    write(OUT / "sgd-act-aux-verification.json", json.dumps(checks, indent=2, sort_keys=True) + "\n")
    lines = ["Completed actual SGD source USER-act CPU fit.",
             "INTERNAL DIAGNOSTIC ONLY: TRAIN-derived EVAL was previously exposed by other experiments.",
             "Official SGD TRAIN only. Official dev/test unused. AFFIRM is never financial authorization.",
             "Historical MiniLM 90/95 figures concern B77 topics, not these source acts or bank permission/Freya.",
             "", "Counts: TRAIN 132615; CAL 16072; EVAL 16295. All shard bytes/SHA/counts streamed freshly.",
             "TRAIN groups 9933; CAL 1614; EVAL 1614; group overlap 0.",
             "Fit: 3 epochs; 4 independent log-loss SGD heads per arm; context and no-context arms.",
             f"Optimizer fit wall {report['fit']['fit_wall_seconds']:.6f}s; fit CPU {report['fit']['fit_cpu_seconds']:.6f}s; data/fit/CAL/EVAL run wall {report['job_wall_seconds']:.6f}s.",
             "Features: observed current utterance + immediately preceding SYSTEM text only; role-prefixed word1-2 hashing, 4096 dimensions, signed L2.",
             "Weights: group-balanced; positive multipliers computed only on TRAIN; decimal JSON 7 significant digits; 359899 bytes including both arms.",
             "CAL: max positive coverage at empirical precision >=95%; no minimum support floor; weights already frozen.",
             "EVAL: one source streaming/scoring phase after CAL freeze; no selection/refit.", ""]
    for split in ("TRAIN", "CAL", "EVAL"):
        lines.append(split + " per-act positive/negative/unknown:")
        for act in runtime.ACTS:
            s = report["data"][split]["per_class"][act]
            lines.append(f"  {act}: {s['positive']}/{s['negative']}/{s['unknown']}")
    def pct(v):
        return "undefined" if v is None else f"{100 * v:.3f}%"
    for arm in ("context", "no_context"):
        lines += ["", "EVAL " + arm + " (precision / recall / positive-proposal coverage):"]
        for act in runtime.ACTS:
            m = report["EVAL"][arm][act]
            raw, accepted = m["raw"], m["accepted"]
            lines.append(f"  {act}: raw {pct(raw['precision'])} / {pct(raw['recall'])} / {pct(raw['coverage_known'])}; accepted {pct(accepted['precision'])} / {pct(accepted['recall'])} / {pct(accepted['coverage_known'])}")
    lines += ["", "Context raises AFFIRM accepted recall 22.344% -> 79.593% and enables NEGATE accepted recall 68.041% (baseline threshold unavailable).",
              "INFORM/REQUEST accepted recall is slightly lower with context; 95% CAL precision does not guarantee 95% EVAL precision.",
              "Observed-only controls, frozen context thresholds (accepted precision / recall / coverage):"]
    for name, results in report["observed_only_negative_controls"].items():
        lines.append("  " + name)
        for act in runtime.ACTS:
            m = results[act]["accepted"]
            lines.append(f"    {act}: {pct(m['precision'])} / {pct(m['recall'])} / {pct(m['coverage_known'])}")
    lines += ["Context-only control still proposes acts: learned source dialogue priors exist. Shuffled context degrades AFFIRM/NEGATE. These are diagnostics, not evidence of bank authority.",
              f"Stdlib runtime probability parity max error {report['checks']['runtime_probability_parity_max_abs_error']:.3g} on 256 stored EVAL witnesses; site-packages-free interpreter check passed.",
              "", "Runtime usage:",
              "  from sgd_act_aux_runtime import ActProposer",
              "  proposer = ActProposer(weights_path, calibration_path, expected_weights_sha256, expected_calibration_sha256)",
              "  proposal = proposer.propose({'speaker':'USER','utterance':current_text,'earlier_context':[{'speaker':'SYSTEM','text':previous_system_text}]})",
              "  Nonaccepted positives remain UNKNOWN. Financial authorization always UNKNOWN; bank_authority and ledger_truth are None.",
              "", "Changed files and exact SHA256:"]
    owned = sorted(HERE.glob("sgd_act_aux_*")) + sorted(OUT.glob("sgd-act-aux-*"))
    for path in owned:
        if path.is_file():
            p = pin(path)
            lines.append(f"  {p['path']} ({p['bytes']} bytes) {p['sha256']}")
    lines += ["", "Raw matrices/targets/scores are under ignored local-runs/customer-benchmark-sgd-act-aux/; their hashes are in the report.",
              "No changes made to Hooke repayment files, frozen existing files, builder/data/Freya/Git/keys/Modal."]
    handoff = OUT / "sgd-act-aux-handoff.txt"
    write(handoff, "\n".join(lines) + "\n")
    final = {"verification": pin(OUT / "sgd-act-aux-verification.json"), "handoff": pin(handoff),
             "files": [pin(p) for p in sorted(HERE.glob("sgd_act_aux_*")) + sorted(OUT.glob("sgd-act-aux-*")) if p.is_file()]}
    write(OUT / "sgd-act-aux-handoff-receipt.json", json.dumps(final, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"verification": checks['status'], "files": len(final['files']) + 1,
                      "report": pin(report_path), "handoff": pin(handoff)}, indent=2))


if __name__ == "__main__":
    main()
