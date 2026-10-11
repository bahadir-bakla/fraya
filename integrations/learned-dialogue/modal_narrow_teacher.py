"""Bounded offline teacher; shared by CPU and the single-use Modal job.

No import/download/training at module import. Model must match the pinned file
manifest. No dev/calibration/qualification record enters this function.
"""
import hashlib
import json
import time
from pathlib import Path

from modal_narrow_core import canonical, digest, validate_payload

MODEL_ID = "intfloat/multilingual-e5-small"
REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


def verify_model(folder, manifest):
    if manifest["model_id"] != MODEL_ID or manifest["revision"] != REVISION or manifest["declared_license"] != "mit":
        raise ValueError("Pinned public encoder/license mismatch")
    for name, info in manifest["files"].items():
        if "/" in name or "\\" in name or name.startswith("."):
            raise ValueError("Only explicit top-level public model files allowed")
        path = Path(folder) / name
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024*1024), b""):
                hasher.update(chunk)
        if path.stat().st_size != info["size"] or hasher.hexdigest() != info["sha256"]:
            raise ValueError("Public model file hash mismatch: " + name)


def group_weights(rows):
    sizes = {}
    for row in rows:
        sizes[row["group"]] = sizes.get(row["group"], 0)+1
    return [1/(len(sizes)*sizes[r["group"]]) for r in rows]


def check_token_lengths(tokenizer, texts, cap=256):
    encoded = tokenizer(texts, padding=False, truncation=False, add_special_tokens=True)
    lengths = [len(ids) for ids in encoded["input_ids"]]
    if any(length > cap for length in lengths):
        raise ValueError("Tokenizer overflow: no truncation; lengths=" + str(lengths))
    return lengths


def run_teacher(payload_blob, expected_payload_sha, model_manifest, folder,
                compute_seconds, stop_epoch, device="cpu", download=False):
    started = time.monotonic()
    payload = validate_payload(payload_blob, expected_payload_sha)
    if payload["sources"]["model_manifest_sha256"] != digest(canonical(model_manifest)):
        raise ValueError("Model manifest not bound to admitted payload")
    if type(compute_seconds) is not int or not 1 <= compute_seconds <= 1800:
        raise ValueError("Bounded compute timeout required")
    deadline = min(started+compute_seconds, started+max(0, stop_epoch-time.time()))
    def remaining():
        if time.monotonic() >= deadline:
            raise TimeoutError("Compute/absolute deadline reached; no retry")
    remaining()
    if download:
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=MODEL_ID, revision=REVISION, token=False,
                          local_dir=str(folder), allow_patterns=list(model_manifest["files"]))
    remaining()
    verify_model(folder, model_manifest)
    import torch
    from transformers import AutoModel, AutoTokenizer
    torch.set_num_threads(2)
    torch.manual_seed(payload["contract"]["seed"])
    if device == "cuda" and (not torch.cuda.is_available() or torch.cuda.device_count() != 1):
        raise ValueError("Exactly one visible GPU required")
    if device not in ("cpu", "cuda"):
        raise ValueError("Explicit CPU or single CUDA device only")
    if device == "cuda":
        torch.cuda.set_per_process_memory_fraction(min(1.,24*1024**3/torch.cuda.get_device_properties(0).total_memory),0)
    tokenizer = AutoTokenizer.from_pretrained(str(folder), local_files_only=True, trust_remote_code=False)
    encoder = AutoModel.from_pretrained(str(folder), local_files_only=True,
                                        trust_remote_code=False, use_safetensors=True).to(device)
    encoder.eval()
    for parameter in encoder.parameters():
        parameter.requires_grad_(False)
    texts = [r["text"] for r in payload["rows"]]
    lengths = check_token_lengths(tokenizer, texts)
    embeddings = []
    encoded_at = time.monotonic()
    with torch.inference_mode():
        for start in range(0, len(texts), 16):
            remaining()
            batch = tokenizer(texts[start:start+16], padding=True, truncation=False, return_tensors="pt").to(device)
            hidden = encoder(**batch).last_hidden_state
            mask = batch["attention_mask"].unsqueeze(-1)
            pooled = (hidden*mask).sum(1)/mask.sum(1).clamp(min=1)
            embeddings.append(torch.nn.functional.normalize(pooled.float(), p=2, dim=1).cpu())
    encode_seconds = time.monotonic()-encoded_at
    x = torch.cat(embeddings).to(device)
    y = torch.tensor([r["y"] for r in payload["rows"]], dtype=torch.float32, device=device)
    w = torch.tensor(group_weights(payload["rows"]), device=device)
    head = torch.nn.Linear(x.shape[1], 1).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=.001, weight_decay=.0002)
    groups = {}
    for index, row in enumerate(payload["rows"]):
        groups.setdefault(row["group"], []).append(index)
    keys = sorted(groups)
    losses, steps = [], 0
    for epoch in range(3):
        for offset in range(0, len(keys), 16):
            remaining()
            selected_groups = keys[offset:offset+16]
            indices = [i for group in selected_groups for i in groups[group]]
            logits = head(x[indices]).squeeze(1)
            per_row = torch.nn.functional.binary_cross_entropy_with_logits(logits, y[indices], reduction="none")
            # Each selected group contributes equally; descendants share its mass.
            weight = w[indices]*len(keys)/len(selected_groups)
            loss = (per_row*weight).sum()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            steps += 1
            if steps >= 1000:
                break
        with torch.no_grad():
            losses.append(float((torch.nn.functional.binary_cross_entropy_with_logits(head(x).squeeze(1), y, reduction="none")*w).sum().cpu()))
        if steps >= 1000:
            break
    remaining()
    with torch.no_grad():
        logits = head(x).squeeze(1)
        raw_logits = logits.cpu().tolist()
        probability = torch.sigmoid(logits).cpu().tolist()
        correct = ((logits >= 0) == y.bool()).float()
        row_accuracy = float(correct.mean().cpu())
        group_accuracy = float((correct*w).sum().cpu())
    gpu = None
    if device == "cuda":
        gpu = {"name":torch.cuda.get_device_name(0), "peak_allocated_bytes":torch.cuda.max_memory_allocated(), "visible_gpus":torch.cuda.device_count()}
        if gpu["peak_allocated_bytes"] > 24*1024**3:
            raise ValueError("Measured VRAM exceeds planned 24GiB envelope")
    result = {"format":"narrow_frozen_teacher_result.v3", "task":payload["task"],
              "payload_sha256":digest(payload_blob), "model_manifest_sha256":digest(canonical(model_manifest)),
              "device":device, "dtype":"float32", "gpu":gpu,
              "encoder_frozen":all(not p.requires_grad for p in encoder.parameters()),
              "training_rows":len(texts), "training_groups":len(groups),
              "steps":steps, "epoch_group_ce":losses, "train_row_accuracy":row_accuracy,
              "train_group_mean_accuracy":group_accuracy, "encode_seconds":encode_seconds,
              "elapsed_seconds":time.monotonic()-started, "max_tokens":max(lengths),
              "head":{"weights":head.weight.detach().cpu().flatten().tolist(), "bias":float(head.bias.detach().cpu()[0])},
              "train_only_soft_targets":[{"id":r["id"], "group":r["group"], "logit":z, "probability":p} for r,z,p in zip(payload["rows"],raw_logits,probability)],
              "calibrated":False, "qualified":False, "decision":"abstain",
              "development_metrics":None, "qualification_metrics":None,
              "fine_tuning_enabled":False}
    # JSON return only: finite values, no tensors/pickle/encoder upload/authority.
    return canonical(result)
