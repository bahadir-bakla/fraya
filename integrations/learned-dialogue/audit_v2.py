"""Offline integrity checks, not a statistical independence certification."""
import hashlib
import re
from collections import Counter


def audit_splits(train, dev):
    def values(rows, field):
        return {r["source"][field] for r in rows if r.get("source", {}).get(field)}
    train_groups = {r["lineage_group_id"] for r in train}
    dev_groups = {r["lineage_group_id"] for r in dev}
    if train_groups & dev_groups:
        raise ValueError("Train/development lineage overlap")
    overlaps = {}
    for field in ("template_root", "scenario_root", "source_document_or_conversation_id"):
        overlaps[field] = sorted(values(train, field) & values(dev, field))
        if overlaps[field]:
            raise ValueError("Cross-split source/template/scenario overlap: " + field)
    def normalized(rows):
        return {re.sub(r"\s+", " ", r["input"]["utterance"]["text"].casefold()).strip() for r in rows}
    exact = normalized(train) & normalized(dev)
    if exact:
        raise ValueError("Cross-split normalized utterance duplicates")
    train_ids = {r["example_id"] for r in train}
    dev_ids = {r["example_id"] for r in dev}
    for rows, other_ids in ((train, dev_ids), (dev, train_ids)):
        if any(set(r.get("source", {}).get("augmentation_parent_ids", [])) & other_ids for r in rows):
            raise ValueError("Cross-split augmentation parent")
    authors = values(train + dev, "author_or_actor_id")
    reviewed = sum(r.get("annotation", {}).get("independent_reviewer_count", 0) >= 2 for r in train + dev)
    return {"train_rows": len(train), "development_rows": len(dev), "train_lineage_groups": len(train_groups),
            "development_lineage_groups": len(dev_groups), "declared_family_overlaps": overlaps,
            "normalized_duplicate_count": len(exact), "cross_split_augmentation_parent_count": 0,
            "unique_authors": len(authors), "independently_double_reviewed_rows": reviewed,
            "iid_or_source_independence_established": False,
            "limits": "Declared lineage/source/template/scenario identifiers and exact text checked. Shared author, carrier phrases and unknown latent semantic siblings remain; no OOD or IID claim."}


def verify_manifest(manifest, train_bytes, dev_bytes):
    hashes = {"train": hashlib.sha256(train_bytes).hexdigest(), "development": hashlib.sha256(dev_bytes).hexdigest()}
    for row in manifest["artifacts"]:
        if row["split"] in hashes and row["sha256"] != hashes[row["split"]]:
            raise ValueError("Worker artifacts changed or not at a consistent handoff: " + row["split"])
    if {row["split"] for row in manifest["artifacts"]} != set(hashes):
        raise ValueError("Expected exactly worker train/development artifacts")
    return hashes
