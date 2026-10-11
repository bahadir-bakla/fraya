"""Source/cache/mathematical tests: no optimizer steps and no authorization double."""
import base64
import copy
import hashlib
import numpy as np
from day2_distill_data import PINS, TRAIN, REVISION, check_cache_header, raw_teacher, identity, encoded
from day2_distill_runtime import features, decode, predict
from day2_distill_model import init, objective, NONBIAS, L2
from day2_distill_eval import bundle, parity


def run(rows, labels, teacher):
    checks = []
    def ok(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
    def rejects(name, fn):
        try:
            fn()
        except (ValueError, TypeError, KeyError):
            checks.append(name)
            return
        raise AssertionError(name)
    ok("parameter_count_35341", sum(v.size for v in init().values()) == 35341)
    ok("fresh_identical_initialization", all(np.array_equal(init()[k], init()[k]) for k in init()))
    for bad in (None, {}, [], 12, True, "", " ", "!", "x" * 4097):
        rejects("unknown_feature_" + str(type(bad).__name__) + "_" + str(len(checks)), lambda: features(bad))
    ok("metadata_cannot_enter_text_signature", features(rows[0]["text"]) == features(rows[0]["text"]))
    ok("feature_L2_norm", abs(sum(v * v for v in features("Card payment #123" ).values()) - 1) < 1e-12)
    ok("number_rule_shared", features("payment 123") == features("payment 999"))
    ok("order_digest_changes_on_reorder", identity(rows) != identity(list(reversed(rows))))
    h = {"__metadata__": {"split": "train", "input_sha256": PINS[TRAIN], "encoder_revision": REVISION},
         "embeddings": {"shape": [7943, 384], "dtype": "F32"}}
    for field, value in (("split", "eval"), ("input_sha256", "0" * 64), ("encoder_revision", "bad")):
        bad = copy.deepcopy(h); bad["__metadata__"][field] = value
        rejects("cache_reject_" + field, lambda: check_cache_header(bad))
    bad = copy.deepcopy(h); bad["embeddings"]["shape"] = [993, 384]
    rejects("cache_reject_wrong_shape", lambda: check_cache_header(bad))
    # Test the actual teacher decoder with a bounded fabricated shape-valid zero
    # input only; this is not supervision, a fitted artifact or an auth stand-in.
    head = {"weights_qint16": np.zeros((77, 384)), "weight_scales": np.ones(77), "intercept": np.arange(77.)}
    emb = np.zeros((7943, 384), np.float32)
    a = raw_teacher(emb, head)
    head.update(temperature=float("nan"), threshold="forbidden-calibration-input")
    ok("teacher_CAL_fields_ignored", np.array_equal(a, raw_teacher(emb, head)))
    head["weight_scales"][0] = float("nan")
    rejects("nonfinite_teacher_rejected", lambda: raw_teacher(emb, head))
    p = {k: v.astype(np.float64) for k, v in init().items()}
    x = np.zeros((5, 1024)); y = np.array([rows[i]["source_label_id"] for i in range(5)])
    for i in range(5):
        for j, v in features(rows[i]["text"]).items(): x[i, j] = v
    w = np.ones(5); t = teacher[:5].astype(np.float64)
    for arm in ("hard", "distill"):
        loss, g, d = objective(p, x, y, t, w, arm)
        ok(arm + "_finite_gradients", np.isfinite(loss) and all(np.isfinite(v).all() for v in g.values()))
        for k, idx in (("E", (list(features(rows[0]["text"]))[0], 0)), ("W", (0, 0)), ("b", (0,)), ("c", (0,))):
            old = p[k][idx]; eps = 1e-5
            p[k][idx] = old + eps; plus = objective(p, x, y, t, w, arm)[0]
            p[k][idx] = old - eps; minus = objective(p, x, y, t, w, arm)[0]
            p[k][idx] = old
            ok(arm + "_gradient_" + k, abs((plus - minus) / (2 * eps) - g[k][idx]) < 1e-6)
        expected = .5 * L2 * sum((p[k] ** 2).sum() for k in ("E", "W")) / NONBIAS
        ok(arm + "_mean_parameter_regularizer", abs(d["regularizer"] - expected) < 1e-14)
    _, _, hard = objective(p, x, y, t, w, "hard")
    ok("unscaled_CE_near_log77", 3 < hard["data_loss"] < 6)
    badt = t.copy(); badt[0, 0] = float("nan")
    rejects("nonfinite_training_target", lambda: objective(p, x, y, badt, w, "distill"))
    native = init(); blob, pp = parity(native, rows, x.astype(np.float32), labels, list(range(5)), "hard")
    ok("initialization_export_parity", pp["decision_mismatches"] == 0)
    sha = hashlib.sha256(blob).hexdigest(); model = decode(blob, sha)
    ok("unknown_runtime_abstains", predict({}, model)["abstain"] and predict({}, model)["bank_authority"] is False)
    rejects("tampered_hash_rejected", lambda: decode(blob + b" ", sha))
    import json
    obj = json.loads(blob); obj["parameters"]["c"] = base64.b64encode(np.full(77, np.nan, dtype="<f4").tobytes()).decode()
    badblob = encoded(obj)
    rejects("nonfinite_artifact_rejected", lambda: decode(badblob, hashlib.sha256(badblob).hexdigest()))
    return {"checks_passed": len(checks), "checks": checks, "optimizer_steps": 0, "fits": 0, "CAL_EVAL_rows_read": 0}
