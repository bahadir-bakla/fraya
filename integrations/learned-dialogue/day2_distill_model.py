"""Matched fresh NumPy students. Data/group CE is never divided by log(77)."""
import numpy as np

SEED = 20261011
L2 = .01
T = 2.0
NONBIAS = 1024 * 32 + 32 * 77


def init():
    rng = np.random.default_rng(SEED)
    return {"E": rng.normal(0, .15, (1024, 32)).astype(np.float32), "b": np.zeros(32, np.float32),
            "W": rng.normal(0, 1 / np.sqrt(32), (32, 77)).astype(np.float32), "c": np.zeros(77, np.float32)}


def softmax(z):
    e = np.exp(z - z.max(1, keepdims=True))
    return e / e.sum(1, keepdims=True)


def logsoftmax(z):
    a = z - z.max(1, keepdims=True)
    return a - np.log(np.exp(a).sum(1, keepdims=True))


def forward(p, x):
    h = np.tanh(x @ p["E"] + p["b"])
    return h @ p["W"] + p["c"], h


def objective(p, x, y, teacher, weights, arm):
    if arm not in ("hard", "distill"):
        raise ValueError("Unknown objective")
    if not all(np.isfinite(v).all() for v in (x, teacher, weights, *p.values())) or (weights <= 0).any():
        raise ValueError("Nonfinite/invalid training input")
    z, h = forward(p, x)
    logp = logsoftmax(z)
    prob = np.exp(logp)
    g = prob.copy()
    g[np.arange(len(y)), y] -= 1
    ce = -logp[np.arange(len(y)), y]
    tq = logsoftmax(teacher / T)
    q = np.exp(tq)
    st = logsoftmax(z / T)
    kl = (q * (tq - st)).sum(1)
    data = ce if arm == "hard" else .5 * ce + .5 * T * T * kl
    if arm == "distill":
        g = .5 * g + .5 * T * (np.exp(st) - q)
    g *= (weights / len(y))[:, None]
    dh = (g @ p["W"].T) * (1 - h * h)
    grads = {"W": h.T @ g, "c": g.sum(0), "E": x.T @ dh, "b": dh.sum(0)}
    data_norm = float(np.sqrt(sum(float((v.astype(np.float64) ** 2).sum()) for v in grads.values())))
    reg = .5 * L2 * sum(float((p[k].astype(np.float64) ** 2).sum()) for k in ("E", "W")) / NONBIAS
    reg_norm = L2 * np.sqrt(sum(float((p[k].astype(np.float64) ** 2).sum()) for k in ("E", "W"))) / NONBIAS
    for k in ("E", "W"):
        grads[k] += L2 * p[k] / NONBIAS
    if not all(np.isfinite(v).all() for v in grads.values()):
        raise ValueError("Nonfinite gradient")
    return float((weights * data).mean() + reg), grads, {"data_loss": float((weights * data).mean()), "regularizer": reg,
            "data_gradient_norm": data_norm, "regularizer_gradient_norm": float(reg_norm),
            "hidden_saturation": float((np.abs(h) > .98).mean())}


class Adam:
    def __init__(self, p):
        self.m = {k: np.zeros_like(v) for k, v in p.items()}
        self.v = {k: np.zeros_like(v) for k, v in p.items()}
        self.step = 0

    def update(self, p, grads):
        self.step += 1
        for k in p:
            self.m[k] = .9 * self.m[k] + .1 * grads[k]
            self.v[k] = .999 * self.v[k] + .001 * grads[k] ** 2
            p[k] -= .003 * (self.m[k] / (1 - .9 ** self.step)) / (np.sqrt(self.v[k] / (1 - .999 ** self.step)) + 1e-8)
            if not np.isfinite(p[k]).all():
                raise ValueError("Nonfinite optimizer state")
