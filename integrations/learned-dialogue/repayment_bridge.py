"""Explicit local artifact adapters for the parent builder. No platform/tool API."""
import hashlib
import json
from pathlib import Path
from repayment_runtime import decode, predict, observed_text


def pinned_bytes(path, digest):
    blob = Path(path).read_bytes()
    if hashlib.sha256(blob).hexdigest() != digest: raise ValueError("Artifact digest mismatch")
    return blob


class RepaymentStudent:
    def __init__(self, model_path, model_sha256, calibrator_path=None, calibrator_sha256=None):
        self.model = decode(pinned_bytes(model_path, model_sha256), model_sha256)
        self.calibrator = None
        if calibrator_path is not None:
            if not calibrator_sha256: raise ValueError("Calibrator requires frozen digest")
            self.calibrator = json.loads(pinned_bytes(calibrator_path, calibrator_sha256))
            if self.calibrator["bank_authority"] is not False or self.calibrator["qualified"] is not False: raise ValueError("Forbidden authority")
            if len(self.calibrator["temperature"]) != len(self.model["labels"]): raise ValueError("Calibration shape mismatch")

    def predict(self, inputs):
        return [predict(snapshot, self.model, self.calibrator) for snapshot in inputs]

    def proposal(self, snapshot, evidence_refs=None):
        result = predict(snapshot, self.model, self.calibrator)
        if result.get("reason") != "unknown_input":
            result["input_sha256"] = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        result["evidence_refs"] = evidence_refs
        result["refs_are_authenticated"] = False
        return result


class RepaymentTaskTeacher:
    """Builder/offline CPU reference: frozen MiniLM + fresh task head only."""
    def __init__(self, state_path, state_sha256, plan_path, plan_sha256, calibrator_path=None, calibrator_sha256=None):
        import numpy as np
        from safetensors.numpy import load_file
        from repayment_data import verify, ROOT
        from repayment_preflight import get_encoder
        plan = json.loads(pinned_bytes(plan_path, plan_sha256)); verify(plan["source_sha256"])
        # Verify encoder files only; no old Banking77 classifier is used.
        verify({p: h for p,h in plan["input_sha256"].items() if p.startswith("local-runs/customer-benchmark-day2-pretrained/encoder/")})
        pinned_bytes(state_path, state_sha256); self.p = load_file(str(state_path)); self.labels = plan["labels"]
        if self.p["W"].shape != (384, len(self.labels)) or self.p["c"].shape != (len(self.labels),) or not all(np.isfinite(v).all() for v in self.p.values()):
            raise ValueError("Teacher state shape/finite check")
        self.encoder = get_encoder(ROOT / plan["encoder"]["directory"])
        self.calibrator = None if calibrator_path is None else json.loads(pinned_bytes(calibrator_path, calibrator_sha256))

    def predict(self, inputs):
        import numpy as np
        from repayment_model import forward, sigmoid
        texts = [observed_text(s) for s in inputs]
        if any(len(self.encoder.tokenizer(t, truncation=False)["input_ids"]) > 256 for t in texts): raise ValueError("Input encoder truncation unsupported")
        emb = self.encoder.encode(texts); z, _ = forward(self.p, emb)
        t = np.ones(len(self.labels)) if self.calibrator is None else np.asarray(self.calibrator["temperature"])
        scores = sigmoid(z / t)
        return [{"label_scores": dict(zip(self.labels, map(float, row))), "abstain": True, "bank_authority": False,
                 "qualified": False, "reason": "offline_semantic_teacher_only"} for row in scores]
