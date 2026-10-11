"""Predeclared TRAIN diagnostics/export. No CAL/EVAL data files are loaded."""
import base64
import hashlib
import time
import numpy as np
from day2_distill_model import forward, logsoftmax, T
from day2_distill_runtime import decode, logits, FEATURE_VERSION
from day2_distill_data import encoded


def metrics(p, x, y, teacher, weights):
    z, h = forward(p, x)
    lp = logsoftmax(z)
    ql = logsoftmax(teacher / T)
    q = np.exp(ql)
    return {"rows": len(y), "CE_without_regularizer": float((-lp[np.arange(len(y)), y] * weights).mean()),
            "hard_accuracy": float(((z.argmax(1) == y) * weights).mean()),
            "teacher_top1_agreement": float(((z.argmax(1) == teacher.argmax(1)) * weights).mean()),
            "KL_T2": float(((q * (ql - logsoftmax(z / T))).sum(1) * weights).mean()),
            "teacher_entropy_T2": float((-(q * ql).sum(1) * weights).mean()),
            "hidden_saturation": float((np.abs(h) > .98).mean()), "bank_acceptance": 0, "qualified": False}


def bundle(p, labels, arm):
    return encoded({"schema": "day2_distill_student.v1", "feature_version": FEATURE_VERSION, "labels": labels,
                    "parameters": {k: base64.b64encode(v.astype("<f4").tobytes()).decode("ascii") for k, v in p.items()},
                    "arm": arm, "bank_authority": False, "qualified": False})


def parity(p, rows, x, labels, probes, arm):
    blob = bundle(p, labels, arm)
    model = decode(blob, hashlib.sha256(blob).hexdigest())
    native, _ = forward(p, x[probes])
    started = time.perf_counter()
    exported = np.asarray([logits(rows[i]["text"], model) for i in probes])
    seconds = time.perf_counter() - started
    mismatches = int((native.argmax(1) != exported.argmax(1)).sum())
    error = float(np.abs(native - exported).max())
    if mismatches or error > 1e-4:
        raise ValueError("Native/stdlb export parity failure")
    return blob, {"TRAIN_probes": len(probes), "classes_covered": len({rows[i]["source_label_id"] for i in probes}),
                  "max_abs_logit_error": error, "decision_mismatches": mismatches,
                  "mean_stdlib_inference_ms": seconds * 1000 / len(probes), "model_bytes": len(blob)}
