"""Pinned CPU experiment. Prepare performs backward smokes, ZERO optimizer steps.
Run requires the exact prepared plan hash and a truthful parent grant string.
No network, GPU, pickled checkpoints, external inference or bank operations.
"""
import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREFIX = ROOT / "analysis/day2-sgd-model"
PLAN = Path(str(PREFIX) + "-plan.json")


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


data = load("day2_sgd_data")
adapter = load("day2_sgd_adapter")


def offline(*args, **kwargs):
    raise RuntimeError("Network disabled by pinned CPU experiment")


socket.create_connection = offline
socket.socket.connect = offline


def write(path, value):
    assert not path.exists(), "No overwriting existing experiment output: " + str(path)
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    path.write_bytes(raw)
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def pin(path):
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": data.sha(path)}


def libraries():
    global np, torch, models, runtime, metrics
    import numpy as np
    import torch
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.manual_seed(data.SEED)
    models = load("day2_sgd_model")
    runtime = load("day2_sgd_runtime")
    metrics = load("day2_sgd_metrics")


def tensors(rows, schema):
    features, masks, roles, labels, known = [], [], [], [], []
    empty = {"input": {"speaker": "USER", "utterance": "", "earlier_context": []}}
    for row in rows:
        x, m, r = adapter.features(row or empty)
        y, k, _ = adapter.targets(row or empty, schema)
        features.append(x); masks.append(m if row else [0.] * 9); roles.append(r)
        labels.append(y); known.append(k)
    xt = torch.tensor(np.asarray(features), dtype=torch.float32)
    mt = torch.tensor(masks, dtype=torch.float32)
    rt = torch.tensor(roles, dtype=torch.int64)
    yt = {h: torch.tensor([y[h] for y in labels]) for h in labels[0]}
    kt = {h: torch.tensor([k[h] for k in known], dtype=torch.float32) for h in known[0]}
    assert not kt["updates"].any()
    return xt, mt, rt, yt, kt


def fresh(schema):
    q = [adapter.vector(text) for text in schema["query_texts"]]
    g = models.SharedQueryGNN(schema, q, True)
    z = copy.deepcopy(g); z.relations = False
    return {"G_relations": g, "Zero_edges": z}


def weights(model):
    return {"relations": model.relations, "weights": {name: {"shape": list(value.shape), "float32_le_base64": base64.b64encode(value.detach().numpy().astype("<f4").tobytes()).decode()} for name, value in model.named_parameters()}}


def state_sha(model):
    return hashlib.sha256(json.dumps(weights(model), sort_keys=True).encode()).hexdigest()


def reset(prior, old_keys, new_keys):
    for i, (old, new) in enumerate(zip(old_keys, new_keys)):
        if old != new:
            for value in prior.values():
                value[i].zero_()


def parity(arms, schema, rows):
    result = {}
    for name, model in arms.items():
        compiled = runtime.CompiledModel(schema, weights(model))
        prior = model.initial_memory(1)
        plain = runtime.initial_memory(schema)
        maximum, latencies = 0., []
        for row in rows:
            x, m, r, _, _ = tensors([row], schema)
            with torch.no_grad():
                reference = model(x, m, r, prior)
            started = time.perf_counter()
            actual = compiled.logits(row["input"], plain)
            latencies.append(time.perf_counter() - started)
            maximum = max(maximum, max(float(np.max(np.abs(reference[h][0].numpy() - actual[h]))) for h in adapter.HEADS))
            prior = model.memory(reference); plain = compiled.memory(actual)
        assert maximum < 1e-4, (name, maximum)
        result[name] = {"rows": len(rows), "all_four_head_coordinates": True, "max_abs_logit_difference": maximum, "stdlib_latency_seconds_median": float(np.median(latencies)), "stdlib_latency_seconds_p95": float(np.percentile(latencies, 95)), "prior": "Own predicted intent/presence, synthetic sequential TRAIN witness chain, not an evaluation metric"}
    return result


def prepare():
    libraries()
    assert not PLAN.exists()
    source_paths = [ROOT / "analysis/day2-learned-next-design.json", ROOT / "analysis/day2-learned-next-design.txt", ROOT / "analysis/day2-sgd-independent-review.json"]
    source_paths += [data.PACKET / s for s in ("service-schema.json", "process.py", "batches.py", "NOTICE.txt", "LICENSE.txt", "README.txt", "full-v1/manifest.json", "full-v1/split-plan.json", "full-v1/ready-handoff.json", "full-v1/validation.json")]
    source_pins = [pin(p) for p in source_paths]
    manifest = json.loads(data.MANIFEST.read_text())
    data.verify_shards()
    schema = json.loads((data.PACKET / "service-schema.json").read_text())
    inventory = data.make_index("TRAIN", schema)
    witnesses = inventory.pop("smoke_rows")
    spec = adapter.schema_spec(schema, inventory["acts"])
    assert len(spec["services"]) == 26 and spec["intent_count"] == 79 and spec["slot_count"] == 215
    arms = fresh(spec)
    original = {n: state_sha(m) for n, m in arms.items()}
    smoke = {"optimizer_steps": 0, "witness_rows": len(witnesses), "all_value_KEEP_SET_DELETE_heads": "DISABLED_UNKNOWN_due_independent_partial_word_recovery_proof", "shards_verified": len(manifest["outputs"])}
    changed = copy.deepcopy(witnesses[0]); changed["targets"] = {"frames": []}; changed["ancestry"] = {"future": "arbitrary"}; changed["record_id"] = "changed"; changed["service_supervision_masks"] = {}
    assert adapter.features(changed) == adapter.features(witnesses[0])
    smoke["annotation_ancestry_mutation_features_identical"] = True
    rows = (witnesses + [None] * 32)[:32]
    x, mask, roles, y, k = tensors(rows, spec)
    for name, model in arms.items():
        prior = model.initial_memory(32)
        logits = model(x, mask, roles, prior)
        loss, _ = model.masked_loss(logits, y, k, torch.ones(32))
        loss.backward()
        norms = {h: float(model.Whead.grad[i].norm()) for i, h in enumerate(adapter.HEADS)}
        assert all(v > 0 and math.isfinite(v) for v in norms.values()) and float(model.E.grad.norm()) > 0
        memory = model.memory(logits)
        assert not memory["requested"].any() and not memory["acts"].any()
        reset(memory, ["old"] * 32, ["new"] * 32)
        assert all(not v.any() for v in memory.values())
        model.zero_grad(set_to_none=True)
        z = {h: torch.zeros_like(v) for h, v in k.items()}
        empty_loss, _ = model.masked_loss(model(x, mask, roles, prior), y, z, torch.ones(32))
        empty_loss.backward()
        assert all(p.grad is None or not p.grad.any() for p in model.parameters())
        model.zero_grad(set_to_none=True)
        assert state_sha(model) == original[name]
        smoke[name] = {"head_gradient_norms": norms, "zero_masks_zero_gradient": True, "memory_reset_all_coordinates": True, "parameter_bytes_unchanged": True}
    # Same information and initial weights: disabling only edge path gives identical outputs.
    arms["G_relations"].relations = False
    with torch.no_grad():
        a = arms["G_relations"](x, mask, roles, arms["G_relations"].initial_memory(32))
        b = arms["Zero_edges"](x, mask, roles, arms["Zero_edges"].initial_memory(32))
    assert all(torch.equal(a[h], b[h]) for h in adapter.HEADS)
    arms["G_relations"].relations = True
    smoke["matched_same_information_edge_toggle_exact"] = True
    stream = data.DialogStream("TRAIN")
    for bad in (32.0, -1, True):
        try:
            next(stream.batches(bad))
            raise AssertionError("invalid batch accepted")
        except ValueError:
            pass
    stream.close()
    smoke["fractional_negative_boolean_batch_rejected"] = True
    smoke["parity"] = parity(arms, spec, witnesses[:3])
    dummy = {h: {"temperature": 1., "threshold": 1., "available": False} for h in adapter.HEADS}
    prototype = {"schema": spec, "arms": {n: weights(m) for n, m in arms.items()}, "calibration": {n: dummy for n in arms}, "attribution": "Google Research Schema-Guided Dialogue, Rastogi et al., CC BY-SA 4.0; preserve publisher NOTICE/LICENSE"}
    size = len(json.dumps(prototype, ensure_ascii=False, separators=(",", ":")).encode()) + (HERE / "day2_sgd_adapter.py").stat().st_size + (HERE / "day2_sgd_runtime.py").stat().st_size
    assert size <= 500000, size
    smoke["compiled_JSON_plus_schema_plus_stdlib_code_bytes"] = size
    smoke_pin = write(Path(str(PREFIX) + "-smoke.json"), smoke)
    witness_pin = write(Path(str(PREFIX) + "-witnesses.json"), witnesses)
    code_pins = [pin(p) for p in sorted(HERE.glob("day2_sgd_*.py"))]
    plan = {"status": "READY_ZERO_OPTIMIZER_STEPS_REQUIRES_FRESH_PARENT_HASH_GRANT", "source_pins": source_pins, "code_pins": code_pins, "input_shards": manifest["outputs"], "TRAIN_index": inventory, "smoke": smoke_pin, "witnesses": witness_pin, "schema": spec, "seed": data.SEED, "arms": ["G_relations", "Zero_edges"], "heads": list(adapter.HEADS), "disabled_heads": {"value": "UNKNOWN", "KEEP_SET": "UNKNOWN", "DELETE": "UNKNOWN", "reason": "Independent source audit found 15 partial-word recovery masks including one update; frozen V1 preserved"}, "memory": "Own detached raw-temperature predicted intent/presence only; requested/actions zero; reset every dialog/split", "training": {"threads": 2, "device": "CPU", "batch_dialogues": 32, "USER_unroll": 4, "epochs": 1, "optimizer": "Adam", "lr": .003, "clip_norm": 1., "l2_once_per_chunk": .0005, "head_weights": {"intent": 1, "requested": 1, "presence": 1, "acts": .5}, "event_weighting": "Equal closure-group mass, equal dialogues within group, equal events within dialogue, denominator fixed128", "ordering": "TRAIN closure groups and dialogs hash-order seed20261011, USER events chronological; first5 batches consume fit and profile; no retries or partial-fit evaluation", "fit_seconds_cap": 600, "external_wall_seconds_cap": 900}, "calibration": "Whole closure groups hash parity partition CAL-fit vs CAL-select, temperatures[.25,.5,1,2,4] then threshold grid.01 max accepted at empiricalprecision>=.95; no arbitrarysupportfloor; never EVAL selection", "evaluation": "After weight freeze then CAL/bundle freeze, one internalEVAL causal pass; main own memory per arm; controlled G given Zero's causal prior diagnostic; no gold routing or values", "limits": ["Conditional published-frame semantics, absent frames UNKNOWN", "No service-routing/DST correctness claim", "No bank authority, permissions, ledger or OOD bank safety claim", "CC BY-SA4 publisher attribution retained", "One publisher officialTRAIN split closure partition, not external IID gold", "Latest-only/oracle-gold-state diagnostics deferred; no gold prior in pilot"], "compiled_total_size_cap": 500000, "initial_export_bytes": size}
    info = write(PLAN, plan)
    text_path = Path(str(PREFIX) + "-plan.txt")
    assert not text_path.exists()
    text_path.write_text("READY; zero optimizer steps. Plan SHA256 " + info["sha256"] + "\nFour publisher heads; value/KEEP_SET/DELETE explicitly UNKNOWN.\nFresh parent grant required before --run.\n" + json.dumps(smoke, indent=2), encoding="utf-8")
    print(json.dumps(info), flush=True)


def verify_plan(expected):
    assert data.sha(PLAN) == expected
    p = json.loads(PLAN.read_text())
    for entry in p["source_pins"] + p["code_pins"] + [p["smoke"], p["witnesses"], p["TRAIN_index"]]:
        path = ROOT / entry["path"]
        assert data.sha(path) == entry["sha256"]
        if "bytes" in entry:
            assert path.stat().st_size == entry["bytes"]
    data.verify_shards()
    return p


def evaluate_stream(stream, arms, spec, controlled=False):
    records = {n: metrics.Records(spec) for n in arms}
    if controlled:
        records["G_common_Zero_prior"] = metrics.Records(spec)
    memories = {n: m.initial_memory(32) for n, m in arms.items()}
    old = [None] * 32
    events = 0
    with torch.no_grad():
        for keys, steps in stream.batches():
            for prior in memories.values():
                reset(prior, old, keys)
            old = keys
            for rows, _ in steps:
                x, mask, roles, y, known = tensors(rows, spec)
                before_zero = memories["Zero_edges"]
                outputs = {n: m(x, mask, roles, memories[n]) for n, m in arms.items()}
                if controlled:
                    outputs["G_common_Zero_prior"] = arms["G_relations"](x, mask, roles, before_zero)
                yy = {h: v.numpy() for h, v in y.items()}; kk = {h: v.numpy() for h, v in known.items()}
                for n, logits in outputs.items():
                    records[n].add({h: v.numpy() for h, v in logits.items()}, yy, kk)
                for n, m in arms.items():
                    memories[n] = m.memory(outputs[n])
                events += sum(r is not None for r in rows)
    stream.close()
    return records, events


def execute(args):
    begun = time.perf_counter()
    p = verify_plan(args.plan_sha)
    assert args.grant and "parent" in args.grant.casefold(), "Truthful parent execution grant required"
    assert not list((ROOT / "analysis").glob("day2-sgd-model-fit-*")), "Fit outputs exist: no rerun"
    write(Path(str(PREFIX) + "-fit-start.json"), {"plan_sha256": args.plan_sha, "grant": args.grant, "optimizer_steps": 0})
    libraries()
    spec = p["schema"]; arms = fresh(spec)
    optimizers = {n: torch.optim.Adam(m.parameters(), lr=.003) for n, m in arms.items()}
    stream = data.DialogStream("TRAIN")
    memories = {n: m.initial_memory(32) for n, m in arms.items()}; old = [None] * 32
    events, chunks, steps_count, profiles = 0, 0, 0, []
    fit_start = time.perf_counter()
    for keys, steps in stream.batches():
        if time.perf_counter() - fit_start > 600:
            write(Path(str(PREFIX) + "-fit-incomplete.json"), {"reason": "600s fit cap", "events": events, "optimizer_steps": steps_count, "no_CAL_or_EVAL": True})
            raise RuntimeError("Fit cap; partial model not evaluated; no retries")
        chunk_start = time.perf_counter()
        for prior in memories.values():
            reset(prior, old, keys)
        old = keys
        prepared = [(tensors(rows, spec), torch.tensor(ww, dtype=torch.float32)) for rows, ww in steps]
        for n, m in arms.items():
            optimizers[n].zero_grad(set_to_none=True)
            loss = 0
            for (x, mask, roles, y, known), ww in prepared:
                logits = m(x, mask, roles, memories[n])
                term, _ = m.masked_loss(logits, y, known, ww)
                loss = loss + term
                memories[n] = m.memory(logits)
            loss = loss + .0005 * sum(v.square().sum() for v in m.parameters())
            assert torch.isfinite(loss)
            loss.backward(); torch.nn.utils.clip_grad_norm_(m.parameters(), 1.)
            optimizers[n].step(); steps_count += 1
        events += sum(r is not None for rows, _ in steps for r in rows)
        chunks += 1
        if chunks <= 5:
            profiles.append({"chunk": chunks, "events_cumulative": events, "seconds": time.perf_counter() - chunk_start, "consumed_fit": True})
        if chunks % 100 == 0:
            print(json.dumps({"TRAIN_events": events, "chunks": chunks, "fit_seconds": time.perf_counter() - fit_start}), flush=True)
    stream.close()
    fit_seconds = time.perf_counter() - fit_start
    assert events == 132615 and fit_seconds <= 600
    for m in arms.values():
        m.eval()
        for v in m.parameters():
            v.requires_grad_(False)
    frozen = write(Path(str(PREFIX) + "-fit-frozen.json"), {"plan_sha256": args.plan_sha, "arms": {n: weights(m) for n, m in arms.items()}, "events": events, "optimizer_steps": steps_count, "fit_seconds": fit_seconds})
    data.make_index("CAL", spec["source_schema"])
    fit_selection = lambda group: int(data.order_key("cal-role", group)[0], 16) % 2 == 0
    cf, nfit = evaluate_stream(data.DialogStream("CAL", fit_selection), arms, spec)
    cs, nselect = evaluate_stream(data.DialogStream("CAL", lambda g: not fit_selection(g)), arms, spec)
    assert nfit + nselect == 16072
    cal = {n: cf[n].calibration(cs[n]) for n in arms}
    bundle = {"schema": spec, "arms": {n: weights(m) for n, m in arms.items()}, "calibration": cal, "frozen_weights": frozen, "plan_sha256": args.plan_sha, "attribution": "Google Research Schema-Guided Dialogue, Rastogi et al., CC BY-SA4.0. Original NOTICE/LICENSE preserved in source pins. Semantic-only; bank authority NONE; values/update/delete UNKNOWN."}
    artifact = write(Path(str(PREFIX) + "-compiled.json"), bundle)
    artifact_total = artifact["bytes"] + (HERE / "day2_sgd_adapter.py").stat().st_size + (HERE / "day2_sgd_runtime.py").stat().st_size
    assert artifact_total <= 500000
    assert data.sha(ROOT / frozen["path"]) == frozen["sha256"]
    data.make_index("EVAL", spec["source_schema"])
    records, evaluated = evaluate_stream(data.DialogStream("EVAL"), arms, spec, controlled=True)
    assert evaluated == 16295
    report = {"status": "COMPLETE", "plan_sha256": args.plan_sha, "grant": args.grant, "frozen_weights": frozen, "compiled": artifact, "compiled_schema_runtime_adapter_total_bytes": artifact_total, "TRAIN_events": events, "CAL_fit_events": nfit, "CAL_select_events": nselect, "EVAL_events": evaluated, "fit_seconds": fit_seconds, "wall_seconds": time.perf_counter() - begun, "optimizer_steps": steps_count, "first5_consumed_fit_profiles": profiles, "calibration": cal, "metrics": {n: r.report(cal[n] if n in cal else cal["G_relations"]) for n, r in records.items()}, "trained_export_parity": parity(arms, spec, json.loads((ROOT / p["witnesses"]["path"]).read_text())[:3]), "disabled_value_update_DELETE": "UNKNOWN_due_independent_audit", "OOD": "Unsupported: no heldout OOD labels or bank authority calibration; conditional source abstention only", "limitations": p["limits"], "ablation": "Matched direct/context/schema information in both arms; own predicted histories differ naturally; controlled G uses Zero causal prior. No graph-superiority claim from single seed."}
    write(Path(str(PREFIX) + "-report.json"), report)
    print(json.dumps({"status": "COMPLETE", "report": "analysis/day2-sgd-model-report.json", "fit_seconds": fit_seconds, "wall_seconds": report["wall_seconds"]}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--execute", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--plan-sha", default="")
    parser.add_argument("--grant", default="")
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.run:
        verify_plan(args.plan_sha)
        assert args.grant and "parent" in args.grant.casefold()
        assert not list((ROOT / "analysis").glob("day2-sgd-model-fit-*"))
        command = [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--execute", "--plan-sha", args.plan_sha, "--grant", args.grant]
        started = time.perf_counter()
        try:
            child = subprocess.run(command, timeout=900, check=False)
            outcome = {"exit_code": child.returncode, "elapsed_seconds": time.perf_counter() - started, "external_wall_cap_seconds": 900}
        except subprocess.TimeoutExpired:
            outcome = {"exit_code": "TIMEOUT", "elapsed_seconds": time.perf_counter() - started, "external_wall_cap_seconds": 900, "no_rerun": True}
        write(Path(str(PREFIX) + "-watchdog.json"), outcome)
        if outcome["exit_code"] != 0:
            raise SystemExit(1)
    elif args.execute:
        execute(args)
    else:
        parser.error("choose --prepare or granted --run")


if __name__ == "__main__":
    main()
