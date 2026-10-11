"""Masked immutable scoring and CAL-only selection; no bank qualification."""
import base64
import hashlib
import math
import time
import numpy as np
from repayment_model import sigmoid, forward
from repayment_runtime import FEATURE_VERSION, decode, logits
from repayment_data import encoded, snapshot


def score(prob, y, mask, labels, threshold=None):
    if threshold is None: threshold = np.full(len(labels), .5)
    predicted = prob >= threshold[None, :]
    known = mask.astype(bool); positive = y.astype(bool)
    per = {}; total = np.zeros(3, dtype=int); f1s = []
    for j, label in enumerate(labels):
        tp = int((predicted[:, j] & positive[:, j] & known[:, j]).sum())
        fp = int((predicted[:, j] & ~positive[:, j] & known[:, j]).sum())
        fn = int((~predicted[:, j] & positive[:, j] & known[:, j]).sum())
        n = int(known[:, j].sum()); denom = 2 * tp + fp + fn
        f1 = 2 * tp / denom if denom else 0.
        if n: f1s.append(f1)
        per[label] = {"known": n, "unknown": len(y) - n, "positive": int((positive[:, j] & known[:, j]).sum()),
            "tp": tp, "fp": fp, "fn": fn, "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None, "F1": f1,
            "prediction_coverage_known": (tp + fp) / n if n else None}
        total += [tp, fp, fn]
    tp, fp, fn = map(int, total); den = 2 * tp + fp + fn
    return {"rows": len(y), "known_elements": int(known.sum()), "unknown_elements": int((~known).sum()),
            "micro_F1": 2 * tp / den if den else 0., "macro_F1_known_heads": float(np.mean(f1s)) if f1s else None,
            "micro_precision": tp / (tp + fp) if tp + fp else None, "micro_recall": tp / (tp + fn) if tp + fn else None,
            "per_class": per, "bank_authority": False, "qualified": False}


def calibrate(z, y, mask, trained, fit_ix=None, select_ix=None):
    if fit_ix is None: fit_ix = np.arange(len(y))
    if select_ix is None: select_ix = np.arange(len(y))
    temperatures = []; thresholds = []; records = []
    for j in range(z.shape[1]):
        fi = fit_ix[mask[fit_ix, j] > 0]; si = select_ix[mask[select_ix, j] > 0]
        fy, sy = y[fi, j], y[si, j]; t = 1.
        temp_available = bool(trained[j] and len(fy) and (fy > .5).any() and (fy < .5).any())
        selection_available = bool(trained[j] and len(sy) and (sy > .5).any() and (sy < .5).any())
        if temp_available:
            losses = [(float((np.logaddexp(0, z[fi, j] / candidate) - fy * z[fi, j] / candidate).mean()), candidate) for candidate in (.5, 1., 2., 4.)]
            t = min(losses)[1]
        p = sigmoid(z[si, j] / t); chosen = 1.000001; grid = []
        for threshold in (.5, .6, .7, .8, .9):
            accepted = p >= threshold; n = int(accepted.sum())
            precision = float(sy[accepted].mean()) if n else None
            grid.append({"threshold": threshold, "accepted": n, "precision": precision})
        valid = [v for v in grid if selection_available and v["accepted"] >= 3 and v["precision"] >= .90]
        if valid: chosen = max(valid, key=lambda v: (v["accepted"], -v["threshold"]))["threshold"]
        temperatures.append(t); thresholds.append(chosen)
        records.append({"temperature_fit_known": len(fy), "temperature_fit_positive": int(fy.sum()), "temperature_available": temp_available,
                        "threshold_select_known": len(sy), "threshold_select_positive": int(sy.sum()), "selective_available": selection_available,
                        "grid": grid,
                        "warning": "CAL-selected empirical estimates; no safety or independent-risk bound"})
    return {"temperature": temperatures, "threshold": thresholds, "per_class_CAL": records,
            "trained_heads": list(map(bool, trained)), "qualified": False, "bank_authority": False}


def student_blob(p, labels, arm):
    return encoded({"schema": "repayment_student.v1", "features": FEATURE_VERSION, "labels": labels,
      "parameters": {k: base64.b64encode(v.astype("<f4").tobytes()).decode() for k, v in p.items()},
      "qualified": False, "bank_authority": False, "arm": arm})


def export_parity(p, blob, rows, x, calibrator=None):
    model = decode(blob, hashlib.sha256(blob).hexdigest()); native, _ = forward(p, x)
    times = []; exported = []
    for row in rows:
        start = time.perf_counter(); exported.append(logits(snapshot(row), model)); times.append((time.perf_counter() - start) * 1000)
    exported = np.asarray(exported); max_error = float(np.abs(native - exported).max())
    raw_flips = int(((native >= 0) != (exported >= 0)).sum())
    selected_flips = 0
    if calibrator is not None:
        t, threshold = np.asarray(calibrator["temperature"]), np.asarray(calibrator["threshold"])
        selected_flips = int(((sigmoid(native / t) >= threshold) != (sigmoid(exported / t) >= threshold)).sum())
    if max_error > 1e-4 or raw_flips or selected_flips: raise ValueError("Native/stdlb parity mismatch")
    return exported, {"rows": len(rows), "head_elements": int(native.size), "max_logit_error": max_error,
         "raw_decision_flips": raw_flips, "calibrated_decision_flips": selected_flips,
         "latency_p50_ms": float(np.percentile(times, 50)), "latency_p95_ms": float(np.percentile(times, 95))}


def slices(prob, y, mask, labels, rows, threshold):
    result = {}
    all_tags = sorted(set(tag for r in rows for tag in r.get("diagnostic_tags", [])))
    for tag in all_tags:
        ix = np.array([tag in r.get("diagnostic_tags", []) for r in rows])
        result[tag] = score(prob[ix], y[ix], mask[ix], labels, threshold)
    return result
