"""Build concrete executable pins and TRAIN cache; never fit classifier weights."""
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys
import time
import numpy as np
from safetensors.numpy import save_file
from threadpoolctl import threadpool_limits
from repayment_data import ROOT, HERE, PACKET, sha, encoded, write_new, verify, manifest, split_integrity, arrays, snapshot
from repayment_runtime import observed_text
from repayment_model import support
from repayment_test import run

PLAN = HERE / "repayment_plan.json"
ENCODER_RUNTIME = ROOT / "integrations/learned-dialogue/day2_pretrained_runtime.py"
ENCODER_HEAD = ROOT / "integrations/learned-dialogue/day2_pretrained_head.json"


def rel(path): return Path(path).relative_to(ROOT).as_posix()


def encoder_records():
    if sha(ENCODER_HEAD) != "fb3d2758994ea47c2d7e88bafc2deab552a506dd09a39780fda85f2c6036cd5e" or sha(ENCODER_RUNTIME) != "355e946677aa0a08b35d3714802b4ba645a0405f7d2f1910d6b5b6f26f37e2db":
        raise ValueError("Frozen encoder provenance source changed")
    record = json.loads(ENCODER_HEAD.read_text(encoding="utf-8"))["encoder"]
    directory = ROOT / record["local_directory"]
    pins = {rel(ENCODER_HEAD): sha(ENCODER_HEAD), rel(ENCODER_RUNTIME): sha(ENCODER_RUNTIME)}
    pins.update({rel(directory / name): value["sha256"] for name, value in record["files"].items()})
    verify(pins)
    return directory, pins, record


def get_encoder(directory):
    spec = importlib.util.spec_from_file_location("repayment_pinned_encoder", ENCODER_RUNTIME)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.FrozenEncoder(directory, threads=2)


def versions():
    return {n: importlib.metadata.version(n) for n in ("numpy", "torch", "transformers", "safetensors", "threadpoolctl")}


def historical():
    old = ROOT / "integrations/learned-dialogue/day2_distill_plan.json"
    frozen = ROOT / "integrations/learned-dialogue/day2_distill_freeze.json"
    if sha(frozen) != "092abc6a6c5e4328d8f99884dfe50f289741d675c0e631713864080c4103084e": raise ValueError("Previous student freeze changed")
    p = json.loads(old.read_text(encoding="utf-8")); f = json.loads(frozen.read_text(encoding="utf-8"))
    pins = dict(p["historical_sha256"]); pins.update(p["source_sha256"]); pins.update(p["input_sha256"])
    pins.update(f["models_sha256"]); pins[rel(frozen)] = sha(frozen); pins[rel(old)] = sha(old)
    pins["analysis/day2-distill-experiment.json"] = "9cb30809b42895dfe93f4d3b808d70efc842a07d28024ca0af589451abe1e0a3"
    verify(pins); return pins


def prepare():
    if PLAN.exists(): raise ValueError("Plan already frozen; no overwrite")
    start = time.monotonic()
    if not (ROOT / "analysis/repayment-semantic-design.json").exists(): raise FileNotFoundError("Astra actual final design/handoff not ready; no packet fit")
    designpath = ROOT / "analysis/repayment-semantic-design.json"
    if sha(designpath) != "918ce8c2a9d7777ee571f59e8b647b167cc16b99065f85e7a5bb117a65162027" or sha(PACKET / "manifest.json") != "a36f51005b81e8ec981ce9651baae76cfa775e07ec128ae22d2fbd75edb37ae3":
        raise ValueError("Parent-provided final author anchors changed")
    design = json.loads(designpath.read_text(encoding="utf-8")); verify(design["dataset_pins"])
    obj, labels, files = manifest(); train, splits = split_integrity(files, labels)
    x, y, masks, gw = arrays(train, labels); pos, neg, q, trained = support(y, masks, gw)
    directory, encoderpins, encoder_record = encoder_records(); old = historical()
    with threadpool_limits(limits=2): tests = run()
    encoder = get_encoder(directory); texts = [observed_text(snapshot(r)) for r in train]
    lengths = [len(encoder.tokenizer(t, truncation=False)["input_ids"]) for t in texts]
    if max(lengths) > encoder.max_length: raise ValueError("TRAIN source would be truncated by frozen encoder; explicit new mask/version needed")
    embeddings = encoder.encode(texts, deadline=time.monotonic() + 180, progress=True)
    cache = HERE / "repayment_cache.train.safetensors"
    if cache.exists(): raise ValueError("Immutable cache exists")
    ordered = sha(files["train"])
    save_file({"embeddings": embeddings}, str(cache), metadata={"split": "TRAIN", "input_sha256": ordered,
             "serialization": "repayment-observed-context-hash1024-v1", "encoder_revision": encoder_record["revision"]})
    code = {rel(HERE / ("repayment_" + name + ".py")): sha(HERE / ("repayment_" + name + ".py")) for name in ("runtime", "model", "data", "eval", "test", "preflight", "train", "bridge")}
    packet_pins = {rel(PACKET / "manifest.json"): sha(PACKET / "manifest.json"), rel(ROOT / "analysis/repayment-semantic-design.json"): sha(ROOT / "analysis/repayment-semantic-design.json")}
    for name, record in obj["outputs"].items():
        p = PACKET / name
        if sha(p) != record["sha256"]: raise ValueError("Actual author output pin mismatch")
        packet_pins[rel(p)] = record["sha256"]
    packet_pins[rel(PACKET / "build_packet.py")] = obj["authoring_source_sha256"]
    verify(packet_pins)
    source_sgd = ROOT / "analysis/day2-sgd-model-report.json"
    if sha(source_sgd) != "36fac151cbf2eeb04a1d77b0c65ba69946a00e577c0213b259965db8659a5f1a": raise ValueError("Frozen SGD reference changed")
    sgd_completion = ROOT / "analysis/day2-sgd-model-completion.json"
    sgd = json.loads(sgd_completion.read_text(encoding="utf-8"))
    packet_pins[rel(source_sgd)] = sha(source_sgd); packet_pins[rel(sgd_completion)] = sha(sgd_completion)
    plan = {"status": "READY_FOR_PARENT_EXACT_SOURCE_EXECUTION", "python_executable": sys.executable, "source_sha256": code,
      "input_sha256": {**packet_pins, **encoderpins, rel(cache): sha(cache)}, "historical_sha256": old, "versions": versions(),
      "labels": labels, "files": {s: rel(p) for s, p in files.items()}, "splits": splits,
      "TRAIN_support": {"group_weighted_positive": pos.tolist(), "group_weighted_negative": neg.tolist(), "class_weight_q": q.tolist(),
          "trained_head_mask": trained.tolist(), "known_elements": int(masks.sum()), "unknown_elements": int((1 - masks).sum()),
          "rule": "TRAIN q=min(5,max(1,sqrt(N/P))); no P or N -> untrained; unknown mask is never a negative"},
      "encoder": {"directory": rel(directory), "revision": encoder_record["revision"], "frozen": True, "threads": 2,
          "maximum_wordpieces": encoder.max_length, "TRAIN_max_wordpieces": max(lengths), "TRAIN_cache_shape": list(embeddings.shape),
          "old_B77_head_reused": False, "runtime_teacher_encoder_required": False},
      "fit": {"models": ["MiniLM_frozen_fresh_task_linear", "student_hard", "student_distill"], "teacher_epochs": 200,
          "student_epochs": 400, "batch": 32, "seed": 20261011, "teacher_Adam_lr": .01, "student_Adam_lr": .003, "clip_norm": 1, "mean_nonbias_L2": .01,
          "denominator": "per-head TRAIN sum(group_weight*(q*y+1-y)); divide over trained heads; minibatch N/B correction",
          "distill": ".5 masked balanced hardBCE + .5*T^2 BernoulliKL(raw TRAIN teacher/2 || student/2), T2, same L2/init/batches",
          "student_features": "only observed speaker/text, signed word/bigram/character hash1024 -> tanh32 -> labels",
          "SGD_financial_supervision": "none; no SGD rows admitted or generic AFFIRM mapped to finance"},
      "calibration": {"temperature_family_prefixes": ["C01", "C03", "C07"], "threshold_family_prefixes": ["C02", "C06", "C08"],
          "temperature": "CAL-fit only fixed T grid [.5,1,2,4] unweighted known BCE; no both directions -> T1 unsupported", "threshold": "CAL-select only [.5,.6,.7,.8,.9], maximize empirical precision>=.90 with >=3 accepted; no both directions -> unavailable/all abstain",
          "warning": "Disjoint CAL roles but tiny authored groups; no independent gold/risk qualification"},
      "evaluation": {"once": True, "weights_and_both_student_exports_frozen_before_CAL": True,
          "all_calibrators_frozen_before_HELDOUT": True, "selection_on_HELDOUT": False, "raw_threshold": .5,
          "metrics": ["per-class_known_precision_recall_F1", "micro_macroF1", "unknown_counts", "whole_context_vs_no_context", "negation_multiact_reported_scope_slices", "native_stdlib_full_parity", "retained_sanity_probes_descriptive_only"],
          "expected_scorer": rel(HERE / "repayment_eval.py"), "qualification": False},
      "budget": {"wall_seconds": 900, "threads": 2, "retries": 0, "GPU": False, "USD": 0},
      "SGD_source_only_reference": {"frozen_report_path": rel(source_sgd), "frozen_report_sha256": sha(source_sgd),
          "completion_path": rel(sgd_completion), "completion_sha256": sha(sgd_completion), "available_previously_fitted_TRAIN_USER_rows": sgd["actual_counts"]["TRAIN_USER"],
          "rows_used_for_this_repayment_fit": 0, "semantic_financial_labels_from_SGD": 0, "generic_act_auxiliary_new_rows_fitted": 0,
          "scope": "Reuse historical measured source-only SGD support by reference, not as financial target/gold or all-row MiniLM encoding. Optional <=1024 generic-act follow-up deferred to avoid delaying targeted fit."},
      "tests": tests, "prepare_seconds": time.monotonic() - start,
      "scope": "Single-author fictional engineering data, group-heldout authored families. No ASR/Freya/permission/identity/ledger qualification; bank authority always false.",
      "API": "repayment_runtime.decode(blob,expected_sha256); predict(packet_input,model,calibrator=None). Raw packet input is observed current_utterance plus previous_utterances; all outputs abstain on bank authority."}
    write_new(PLAN, plan)
    command = '"' + sys.executable + '" -B integrations/learned-dialogue/repayment_train.py --run --approved-plan-sha ' + sha(PLAN)
    report = {"status": plan["status"], "plan_path": rel(PLAN), "plan_sha256": sha(PLAN), "command": command,
              "source_sha256": code, "input_sha256": plan["input_sha256"], "historical_pins_verified": len(old),
              "splits": splits, "TRAIN_support": plan["TRAIN_support"], "tests": tests, "fits": 0, "bank_authority": False}
    write_new(ROOT / "analysis/repayment-model-plan.json", report)
    (ROOT / "analysis/repayment-model-plan.txt").write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True), flush=True)


if __name__ == "__main__": prepare()
