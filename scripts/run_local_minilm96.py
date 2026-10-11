"""Repeat frozen MiniLM diagnostics locally; never train, publish or call Freya.

The exposed96 cohort is semantic, with no bank fixtures. Repeats measure local
repeatability, not independent qualification. The unchanged worker additionally
executes the previously exposed384/32 regression controls and V2 ablations.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "integrations/learned-dialogue"
EVAL_SHA = "04c69c6e0e1ddeb48f40e6b7c3934a506cd0cb8690dedb98961f42d10cb65571"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def environment():
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LOCALAPPDATA",
               "APPDATA", "USERPROFILE", "USERNAME", "USERDOMAIN", "PYTHONUTF8"}
    result = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    # USERNAME is required by getpass.getuser() in PyTorch on Windows; no pwd module.
    result.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                  HF_HUB_DISABLE_TELEMETRY="1", PYTHONUTF8="1")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repeats", type=int, choices=(1, 2, 3), default=3)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("Never overwrite diagnostic evidence")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "local-runs/minilm-finetune-v2" / ("local-regression-" + stamp)
    out.mkdir(parents=True, exist_ok=False)
    anchors = {ROOT / "analysis/minilm-v2-independent-probes.json": EVAL_SHA}
    for version in ("v1", "v2"):
        release = json.loads((HERE / f"minilm_ft_{version}/release.json").read_text(encoding="utf-8"))
        anchors[HERE / f"minilm_ft_{version}/release.json"] = sha(HERE / f"minilm_ft_{version}/release.json")
        anchors[HERE / f"minilm_ft_{version}/model/manifest.json"] = release["manifest_sha256"]
        runtime = HERE if version == "v1" else HERE / "minilm_ft_v2/runtime"
        for name, digest in release["runtime_sha256"].items():
            anchors[runtime / name] = digest
    for path in (HERE / "minilm_v2_evaluate.py", ROOT / "analysis/minilm-v2-plan.json"):
        anchors[path] = sha(path)

    def verify():
        for path, digest in anchors.items():
            if sha(path) != digest:
                raise ValueError("Pinned source changed: " + str(path.relative_to(ROOT)))

    verify()
    started, results, failures = time.monotonic(), [], []
    for repeat in range(1, args.repeats + 1):
        for version in ("v1", "v2"):
            verify()
            dst = out / f"{version}-rep{repeat}.json"
            command = [sys.executable, "-X", "utf8", "-B", str(HERE / "minilm_v2_evaluate.py"),
                       "--worker", version, "--model", str(HERE / f"minilm_ft_{version}/model"),
                       "--output", str(dst)]
            try:
                done = subprocess.run(command, cwd=ROOT, env=environment(), capture_output=True,
                                      text=True, encoding="utf-8", timeout=150)
            except subprocess.TimeoutExpired:
                failures.append({"repeat": repeat, "version": version, "error": "worker_timeout"})
                break
            (out / f"{version}-rep{repeat}.stdout.txt").write_text(done.stdout, encoding="utf-8")
            (out / f"{version}-rep{repeat}.stderr.txt").write_text(done.stderr, encoding="utf-8")
            if done.returncode:
                failures.append({"repeat": repeat, "version": version, "error": "worker_failed",
                                 "returncode": done.returncode})
                break
            evidence = json.loads(dst.read_text(encoding="utf-8"))
            if evidence["fresh"]["raw"]["rows"] != 96:
                raise ValueError("Worker did not score all96")
            row = {"repeat": repeat, "version": version, "model_manifest_sha256": evidence["manifest_sha256"],
                   "device": evidence["device"], "fresh": evidence["fresh"], "fresh_groups": evidence["fresh_groups"],
                   "fresh_subsets": evidence["fresh_subsets"], "fresh_predictions": evidence["fresh_predictions"],
                   "thresholds": evidence["thresholds"], "seconds": evidence["seconds"],
                   "worker_result_sha256": sha(dst),
                   "worker_result_relative_path": dst.relative_to(ROOT).as_posix(), "bank_authority": False}
            if version == "v2":
                row["no_tail"] = evidence["fresh_no_tail_ablation"]
                row["no_context"] = evidence["fresh_no_context_ablation"]
            results.append(row)
            print(json.dumps({"version": version, "repeat": repeat, "cases": 96,
                              "raw_macro_F1": evidence["fresh"]["raw"]["domain_macro_F1"],
                              "joint": evidence["fresh"]["joint_raw"], "device": evidence["device"],
                              "seconds": round(evidence["seconds"], 3)}), flush=True)
        if failures:
            break
    verify()
    report = {"status": "INCOMPLETE" if failures else "COMPLETED_LOCAL_FROZEN_MODEL_REGRESSION",
              "finished_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "scope": "Repeated local inference on the SAME exposed authored96; deterministic repeatability, "
                       "not independent qualification or bank/voice/Freya score. Frozen worker additionally "
                       "executes reused384/32 controls, not new cases.",
              "cases": 96, "groups": 24, "requested_repeats": args.repeats,
              "model_arms": ["v1", "v2"], "actual_96_predictions": 96 * len(results),
              "source_hashes": {path.relative_to(ROOT).as_posix(): digest for path, digest in anchors.items()},
              "Freya_calls": 0, "Modal_launches": 0, "bank_authority": False, "voice_agent_pass": None,
              "classic_96_ledger_score": None, "model_or_threshold_changes": False,
              "elapsed_seconds": round(time.monotonic() - started, 3), "results": results, "failures": failures}
    report["joint_raw_identical_across_repeats"] = {
        version: len([r for r in results if r["version"] == version]) == args.repeats and
        len({(r["fresh"]["joint_raw"]["correct"], r["fresh"]["joint_raw"]["denominator"])
             for r in results if r["version"] == version}) == 1 for version in ("v1", "v2")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("status", "actual_96_predictions", "elapsed_seconds")}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
