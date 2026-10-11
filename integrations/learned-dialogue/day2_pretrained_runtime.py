"""CPU-only offline MiniLM teacher + plain JSON 77-intent head. No bank tool.

No remote code, token, pickle/joblib or external inference. Encoder loaded only
from the explicitly pinned, locally copied safetensors directory in the head.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FrozenEncoder:
    def __init__(self, directory, threads=2):
        self.directory = Path(directory)
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass
        config = json.loads((self.directory / "config.json").read_text())
        assert config["model_type"] == "bert" and config["hidden_size"] == 384
        assert "auto_map" not in config
        pooling = json.loads((self.directory / "1_Pooling/config.json").read_text())
        assert pooling["pooling_mode_mean_tokens"] and not pooling["pooling_mode_cls_token"] and not pooling["pooling_mode_max_tokens"]
        self.max_length = 256
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.directory), local_files_only=True, token=False, trust_remote_code=False, use_fast=True)
        self.model = AutoModel.from_pretrained(str(self.directory), local_files_only=True, token=False, trust_remote_code=False, use_safetensors=True, attn_implementation="eager").to("cpu").eval()
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)
        assert all(not p.requires_grad and p.device.type == "cpu" for p in self.model.parameters())

    def encode(self, texts, batch_size=32, deadline=None, progress=False):
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        output = np.zeros((len(texts), 384), dtype=np.float32)
        with torch.inference_mode():
            for start in range(0, len(order), batch_size):
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("CPU experiment wall-time bound exceeded")
                indices = order[start:start + batch_size]
                inputs = self.tokenizer([texts[i] for i in indices], padding=True, truncation=True, max_length=self.max_length, return_tensors="pt")
                tokens = self.model(**inputs).last_hidden_state
                mask = inputs["attention_mask"].unsqueeze(-1).to(tokens.dtype)
                pooled = (tokens * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
                embeddings = torch.nn.functional.normalize(pooled, p=2, dim=1)
                output[indices] = embeddings.cpu().numpy()
                if progress and (start % 1024 == 0 or start + batch_size >= len(order)):
                    print(f"encoded {min(start + batch_size, len(order))}/{len(order)}", flush=True)
        assert output.shape == (len(texts), 384) and np.isfinite(output).all()
        assert np.allclose(np.linalg.norm(output, axis=1), 1, atol=2e-5)
        return output


def head_arrays(head):
    weights = np.asarray(head["weights_qint16"], dtype=np.float64) * np.asarray(head["weight_scales"], dtype=np.float64)[:, None]
    intercept = np.asarray(head["intercept"], dtype=np.float64)
    assert weights.shape == (77, 384) and intercept.shape == (77,)
    return weights, intercept


def head_logits(head, embeddings):
    weights, intercept = head_arrays(head)
    return np.asarray(embeddings, dtype=np.float64) @ weights.T + intercept


def probabilities(logits, temperature):
    values = logits / temperature
    values -= values.max(axis=1, keepdims=True)
    values = np.exp(values)
    return values / values.sum(axis=1, keepdims=True)


class OfflineIntentTeacher:
    def __init__(self, head_path):
        self.head = json.loads(Path(head_path).read_text(encoding="utf-8"))
        directory = ROOT / self.head["encoder"]["local_directory"]
        for name, record in self.head["encoder"]["files"].items():
            assert sha(directory / name) == record["sha256"], name
        self.encoder = FrozenEncoder(directory)

    def predict(self, texts):
        features = self.encoder.encode(texts)
        prob = probabilities(head_logits(self.head, features), self.head["temperature"])
        indices = prob.argmax(axis=1)
        confidence = prob.max(axis=1)
        return [{"source_label_id": int(i), "source_label": self.head["labels"][i], "confidence": float(c), "abstain": bool(c < self.head["threshold"]), "bank_permission": None, "ledger_truth": None} for i, c in zip(indices, confidence)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--head", required=True)
    parser.add_argument("--text", action="append", required=True)
    args = parser.parse_args()
    print(json.dumps(OfflineIntentTeacher(args.head).predict(args.text), ensure_ascii=False, indent=2))
