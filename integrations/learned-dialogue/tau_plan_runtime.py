"""Offline source-scenario planning only; NOT observed-user intent or permission."""
import base64
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parents[2]
FEATURE_VERSION = "tau-source-instructions-persona-window640-stride480-v1"


def source_text(spec):
    if type(spec) is not dict or set(spec) != {"instructions", "persona"}: raise ValueError("Wrong source-spec fields")
    instructions = spec["instructions"]
    if type(instructions) is not dict: raise ValueError("Instructions are source fields, not dialogue")
    lines = []
    for key in sorted(instructions):
        value = instructions[key]
        if type(key) is not str or (value is not None and type(value) is not str): raise ValueError("Unsupported structured source field")
        if value is not None: lines.append(key + ": " + value)
    persona = spec["persona"]
    if persona is not None:
        if type(persona) is not str: raise ValueError("Unsupported persona")
        lines.append("persona: " + persona)
    text = "\n".join(lines)
    if not text.strip() or len(text) > 20000: raise ValueError("Empty/oversized source text")
    return text


def windows(text):
    if type(text) is not str or not text: raise ValueError("Invalid source text")
    return [text[start:start + 640] for start in range(0, len(text), 480)]


def load_encoder(directory, source_sha256):
    path = ROOT / "integrations/learned-dialogue/day2_pretrained_runtime.py"
    if hashlib.sha256(path.read_bytes()).hexdigest() != source_sha256: raise ValueError("Encoder loader source changed")
    spec = importlib.util.spec_from_file_location("tau_plan_encoder_reference", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.FrozenEncoder(directory, threads=2)


def encode_specs(encoder, specs, deadline=None):
    import numpy as np
    chunks = []; ranges = []; max_tokens = 0
    for spec in specs:
        current = windows(source_text(spec)); accepted = []
        stack = list(reversed(current))
        while stack:
            chunk = stack.pop(); tokens = len(encoder.tokenizer(chunk, truncation=False)["input_ids"])
            max_tokens = max(max_tokens, tokens)
            if tokens > 256:
                if len(chunk) < 2: raise ValueError("Unencodable source window")
                mid = len(chunk) // 2; stack += [chunk[mid:], chunk[:mid]]
            else: accepted.append(chunk)
        start = len(chunks); chunks += accepted; ranges.append((start, len(chunks)))
    vectors = encoder.encode(chunks, deadline=deadline)
    result = np.asarray([vectors[a:b].mean(0) for a,b in ranges], np.float32)
    result /= np.maximum(np.linalg.norm(result, axis=1, keepdims=True), 1e-12)
    if not np.isfinite(result).all(): raise ValueError("Nonfinite source embeddings")
    return result, {"source_rows": len(specs), "encoded_windows": len(chunks), "largest_presplit_token_count": max_tokens,
                    "all_source_characters_covered": True, "token_truncation": False, "window_mean_L2_normalized": True}


def decode_head(blob, expected_sha256):
    if hashlib.sha256(blob).hexdigest() != expected_sha256: raise ValueError("Head hash mismatch")
    h = json.loads(blob)
    if h["schema"] != "tau_plan_reference_inclusion.v1" or h["features"] != FEATURE_VERSION or h["bank_authority"] is not False or h["observed_utterance"] is not False:
        raise ValueError("Wrong target/authority contract")
    labels = h["labels"]
    if len(set(labels)) != len(labels) or not 1 <= len(labels) <= 128: raise ValueError("Invalid operation labels")
    parameters = {}
    for name, count in (("W", 384 * len(labels)), ("b", len(labels))):
        raw = base64.b64decode(h["parameters"][name], validate=True)
        if len(raw) != count * 4: raise ValueError("Invalid shape")
        values = struct.unpack("<" + str(count) + "f", raw)
        if not all(math.isfinite(v) for v in values): raise ValueError("Nonfinite head")
        parameters[name] = values
    h["decoded"] = parameters
    return h


def stdlib_logits(head, embedding):
    k = len(head["labels"])
    if len(embedding) != 384 or not all(math.isfinite(float(v)) for v in embedding): raise ValueError("Invalid embedding")
    return [head["decoded"]["b"][j] + sum(float(embedding[i]) * head["decoded"]["W"][i*k+j] for i in range(384)) for j in range(k)]


class SourcePlanningModel:
    def __init__(self, head_path, head_sha256, plan_path, plan_sha256):
        from tau_plan_data import verify
        data = Path(plan_path).read_bytes()
        if hashlib.sha256(data).hexdigest() != plan_sha256: raise ValueError("Plan hash mismatch")
        self.plan = json.loads(data); verify(self.plan["code_sha256"]); verify(self.plan["encoder_sha256"])
        self.head = decode_head(Path(head_path).read_bytes(), head_sha256)
        self.encoder = load_encoder(ROOT / self.plan["encoder_directory"], self.plan["encoder_loader_sha256"])

    def plan_source_specs(self, specs):
        emb, _ = encode_specs(self.encoder, specs)
        result = []
        for vector in emb:
            z = stdlib_logits(self.head, vector)
            scores = {label: 1 / (1 + math.exp(-max(-80., min(80., value)))) for label,value in zip(self.head["labels"],z)}
            result.append({"literal_reference_inclusion_scores": scores, "trained_head_mask": self.head["trained_head_mask"],
                "target": "appears_in_publisher_reference_annotation_not_all_valid_tools", "bank_authority": False,
                "observed_utterance": False, "financial_masks": "UNKNOWN", "qualified": False})
        return result
