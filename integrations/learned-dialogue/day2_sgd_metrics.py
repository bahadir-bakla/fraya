"""Masked conditional source metrics. Masks are denominators, never routing."""
from collections import defaultdict
import math
import numpy as np

HEADS = ("intent", "requested", "presence", "acts")


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -60, 60)))


class Records:
    def __init__(self, spec):
        self.spec = spec
        self.values = {h: [] for h in HEADS}
        self.domains = {h: [] for h in HEADS}
        self.support = {h: defaultdict(int) for h in HEADS}

    def add(self, logits, y, masks):
        for sid, service in enumerate(self.spec["services"]):
            domain = service["name"].split("_")[0]
            a, c = service["intent_offset"], len(service["intents"])
            known = masks["intent"][:, sid].astype(bool)
            for scores, target in zip(logits["intent"][known, a:a + c], y["intent"][known, sid]):
                self.values["intent"].append((scores.copy(), int(target), sid))
                self.domains["intent"].append(domain)
                self.support["intent"][service["name"] + "::" + service["intents"][int(target)]] += 1
            for h in HEADS[1:]:
                a = service["act_offset"] if h == "acts" else service["slot_offset"]
                c = len(self.spec["acts"]) if h == "acts" else len(service["slots"])
                known = masks[h][:, a:a + c].astype(bool)
                self.values[h].extend(zip(logits[h][:, a:a + c][known].tolist(), y[h][:, a:a + c][known].astype(int).tolist()))
                self.domains[h].extend([domain] * int(known.sum()))
                self.support[h][service["name"] + ":known"] += int(known.sum())
                self.support[h][service["name"] + ":positive"] += int(y[h][:, a:a + c][known].sum())

    def calibration(self, select):
        result = {}
        for h in HEADS:
            temperatures = [.25, .5, 1., 2., 4.]
            def nll(t):
                if not self.values[h]:
                    return None
                if h == "intent":
                    values = []
                    for z, target, _ in self.values[h]:
                        z = z / t
                        maximum = z.max()
                        values.append(float(maximum + np.log(np.exp(z - maximum).sum()) - z[target]))
                    return float(np.mean(values))
                z = np.asarray([r[0] for r in self.values[h]]) / t
                y = np.asarray([r[1] for r in self.values[h]])
                return float(np.mean(np.logaddexp(0, z) - y * z))
            losses = [(t, nll(t)) for t in temperatures]
            temperature = min(losses, key=lambda r: r[1])[0] if self.values[h] else 1.
            if h == "intent":
                confidence, correct = [], []
                for z, target, _ in select.values[h]:
                    z = z / temperature
                    p = np.exp(z - z.max()); p /= p.sum()
                    confidence.append(float(p.max())); correct.append(int(p.argmax() == target))
                confidence, correct = np.asarray(confidence), np.asarray(correct)
            else:
                confidence = sigmoid(np.asarray([r[0] for r in select.values[h]]) / temperature)
                correct = np.asarray([r[1] for r in select.values[h]])
            candidates = []
            for threshold in np.linspace(0, 1, 101):
                accepted = confidence >= threshold
                count = int(accepted.sum())
                precision = float(correct[accepted].mean()) if count else None
                if count and precision >= .95:
                    candidates.append((count, float(threshold), precision))
            best = max(candidates, key=lambda r: (r[0], -r[1])) if candidates else None
            result[h] = {"temperature": temperature, "threshold": best[1] if best else 1., "available": best is not None and bool(self.values[h]), "cal_fit_known": len(self.values[h]), "cal_select_known": len(select.values[h]), "cal_select_accepted": best[0] if best else 0, "cal_select_precision": best[2] if best else None, "temperature_grid_nll": losses, "selection_limit": "Empirical 95% accepted precision; no minimum deployment/admission floor; in-sample selection, not a guarantee"}
        return result

    def report(self, calibration):
        out = {}
        for h in HEADS:
            cfg = calibration[h]
            if h == "intent":
                confusion = np.zeros((self.spec["intent_count"], self.spec["intent_count"]), dtype=np.int64)
                confidence, correct = [], []
                for z, target, sid in self.values[h]:
                    p = np.exp(z / cfg["temperature"] - np.max(z / cfg["temperature"])); p /= p.sum()
                    pred = int(p.argmax()); offset = self.spec["services"][sid]["intent_offset"]
                    confusion[offset + target, offset + pred] += 1
                    confidence.append(float(p.max())); correct.append(int(pred == target))
                support = confusion.sum(1); predicted = confusion.sum(0); tp = confusion.diagonal()
                f1 = np.divide(2 * tp, support + predicted, out=np.zeros_like(tp, dtype=float), where=(support + predicted) > 0)
                recall = np.divide(tp, support, out=np.zeros_like(tp, dtype=float), where=support > 0)
                names = [s["name"] + "::" + name for s in self.spec["services"] for name in s["intents"]]
                accepted = np.asarray(confidence) >= cfg["threshold"] if cfg["available"] else np.zeros(len(correct), bool)
                known = len(correct)
                out[h] = {"known": known, "accuracy": float(np.mean(correct)) if known else None, "macro_f1_supported_classes": float(f1[support > 0].mean()) if (support > 0).any() else None, "per_class": {name: {"support": int(n), "recall": float(r) if n else None, "f1": float(f) if n else None} for name, n, r, f in zip(names, support, recall, f1)}, "accepted": int(accepted.sum()), "accepted_precision": float(np.asarray(correct)[accepted].mean()) if accepted.any() else None, "coverage": float(accepted.mean()) if known else None, "scope": "Conditional known-frame intents; all26 services were scored, no end-to-end routing/DST claim"}
                error = 1 - np.asarray(correct, dtype=float)
            else:
                probability = sigmoid(np.asarray([r[0] for r in self.values[h]]) / cfg["temperature"])
                truth = np.asarray([r[1] for r in self.values[h]], dtype=bool)
                pred = probability >= cfg["threshold"] if cfg["available"] else np.zeros(len(truth), bool)
                tp, fp, fn, tn = [int(a.sum()) for a in [pred & truth, pred & ~truth, ~pred & truth, ~pred & ~truth]]
                out[h] = {"known": len(truth), "positive_support": int(truth.sum()), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "f1": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None, "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None, "available": cfg["available"], "support": dict(self.support[h])}
                error = (pred != truth).astype(float)
            domain_metrics = {}
            for domain in sorted(set(self.domains[h])):
                idx = np.asarray([d == domain for d in self.domains[h]])
                domain_metrics[domain] = {"known": int(idx.sum()), "error_rate": float(error[idx].mean())}
            out[h]["per_domain"] = domain_metrics
        return out
