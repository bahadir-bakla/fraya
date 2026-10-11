"""Meaningful CPU source/gradient/mask/scorer tests, no fit or auth substitute."""
import copy
import hashlib
import numpy as np
from repayment_runtime import observed_text, features, decode, predict
from repayment_data import snapshot, targets, encoded
from repayment_model import init_student, init_teacher, objective, forward, support
from repayment_eval import score, student_blob, export_parity, calibrate


def run():
    checks = []
    def ok(name, value):
        if not value: raise AssertionError(name)
        checks.append(name)
    def reject(name, fn):
        try: fn()
        except (ValueError, TypeError, KeyError): checks.append(name); return
        raise AssertionError(name)
    def inp(user, previous):
        return {"current_utterance": {"speaker": "USER", "text": user}, "previous_utterances": [{"speaker": "SYSTEM", "text": previous}]}
    inputs = [inp("Yes", "Do you promise to pay?"), inp("Yes", "Are you disputing this?"), inp("I do not promise payment", "What can you do?")]
    rows = [{"input": x} for x in inputs]
    ok("same_utterance_different_context_features", features(inputs[0]) != features(inputs[1]))
    ok("no_context_ablation_really_removes_context", features(inputs[0], True) == features(inputs[1], True))
    ok("negation_is_retained", "not" in observed_text(inputs[2]))
    for bad in (None, {}, inp([], "x"), inp("", "x"), {"current_utterance": {"speaker": "USER", "text": "x"}, "previous_utterances": True},
                dict(inp("x", "x"), permission=True)):
        reject("unknown_input_" + str(len(checks)), lambda: observed_text(bad))
    extra = {"input": inputs[0], "labels": {"promise": True}, "group_id": "x", "source_label": "anything"}
    changed = copy.deepcopy(extra); changed["labels"] = {"promise": False}; changed["group_id"] = "another"
    ok("labels_group_source_metadata_never_features", features(snapshot(extra)) == features(snapshot(changed)))
    reject("labels_not_truthy_strings", lambda: targets({"labels": {"a": "false"}, "known_mask": {"a": True}}, ["a"]))
    yy, mm = targets({"labels": {"a": 0, "b": 0, "c": 1}, "known_mask": {"a": False, "b": True, "c": True}}, ["a", "b", "c"])
    ok("unknown_masks_not_negative", yy == [0, 0, 1] and mm == [0, 1, 1])
    y = np.array([[1., 0., 0.], [0., 1., 0.], [0., 0., 0.]])
    mask = np.array([[1., 1., 0.], [1., 1., 0.], [1., 1., 0.]])
    gw = np.ones(3); pos, neg, q, trained = support(y, mask, gw)
    ok("unknown_head_untrained", trained.tolist() == [True, True, False])
    den = (mask * np.where(y > .5, q, 1.)).sum(0)
    x = np.zeros((3, 1024), np.float64)
    for i, s in enumerate(inputs):
        for j, v in features(s).items(): x[i, j] = v
    teacher = np.array([[2., -2., 0.], [-2., 2., 0.], [-1., -1., 0.]])
    for name, p, xx, arm in (("teacher", init_teacher(3), x[:, :384], "hard"),
                             ("student_hard", init_student(3), x, "hard"),
                             ("student_distill", init_student(3), x, "distill")):
        p = {k: v.astype(np.float64) for k, v in p.items()}
        loss, gradients, stats = objective(p, xx, y, mask, gw, q, den, arm, teacher)
        ok(name + "_finite", np.isfinite(loss) and all(np.isfinite(v).all() for v in gradients.values()))
        for key in p:
            idx = (0, 0) if p[key].ndim == 2 else (0,); old = p[key][idx]; eps = 1e-5
            p[key][idx] = old + eps; plus = objective(p, xx, y, mask, gw, q, den, arm, teacher)[0]
            p[key][idx] = old - eps; minus = objective(p, xx, y, mask, gw, q, den, arm, teacher)[0]
            p[key][idx] = old
            ok(name + "_gradient_" + key, abs((plus - minus) / (2 * eps) - gradients[key][idx]) < 1e-6)
        different = y.copy(); different[:, 2] = 1
        ok(name + "_unknown_value_has_no_loss_effect", abs(objective(p, xx, different, mask, gw, q, den, arm, teacher)[0] - loss) < 1e-12)
    metrics = score(np.array([[.9, .1, .9], [.8, .9, .9], [.1, .1, .9]]), y, mask, ["a", "b", "unknown"])
    ok("scorer_expected_tp_fp_fn", metrics["per_class"]["a"]["tp"] == 1 and metrics["per_class"]["a"]["fp"] == 1 and metrics["per_class"]["a"]["fn"] == 0)
    ok("scorer_unknown_not_counted", metrics["known_elements"] == 6 and metrics["per_class"]["unknown"]["known"] == 0)
    p = init_student(3); blob = student_blob(p, ["a", "b", "c"], "hard")
    z, parity = export_parity(p, blob, rows, x.astype(np.float32))
    ok("native_serialized_runtime_parity", parity["raw_decision_flips"] == 0)
    model = decode(blob, hashlib.sha256(blob).hexdigest())
    ok("pure_runtime_authority_false_abstains", predict(inputs[0], model)["bank_authority"] is False and predict(inputs[0], model)["abstain"] is True)
    ok("unknown_runtime_abstains", predict(None, model)["reason"] == "unknown_input")
    reject("hash_tamper", lambda: decode(blob + b" ", hashlib.sha256(blob).hexdigest()))
    import json
    obj = json.loads(blob); obj["bank_authority"] = True; bad = encoded(obj)
    reject("authority_bundle_rejected", lambda: decode(bad, hashlib.sha256(bad).hexdigest()))
    cal = calibrate(teacher, y, mask, trained)
    ok("untrained_CAL_head_closed", cal["threshold"][2] > 1)
    return {"checks_passed": len(checks), "checks": checks, "optimizer_steps": 0, "model_fits": 0,
            "source_only_tests_not_semantic_gold": True}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), ensure_ascii=True))
