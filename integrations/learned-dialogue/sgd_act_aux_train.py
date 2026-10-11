"""Pinned, CPU-only, three-epoch source-act experiment; never uses cached indexes.

Run once in a fresh owned output namespace. TRAIN is streamed and verified before
fitting. CAL is streamed only after weight freeze, EVAL only after CAL freeze.
The baseline and observed-only controls are predeclared internal diagnostics.
"""
import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
import sys
sys.dont_write_bytecode = True
from collections import Counter, defaultdict
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import numpy as np
import scipy
from scipy import sparse
import sklearn
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.linear_model import SGDClassifier

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "analysis"
CACHE = ROOT / "local-runs/customer-benchmark-sgd-act-aux"
MANIFEST = ROOT / "research/customer-benchmark/day2-training-data/sgd/full-v1/manifest.json"
MANIFEST_SHA = "7176ce8bf20c7e6adce899a276f7de0c042e0e33eb63999462264ca6c1843513"
SEED, EPOCHS, LIMIT = 20261011, 3, 900
JOB_START = time.perf_counter()
ACTS = ("AFFIRM", "NEGATE", "INFORM", "REQUEST")
PUBLIC_ACTS = {"INFORM_INTENT", "NEGATE_INTENT", "AFFIRM_INTENT", "INFORM", "REQUEST", "AFFIRM", "NEGATE", "SELECT", "REQUEST_ALTS", "THANK_YOU", "GOODBYE"}


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load_module("sgd_act_aux_runtime")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def pin(path):
    path = Path(path)
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)}


def write(path, obj, pretty=False):
    # Exclusive writes prevent accidental reuse/refit under an existing run.
    raw = (json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"), allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as f:
        f.write(raw)
    return pin(path)


def event(stage, **fields):
    print(json.dumps({"stage": stage, "elapsed_seconds": round(time.perf_counter() - JOB_START, 3), **fields}), flush=True)


def labels(row, services):
    """Existential four-act aggregation of the reviewed service-local masks.

    Positive when any supervised known frame contains the exact act. Negative
    only if every publisher frame has known service/action supervision. Missing
    frames or partially unknown frames cannot invent negative row-level labels.
    AFFIRM_INTENT/NEGATE_INTENT/INFORM_INTENT/REQUEST_ALTS stay distinct.
    """
    frames = row.get("targets", {}).get("frames")
    y = np.zeros(4, dtype=np.int8)
    known = np.zeros(4, dtype=bool)
    reasons = Counter()
    if not isinstance(frames, list) or not frames:
        reasons["missing_or_empty_frames"] += 1
        return y, known, reasons
    complete = True
    for frame in frames:
        service = frame.get("service")
        valid = (service in services and row.get("service_supervision_masks", {}).get(service) is True
                 and frame.get("head_masks", {}).get("publisher_actions") is True
                 and isinstance(frame.get("actions"), list))
        if valid:
            actions = frame["actions"]
            valid = all(isinstance(a, dict) and a.get("act") in PUBLIC_ACTS for a in actions)
        if not valid:
            complete = False
            reasons["frame_service_or_actions_unknown"] += 1
            continue
        for j, act in enumerate(ACTS):
            if any(a["act"] == act for a in actions):
                y[j], known[j] = 1, True
    if complete:
        known[:] = True
    return y, known, reasons


def stream(split, manifest, plan, services):
    current, previous, yy, kk, groups, dialogues = [], [], [], [], [], []
    reasons, dialogue_counts = Counter(), Counter()
    records, verified, witnesses = set(), [], []
    shards = [s for s in manifest["outputs"] if s["split"] == split]
    for item in shards:
        path = ROOT / item["path"]
        digest, size, count = hashlib.sha256(), 0, 0
        with path.open("rb") as f:
            for raw in f:
                digest.update(raw); size += len(raw); count += 1
                row = json.loads(raw)
                a = row["ancestry"]
                meta = plan[a["dialogue_id"]]
                assert a["split"] == split == meta["split"]
                assert a["group_id"] == meta["group_id"]
                assert a["source_revision"] == manifest["source"]["revision"]
                assert a["source_file"] == meta["source_file"] and a["source_file"].startswith("train/")
                assert row["bank_policy_target_mask"] is False and row["ledger_target_mask"] is False
                assert row["record_id"] not in records
                records.add(row["record_id"])
                assert len(row["input"]["earlier_context"]) <= 8
                cu, pr = runtime.observed_text(row["input"])
                y, k, r = labels(row, services)
                reasons.update(r)
                current.append(cu); previous.append(pr); yy.append(y); kk.append(k)
                groups.append(a["group_id"]); dialogues.append(a["dialogue_id"])
                dialogue_counts[a["dialogue_id"]] += 1
                if split == "TRAIN" and len(witnesses) < 256:
                    witnesses.append(row)
        assert count == item["rows"] and size == item["bytes"] and digest.hexdigest() == item["sha256"], item["path"]
        verified.append({**item, "actual_rows": count, "actual_bytes": size, "actual_sha256": digest.hexdigest()})
        event("verified_shard", split=split, shard=path.name, rows=count)
    assert len(current) == manifest["counts"]["split_USER_examples"][split]
    assert len(dialogue_counts) == manifest["counts"]["split_dialogues"][split]
    assert all(n == plan[d]["user_turns"] for d, n in dialogue_counts.items())
    y, k = np.asarray(yy), np.asarray(kk)
    stats = {act: {"positive": int((y[:, j] & k[:, j]).sum()),
                   "negative": int(((y[:, j] == 0) & k[:, j]).sum()),
                   "unknown": int((~k[:, j]).sum())} for j, act in enumerate(ACTS)}
    semantic = json.dumps({"current": current, "previous": previous, "labels": y.tolist(),
                           "known": k.tolist(), "groups": groups, "dialogues": dialogues},
                          ensure_ascii=False, separators=(",", ":")).encode()
    data = {"current": current, "previous": previous, "y": y, "k": k,
            "groups": groups, "dialogues": dialogues, "witnesses": witnesses}
    evidence = {"rows": len(current), "dialogues": len(dialogue_counts), "groups": len(set(groups)),
                "per_class": stats, "unknown_reasons": dict(reasons), "shards": verified,
                "derived_features_labels_masks_ancestry_sha256": hashlib.sha256(semantic).hexdigest()}
    np.savez_compressed(CACHE / (split.lower() + "-targets-masks.npz"), y=y, known=k)
    return data, evidence


def vectorizer():
    return HashingVectorizer(n_features=4096, analyzer="word", ngram_range=(1, 2),
                            alternate_sign=True, norm="l2", lowercase=True, dtype=np.float64)


def matrix(data, arm="context", current=None, previous=None):
    cu = data["current"] if current is None else current
    pr = data["previous"] if previous is None else previous
    return vectorizer().transform(runtime.feature_text(a, b, arm == "context") for a, b in zip(cu, pr))


def quantize(value):
    return float(format(float(value), ".7g"))


def scores(bundle, arm, x):
    result = []
    for act in ACTS:
        h = bundle["arms"][arm][act]
        z = np.asarray(x @ np.asarray(h["coef"])) + h["intercept"]
        result.append(1 / (1 + np.exp(-np.clip(z, -700, 700))))
    return np.asarray(result).T


def metrics(y, k, p, thresholds):
    result = {}
    for j, act in enumerate(ACTS):
        known, truth = k[:, j], y[:, j].astype(bool)
        def one(threshold):
            pred = np.zeros(len(y), dtype=bool) if threshold is None else p[:, j] >= threshold
            tp = int((pred & truth & known).sum()); fp = int((pred & ~truth & known).sum())
            fn = int((~pred & truth & known).sum()); tn = int((~pred & ~truth & known).sum())
            selected = tp + fp
            return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                    "precision": tp / selected if selected else None,
                    "recall": tp / (tp + fn) if tp + fn else None,
                    "coverage_known": selected / int(known.sum()) if known.any() else None,
                    "coverage_all_rows": int(pred.sum()) / len(y) if len(y) else None,
                    "proposals_on_unknown_labels": int((pred & ~known).sum())}
        result[act] = {"known": int(known.sum()), "unknown": int((~known).sum()),
                       "raw": one(.5), "accepted": one(thresholds[act]["threshold"])}
    return result


def calibrate(y, k, p):
    result = {}
    for j, act in enumerate(ACTS):
        probability, truth = p[k[:, j], j], y[k[:, j], j]
        order = np.argsort(-probability, kind="stable")
        ps, ts = probability[order], truth[order]
        tp = np.cumsum(ts)
        candidates = np.flatnonzero(np.r_[ps[:-1] != ps[1:], True]) if len(ps) else np.asarray([], dtype=int)
        valid = [int(i) for i in candidates if tp[i] > 0 and tp[i] / (i + 1) >= .95]
        # Maximum empirical CAL positive coverage at >=95% precision; no support floor.
        chosen = valid[-1] if valid else None
        result[act] = {"threshold": float(ps[chosen]) if chosen is not None else None,
                       "cal_accepted": chosen + 1 if chosen is not None else 0,
                       "cal_precision": float(tp[chosen] / (chosen + 1)) if chosen is not None else None,
                       "known_cal": int(k[:, j].sum()), "minimum_support_floor": None,
                       "criterion": "max empirical CAL accepted positives at precision >=0.95; ties kept together; no confidence guarantee"}
    return result


def checks_before_fit(train, services, x):
    reviewed = load_module("day2_sgd_adapter")
    schema = json.loads((ROOT / "research/customer-benchmark/day2-training-data/sgd/service-schema.json").read_bytes())
    spec = reviewed.schema_spec(schema, sorted(PUBLIC_ACTS))
    for row in train["witnesses"]:
        derived, known, _ = labels(row, services)
        y, k, _ = reviewed.targets(row, spec)
        for j, act in enumerate(ACTS):
            indices = [s["act_offset"] + spec["acts"].index(act) for s in spec["services"]]
            assert bool(derived[j]) == any(y["acts"][i] and k["acts"][i] for i in indices)
        changed = copy.deepcopy(row)
        changed["targets"] = {"frames": []}; changed["ancestry"] = {"poison": "AFFIRM"}
        changed["service_supervision_masks"] = {"poison": True}
        assert runtime.observed_text(changed["input"]) == runtime.observed_text(row["input"])
        assert not labels(changed, services)[1].any()
    # Unknown frames must not become negatives, while a known positive remains known.
    row = copy.deepcopy(train["witnesses"][0])
    frame = row["targets"]["frames"][0]
    frame["actions"] = [{"act": "AFFIRM"}]
    row["targets"]["frames"].append({"service": "unknown", "actions": []})
    y, k, _ = labels(row, services)
    assert y.tolist() == [1, 0, 0, 0] and k.tolist() == [True, False, False, False]
    frame["actions"] = [{"act": "AFFIRM_INTENT"}]
    assert not labels(row, services)[0].any()
    maximum = 0.
    for i in range(min(256, len(train["current"]))):
        plain = runtime.vector(train["current"][i], train["previous"][i])
        reference = dict(zip(x[i].indices.tolist(), x[i].data.tolist()))
        maximum = max(maximum, max((abs(plain.get(j, 0.) - reference.get(j, 0.)) for j in set(plain) | set(reference)), default=0.))
    for cu, pr in [("", ""), ("İstanbul café Straße 東京", "Already confirmed?"), ("yes yes", "yes")]:
        reference = vectorizer().transform([runtime.feature_text(cu, pr)])
        dense = np.zeros(4096)
        for i, v in runtime.vector(cu, pr).items():
            dense[i] = v
        maximum = max(maximum, float(np.abs(dense - reference.toarray()[0]).max()))
    assert maximum < 1e-12
    return {"reviewed_adapter_positive_aggregation_rows": len(train["witnesses"]),
            "annotation_ancestry_mutation_features_identical": True,
            "unknown_masks_and_intent_act_distinction": "passed",
            "stdlib_hashing_parity_max_abs_error": maximum}


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    assert sha(MANIFEST) == MANIFEST_SHA
    manifest = json.loads(MANIFEST.read_bytes())
    assert manifest["source"]["official_split"] == "train"
    source_pins = [pin(MANIFEST)]
    for name in ("split_plan", "service_schema", "processor"):
        item = manifest[name]
        assert sha(ROOT / item["path"]) == item["sha256"]
        source_pins.append(pin(ROOT / item["path"]))
    source_pins += [pin(HERE / "day2_sgd_data.py"), pin(HERE / "day2_sgd_adapter.py")]
    plan = json.loads((ROOT / manifest["split_plan"]["path"]).read_bytes())["dialogues"]
    services = {s["service_name"] for s in json.loads((ROOT / manifest["service_schema"]["path"]).read_bytes())}
    group_sets = {s: {m["group_id"] for m in plan.values() if m["split"] == s} for s in ("TRAIN", "CAL", "EVAL")}
    assert not any(group_sets[a] & group_sets[b] for a, b in (("TRAIN", "CAL"), ("TRAIN", "EVAL"), ("CAL", "EVAL")))
    run_plan = {"authorization": "User explicitly authorized existing 135k source-aux CPU fit and parallel processing/training",
                "created_utc": datetime.now(timezone.utc).isoformat(), "seed": SEED, "epochs": EPOCHS,
                "fit_wall_limit_seconds": LIMIT, "job_wall_target_seconds": 1080,
                "source_pins": source_pins, "counts_pinned": manifest["counts"]["split_USER_examples"],
                "act_labels": list(ACTS), "labels": "exact publisher USER actions, reviewed service/action masks; existential positive; negative requires all frames known; missing unknown",
                "features": "current input.utterance plus only earlier_context[-1] when SYSTEM; role-prefixed lowercase word1-2 HashingVectorizer4096 signed L2; no frame/label/service/schema/action/bank features",
                "arms": ["context", "no_context"], "optimizer": {"loss": "log_loss", "alpha": .0001, "learning_rate": "optimal", "average": True, "batch_rows": 4096, "shuffle": False},
                "weights": "TRAIN-only group-balanced rows N/(groups*dialogues_in_group*rows_in_dialogue), renormalized per known head; positive multiplier max(1, weighted negatives/weighted positives)",
                "selection": "fixed three epochs, no CAL/EVAL model selection or refit",
                "calibration": "after quantized JSON weight freeze; independent thresholds per arm/act; max empirical CAL positive coverage with >=95% precision, no invented minimum support; unavailable if none",
                "eval": "one sealed EVAL pass after calibration freeze; all predeclared arms/controls scored together; previous EVAL exposure exists, INTERNAL DIAGNOSTIC ONLY",
                "controls": ["drop previous context on context-trained head", "shuffle previous SYSTEM text fixed seed", "empty current with observed context", "empty all observed text", "mutate all target/ancestry fields"],
                "scope": "MiniLM historical 90/95 describes B77 topics; this is source act supervision, not bank permission, repayment, Freya or fresh independent EVAL",
                "code_pins": [pin(Path(__file__)), pin(HERE / "sgd_act_aux_runtime.py")],
                "libraries": {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__}}
    plan_pin = write(OUT / "sgd-act-aux-run-plan.json", run_plan, True)
    event("plan_frozen", **plan_pin)
    train, train_evidence = stream("TRAIN", manifest, plan, services)
    xx = {arm: matrix(train, arm) for arm in ("context", "no_context")}
    checks = checks_before_fit(train, services, xx["context"])
    for arm, x in xx.items():
        sparse.save_npz(CACHE / ("train-" + arm + ".npz"), x)
    group_dialogues = defaultdict(set)
    dialogue_rows = Counter(train["dialogues"])
    for group, dialogue in zip(train["groups"], train["dialogues"]):
        group_dialogues[group].add(dialogue)
    n = len(train["current"])
    base_weight = np.asarray([n / (len(group_dialogues) * len(group_dialogues[g]) * dialogue_rows[d])
                              for g, d in zip(train["groups"], train["dialogues"])])
    positive_weights, fit_weights = {}, {}
    for j, act in enumerate(ACTS):
        known = train["k"][:, j]
        pos = float(base_weight[known & (train["y"][:, j] == 1)].sum())
        neg = float(base_weight[known & (train["y"][:, j] == 0)].sum())
        assert pos > 0 and neg > 0
        positive_weights[act] = max(1., neg / pos)
        weight = base_weight.copy() * known
        weight[train["y"][:, j] == 1] *= positive_weights[act]
        weight *= int(known.sum()) / weight.sum()
        fit_weights[act] = weight
    fit_start = time.perf_counter()
    fit_cpu_start = time.process_time()
    heads = {arm: {act: SGDClassifier(loss="log_loss", alpha=.0001,
                    random_state=SEED, shuffle=False, average=True, learning_rate="optimal")
                   for act in ACTS} for arm in xx}
    rng = np.random.default_rng(SEED)
    fit_rows = {arm: Counter() for arm in xx}
    for epoch in range(EPOCHS):
        order = rng.permutation(n)
        for start in range(0, n, 4096):
            batch = order[start:start + 4096]
            for arm in xx:
                xb = xx[arm][batch]
                for j, act in enumerate(ACTS):
                    known = train["k"][batch, j]
                    if known.any():
                        heads[arm][act].partial_fit(xb[known], train["y"][batch, j][known],
                            classes=np.asarray([0, 1]), sample_weight=fit_weights[act][batch][known])
                        fit_rows[arm][act] += int(known.sum())
            assert time.perf_counter() - fit_start < LIMIT, "CPU fit wall budget exceeded"
        event("epoch_complete", epoch=epoch + 1, rows_per_arm=n, fit_wall_seconds=round(time.perf_counter() - fit_start, 3))
    fit_wall, fit_cpu = time.perf_counter() - fit_start, time.process_time() - fit_cpu_start
    bundle = {"format": "sgd-source-act-aux.v1", "acts": list(ACTS),
              "manifest_sha256": MANIFEST_SHA, "plan_sha256": plan_pin["sha256"],
              "features": {"n_features": 4096, "ngram_range": [1, 2], "alternate_sign": True, "norm": "l2", "hash": "MurmurHash3_x86_32 seed0", "text": "role-prefixed current plus immediately previous SYSTEM only"},
              "seed": SEED, "epochs": EPOCHS, "positive_weights_TRAIN_only": positive_weights,
              "arms": {arm: {act: {"coef": [quantize(v) for v in head.coef_[0]], "intercept": quantize(head.intercept_[0])} for act, head in hh.items()} for arm, hh in heads.items()},
              "authority": "source-act proposals only; AFFIRM is never financial authorization",
              "license": "CC-BY-SA-4.0; SGD google-research-datasets/dstc8-schema-guided-dialogue " + manifest["source"]["revision"]}
    weights_pin = write(HERE / "sgd_act_aux_weights.json", bundle)
    assert weights_pin["bytes"] <= 500000, "Compact reviewable JSON budget exceeded"
    freeze_pin = write(OUT / "sgd-act-aux-weights-frozen.json", {
        "utc": datetime.now(timezone.utc).isoformat(), "weights": weights_pin,
        "fit_wall_seconds": fit_wall, "fit_cpu_seconds": fit_cpu,
        "train": train_evidence, "fit_presentations": {a: dict(c) for a, c in fit_rows.items()},
        "checks": checks, "positive_weights": positive_weights}, True)
    event("weights_frozen", weights=weights_pin, fit_wall_seconds=fit_wall, fit_cpu_seconds=fit_cpu)
    # No optimizer calls exist below this boundary.
    del heads, xx
    cal, cal_evidence = stream("CAL", manifest, plan, services)
    cal_scores = {arm: scores(bundle, arm, matrix(cal, arm)) for arm in ("context", "no_context")}
    calibration = {"weights_sha256": weights_pin["sha256"], "split": "CAL", "internal_diagnostic": True,
                   "arms": {arm: calibrate(cal["y"], cal["k"], pp) for arm, pp in cal_scores.items()},
                   "cal_data": cal_evidence, "utc": datetime.now(timezone.utc).isoformat()}
    cal_pin = write(HERE / "sgd_act_aux_calibration.json", calibration, True)
    write(OUT / "sgd-act-aux-calibration-frozen.json", {"calibration": cal_pin, "weights": weights_pin,
          "utc": datetime.now(timezone.utc).isoformat(), "EVAL_scored": False}, True)
    event("calibration_frozen", calibration=cal_pin)
    ev, eval_evidence = stream("EVAL", manifest, plan, services)
    assert set(train["groups"]) == group_sets["TRAIN"] and set(cal["groups"]) == group_sets["CAL"] and set(ev["groups"]) == group_sets["EVAL"]
    eval_scores = {arm: scores(bundle, arm, matrix(ev, arm)) for arm in ("context", "no_context")}
    permutation = np.random.default_rng(SEED + 1).permutation(len(ev["current"]))
    shuffled = [ev["previous"][i] for i in permutation]
    control_scores = {"drop_context": scores(bundle, "context", matrix(ev, "no_context")),
                      "shuffle_previous_system": scores(bundle, "context", matrix(ev, previous=shuffled)),
                      "empty_current": scores(bundle, "context", matrix(ev, current=[""] * len(shuffled))),
                      "empty_all_text": scores(bundle, "context", matrix(ev, current=[""] * len(shuffled), previous=[""] * len(shuffled)))}
    evaluation = {arm: metrics(ev["y"], ev["k"], pp, calibration["arms"][arm]) for arm, pp in eval_scores.items()}
    controls = {name: metrics(ev["y"], ev["k"], pp, calibration["arms"]["context"]) for name, pp in control_scores.items()}
    np.savez_compressed(CACHE / "eval-single-pass-scores.npz", **eval_scores, **control_scores)
    proposer = runtime.ActProposer(HERE / "sgd_act_aux_weights.json", HERE / "sgd_act_aux_calibration.json",
                                  weights_pin["sha256"], cal_pin["sha256"])
    parity_max, latency = 0., []
    for i in range(min(256, len(ev["current"]))):
        observed = {"speaker": "USER", "utterance": ev["current"][i], "earlier_context": [{"speaker": "SYSTEM", "text": ev["previous"][i]}]}
        start = time.perf_counter()
        actual = proposer.propose(observed)
        latency.append(time.perf_counter() - start)
        for j, act in enumerate(ACTS):
            p = actual["source_USER_acts"][act]["source_act_probability"]
            parity_max = max(parity_max, abs(p - eval_scores["context"][i, j]))
            threshold = calibration["arms"]["context"][act]["threshold"]
            assert actual["source_USER_acts"][act]["accepted_positive_proposal"] == (threshold is not None and eval_scores["context"][i, j] >= threshold)
        assert actual["bank_authority"] is None and actual["financial_authorization"] == "UNKNOWN"
        poisoned = {**observed, "targets": {"frames": [{"act": "AFFIRM"}]}, "current_gold": "permission", "bank_action": "transfer", "ancestry": {"label": "NEGATE"}}
        assert proposer.propose(poisoned) == actual
    assert parity_max < 1e-10
    assert sha(HERE / "sgd_act_aux_weights.json") == weights_pin["sha256"]
    assert sha(HERE / "sgd_act_aux_calibration.json") == cal_pin["sha256"]
    report = {"status": "completed_actual_CPU_fit_CAL_EVAL", "claims": {
          "EVAL": "INTERNAL DIAGNOSTIC ONLY: existing TRAIN-derived EVAL had prior experiment exposure; no fresh-independent or official dev/test claim",
          "source": "Official SGD TRAIN only; 132615 TRAIN + 16072 CAL + 16295 EVAL USER rows",
          "task": "Exact source USER acts AFFIRM/NEGATE/INFORM/REQUEST, multilabel; no bank authorization, Hooke/repayment integration or Freya validation",
          "historical_MiniLM_90_95": "B77 topic results, not SGD source acts, bank permissions or Freya"},
          "plan": plan_pin, "weights": weights_pin, "calibration": cal_pin, "weights_freeze": freeze_pin,
          "code": [pin(Path(__file__)), pin(HERE / "sgd_act_aux_runtime.py")], "source_pins": source_pins,
          "data": {"TRAIN": train_evidence, "CAL": cal_evidence, "EVAL": eval_evidence},
          "fit": {"epochs": EPOCHS, "seed": SEED, "heads_per_arm": 4, "arms": 2,
                  "rows_available": n, "rows_streamed": n, "fit_wall_seconds": fit_wall,
                  "fit_cpu_seconds": fit_cpu, "wall_limit_seconds": LIMIT,
                  "presentations_per_head": {a: dict(c) for a, c in fit_rows.items()},
                  "positive_weights_TRAIN_only": positive_weights, "selection_or_refit": False},
          "CAL": {a: metrics(cal["y"], cal["k"], pp, calibration["arms"][a]) for a, pp in cal_scores.items()},
          "EVAL": evaluation, "observed_only_negative_controls": controls,
          "checks": {**checks, "group_overlap": 0, "EVAL_source_stream_passes": 1,
                     "EVAL_selection_or_refit": False, "post_CAL_weights_unchanged": True,
                     "post_EVAL_calibration_unchanged": True, "runtime_target_injection_invariant": True,
                     "runtime_probability_parity_rows": len(latency), "runtime_probability_parity_max_abs_error": parity_max,
                     "runtime_latency_seconds_median": float(np.median(latency)), "runtime_latency_seconds_p95": float(np.percentile(latency, 95))},
          "metric_definitions": {"raw": "positive at p>=0.5 on source-known labels", "accepted": "positive at frozen CAL threshold; all other outcomes UNKNOWN",
                                 "recall": "accepted true positives / all known source positives", "coverage_known": "positive proposals / known labels",
                                 "coverage_all_rows": "positive proposals / all rows; source-unknown proposals counted separately",
                                 "precision_target": "empirical CAL criterion only, not a population guarantee; no minimum 20 floor"},
          "local_cache_artifacts": [pin(p) for p in sorted(CACHE.glob("*.npz"))],
          "job_wall_seconds": time.perf_counter() - JOB_START}
    report_pin = write(OUT / "sgd-act-aux-report.json", report, True)
    receipt = {"report": report_pin, "plan": plan_pin, "weights": weights_pin, "calibration": cal_pin,
               "files": [pin(p) for p in sorted(HERE.glob("sgd_act_aux_*")) if p.is_file()] + [pin(p) for p in sorted(OUT.glob("sgd-act-aux-*")) if p.is_file()],
               "job_wall_seconds": time.perf_counter() - JOB_START}
    receipt_pin = write(OUT / "sgd-act-aux-receipt.json", receipt, True)
    event("completed", report=report_pin, receipt=receipt_pin, job_wall_seconds=receipt["job_wall_seconds"])


if __name__ == "__main__":
    main()
