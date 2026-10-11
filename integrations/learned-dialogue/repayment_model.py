"""Fresh masked multilabel teacher and matched students, NumPy CPU only."""
import numpy as np

SEED = 20261011
L2 = .01
T = 2.


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -80, 80)))


def support(y, mask, group_weight):
    positive = (y * mask * group_weight[:, None]).sum(0)
    negative = ((1 - y) * mask * group_weight[:, None]).sum(0)
    trained = (positive > 0) & (negative > 0)
    q = np.minimum(5., np.maximum(1., np.sqrt(negative / np.maximum(positive, 1e-12))))
    return positive, negative, q, trained


def init_student(k):
    rng = np.random.default_rng(SEED)
    return {"E": rng.normal(0, .15, (1024, 32)).astype(np.float32), "b": np.zeros(32, np.float32),
            "W": rng.normal(0, 1 / np.sqrt(32), (32, k)).astype(np.float32), "c": np.zeros(k, np.float32)}


def init_teacher(k):
    return {"W": np.zeros((384, k), np.float32), "c": np.zeros(k, np.float32)}


def forward(p, x):
    if "E" in p:
        h = np.tanh(x @ p["E"] + p["b"])
    else: h = x
    return h @ p["W"] + p["c"], h


def objective(p, x, y, mask, group_weight, class_weight, denominator, arm="hard", teacher=None, kl_denominator=None):
    if arm not in ("hard", "distill") or (arm == "distill" and teacher is None): raise ValueError("Invalid loss")
    if not all(np.isfinite(v).all() for v in [x, y, mask, group_weight, class_weight, denominator, *p.values()]):
        raise ValueError("Nonfinite inputs")
    z, h = forward(p, x); probability = sigmoid(z)
    known = mask * group_weight[:, None]
    weighted = np.where(y > .5, class_weight, 1.)
    bce = (1 - y) * np.logaddexp(0, z) + y * class_weight * np.logaddexp(0, -z)
    active = denominator > 0
    scale = known / np.maximum(denominator, 1e-12)[None, :] / max(1, int(active.sum()))
    scale[:, ~active] = 0
    data_loss = float((bce * scale).sum())
    dz = (probability - y) * weighted * scale
    if arm == "distill":
        if teacher.shape != z.shape or not np.isfinite(teacher).all(): raise ValueError("Invalid TRAIN teacher")
        q = sigmoid(teacher / T); s = sigmoid(z / T)
        kl = q * (np.log(np.maximum(q, 1e-30)) - np.log(np.maximum(s, 1e-30))) + (1 - q) * (np.log(np.maximum(1 - q, 1e-30)) - np.log(np.maximum(1 - s, 1e-30)))
        if kl_denominator is None: kl_denominator = known.sum(0)
        kl_scale = known / np.maximum(kl_denominator, 1e-12)[None, :] / max(1, int(active.sum()))
        kl_scale[:, ~active] = 0
        data_loss = .5 * data_loss + .5 * T * T * float((kl * kl_scale).sum())
        dz = .5 * dz + .5 * T * (s - q) * kl_scale
    grads = {"W": h.T @ dz, "c": dz.sum(0)}
    if "E" in p:
        dh = (dz @ p["W"].T) * (1 - h * h)
        grads.update(E=x.T @ dh, b=dh.sum(0))
    names = [k for k in p if k in ("E", "W")]; n = sum(p[k].size for k in names)
    reg = .5 * L2 * sum(float((p[k].astype(np.float64) ** 2).sum()) for k in names) / n
    data_norm = np.sqrt(sum(float((v.astype(np.float64) ** 2).sum()) for v in grads.values()))
    reg_norm = L2 * np.sqrt(sum(float((p[k].astype(np.float64) ** 2).sum()) for k in names)) / n
    for k in names: grads[k] += L2 * p[k] / n
    if not all(np.isfinite(v).all() for v in grads.values()): raise ValueError("Nonfinite gradient")
    return data_loss + reg, grads, {"data_loss": data_loss, "regularizer": reg,
           "data_gradient_norm": float(data_norm), "regularizer_gradient_norm": float(reg_norm),
           "hidden_saturation": float((np.abs(h) > .98).mean()) if "E" in p else None}


class Adam:
    def __init__(self, p, learning_rate=.003):
        self.m = {k: np.zeros_like(v) for k, v in p.items()}; self.v = {k: np.zeros_like(v) for k, v in p.items()}; self.t = 0
        self.learning_rate = learning_rate

    def update(self, p, g):
        self.t += 1
        for k in p:
            self.m[k] = .9 * self.m[k] + .1 * g[k]; self.v[k] = .999 * self.v[k] + .001 * g[k] ** 2
            p[k] -= self.learning_rate * (self.m[k] / (1 - .9 ** self.t)) / (np.sqrt(self.v[k] / (1 - .999 ** self.t)) + 1e-8)
            if not np.isfinite(p[k]).all(): raise ValueError("Nonfinite optimizer")
