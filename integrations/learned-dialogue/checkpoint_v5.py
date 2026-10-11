"""Hash-bound authorized primary CPU checkpoint; no new DEV or remote calls."""
import argparse
import ast
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import alignment_v5
import primary_cpu_v5 as cpu

ROOT = cpu.admission.ROOT
TRUSTED_MODULE_SHA = "a0ad8167f422c02d1b7f4f3007b7f272c45bd8fe2c6dcbdcfa7dc4673bd3d12d"


def save_new(path, value):
    path = ROOT / path
    with path.open("xb") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n")
    return cpu.admission.sha(path.read_bytes())


def exported_source():
    def functions(path, names):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        return "\n\n".join(ast.get_source_segment(source, n) for n in tree.body
                           if isinstance(n, ast.FunctionDef) and n.name in names)
    surface = functions(Path(alignment_v5.__file__), {"replay_surface_admission"})
    runtime = functions(Path(cpu.__file__), {"features", "sigmoid", "predict"})
    runtime = runtime.replace("math.exp(-max(-40., min(40., z)))", "2.718281828459045 ** (-max(-40., min(40., z)))")
    runtime = runtime.replace("not math.isfinite(z)", "not -float('inf') < z < float('inf')")
    return "import json\nimport re\nVERSION=" + repr(cpu.VERSION) + "\n\n" + surface + "\n\n" + runtime + "\n"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--authorization", required=True)
    p.add_argument("--trusted-authorization-sha256", required=True,
                   help="Trust anchor received separately from parent; never derive from receipt")
    p.add_argument("--splits", required=True)
    args = p.parse_args()
    started = time.monotonic()
    module_sha = cpu.admission.sha(Path(cpu.admission.__file__).read_bytes())
    if module_sha != TRUSTED_MODULE_SHA:
        raise ValueError("admission_module_hash_changed")
    auth_raw = (ROOT / args.authorization).read_bytes()
    if cpu.admission.sha(auth_raw) != args.trusted_authorization_sha256:
        raise ValueError("external_parent_authorization_hash_mismatch")
    splits_raw = (ROOT / args.splits).read_bytes()
    splits = cpu.admission.strict_json(splits_raw)
    raw = cpu.admission.load_allowed_inputs()
    assessment = cpu.admission.assess_admission(raw, authorization_raw=auth_raw,
                    trusted_authorization_sha256=args.trusted_authorization_sha256,
                    candidates=None, split_assignments=splits)
    if not assessment["admitted"] or not assessment["head_admission"]["primary"]["admitted"]:
        raise ValueError("parent_primary_admission_failed:" + str(assessment["reasons"]))
    sources = [Path(__file__), Path(cpu.__file__), Path(alignment_v5.__file__), Path(cpu.admission.__file__)]
    source_hashes = {str(f.relative_to(ROOT)).replace("\\", "/"):cpu.admission.sha(f.read_bytes()) for f in sources}
    freeze = {"schema_version":"primary_cpu_train_freeze.v5", "utc":datetime.now(timezone.utc).isoformat(),
            "authorization_raw_sha256":args.trusted_authorization_sha256, "source_sha256":source_hashes,
            "source_raw_sha256":assessment["source_raw_sha256"], "splits_raw_sha256":cpu.admission.sha(splits_raw),
            "split_assignments_sha256":assessment["split_assignments_sha256"],
            "feature_version":cpu.VERSION, "epochs":cpu.EPOCHS,"feature_cap":cpu.CAP,"l2":cpu.L2,
            "optimizer":"full batch gradient; lr .8; zero initialization; group-mean unweighted CE",
            "folds":"sha256('predeclared-v5:'+canonical_group) modulo5",
            "controls":list(cpu.MODES), "new_dev_read":False,"qualified":False,"payment_authority":False}
    save_new("analysis/night-learned-dialogue.v5.train-freeze.json", freeze)
    result = cpu.authorized_experiment(raw, auth_raw, args.trusted_authorization_sha256, None, splits)
    bundle = result.pop("final_bundle")
    bundle["training_freeze_sha256"] = cpu.admission.sha((ROOT / "analysis/night-learned-dialogue.v5.train-freeze.json").read_bytes())
    model_sha = save_new("integrations/learned-dialogue/model_primary_v5.json", bundle)
    runtime = exported_source()
    runtime_path = ROOT / "integrations/learned-dialogue/runtime_primary_v5.py"
    with runtime_path.open("x",encoding="utf-8",newline="\n") as f:
        f.write(runtime)
    ns = {}
    exec(compile(runtime, str(runtime_path), "exec"), ns)
    rows = assessment["eligible_rows"]["primary"]
    parity = 0
    for row in rows:
        native = cpu.predict(row["snapshot"], bundle)
        exported = ns["predict"](row["snapshot"], bundle)
        if native.get("raw_score") != exported.get("raw_score") or native["decision"] != exported["decision"]:
            raise ValueError("runtime_score_parity_failed")
        if native["probability_uncalibrated"] is not None and abs(native["probability_uncalibrated"]-exported["probability_uncalibrated"])>1e-12:
            raise ValueError("runtime_probability_parity_failed")
        if cpu.features(row["snapshot"],bundle["mode"]) != ns["features"](row["snapshot"],bundle["mode"]):
            raise ValueError("runtime_feature_mask_parity_failed")
        parity += 1
    model_bytes = (ROOT / "integrations/learned-dialogue/model_primary_v5.json").stat().st_size
    runtime_bytes = runtime_path.stat().st_size
    if model_bytes+runtime_bytes>500000:
        raise ValueError("serialized_bundle_exceeds_500KB")
    result.update({"model_sha256":model_sha,"model_bytes":model_bytes,"runtime_bytes":runtime_bytes,
            "runtime_sha256":cpu.admission.sha(runtime_path.read_bytes()),"native_export_comparisons":parity,
            "authorization_raw_sha256":args.trusted_authorization_sha256,"source_sha256":source_hashes,
            "total_checkpoint_seconds":time.monotonic()-started,"accepted_outputs":0,
            "limits":["TRAIN-internal fixed-fold diagnostics; no DEV/holdout or calibration.",
                      "Provisional machine engineering supervision; zero human/IID gold.",
                      "No canonical policy values, consent, permission or live ingress qualification.",
                      "DATE fitting unauthorized; source alignment is a separate diagnostic."]})
    metrics_sha = save_new("analysis/night-learned-dialogue.v5.primary-cpu.json", result)
    metrics = {mode:{k:v for k,v in values.items() if k!="outputs"}
               for mode,values in result["train_only_cross_validation"].items()}
    text = "CPU PRIMARY v5; exact parent authorization verified; TRAIN only\n" + json.dumps(metrics,indent=2) + "\n"
    text += f"Fit {result['fit_rows']} rows/{result['fit_groups']} groups. Feature-masked {result['masked_by_feature_contract']}.\n"
    text += f"Runtime parity {parity}; model {model_bytes} bytes; runtime {runtime_bytes} bytes; elapsed {result['elapsed_seconds']:.3f}s.\n"
    text += "All outputs abstain/unqualified. New DEV unread; no GPU; DATE untrained.\n"
    text += "Model SHA256:"+model_sha+"\nMetrics SHA256:"+metrics_sha+"\n"
    with (ROOT / "analysis/night-learned-dialogue.v5.primary-cpu.txt").open("x",encoding="utf-8") as f:
        f.write(text)
    print(json.dumps({"metrics":metrics,"elapsed_seconds":result["elapsed_seconds"],"model_sha256":model_sha,
                     "metrics_sha256":metrics_sha,"model_bytes":model_bytes,"runtime_bytes":runtime_bytes,"parity":parity}))


if __name__ == "__main__":
    main()
