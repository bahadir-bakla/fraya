"""Pinned public-source supervision. Targets never enter runtime inputs.

No optimizer, network, platform API, bank-policy labels or deployment admission.
Unknown NLU++ elements remain masked rather than becoming negative examples.
"""
import hashlib
import json
from collections import Counter
from pathlib import Path

VERSION = "day2.multisource.data.v1"
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/customer-benchmark/day2-training-data/v2"
MANIFEST_SHA = "8fbbd1ec7e3cefda0cbcef616bcf61ba7886d9234fee9b9ed5e23513c7cc2ba0"
SPLIT_SHA = {
    "train": "03707b592734838d9ad80fadaab3d87f42a5ed72c170580b86fa9cb58876e60f",
    "calibration": "e2e708b9254a53712c852b26c49b2444be50d72b4f130e35599bb174df94d73d",
    "eval": "f8bbb9dfdf89752bc71b1c5a99ea0042892e3e1dd3175a9e3b3a7dedd8bc8923",
}
HEADS = ("banking77_intent", "nlupp_intents", "nlupp_slot_presence", "taskmaster_next_utterance")
SOURCES = {
    "banking77-publisher-train": ("banking77_intent",),
    "polyai-nlupp": ("nlupp_intents", "nlupp_slot_presence"),
    "google-taskmaster3-shard00": ("taskmaster_next_utterance",),
}


class InputRejected(ValueError):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pinned_json(path, expected):
    if sha(path) != expected:
        raise InputRejected("Pinned bytes changed: " + str(path))
    return json.loads(Path(path).read_text(encoding="utf8"))


def taxonomy():
    manifest = pinned_json(DATA / "manifest.json", MANIFEST_SHA)
    outputs = manifest["outputs"]
    return {name: pinned_json(DATA / name, outputs[name]["sha256"])
            for name in ("banking77-taxonomy.json", "nlupp-taxonomy.json")}


def inference_input(row):
    """An allowlist, not a row serializer; no metadata or targets survive."""
    if type(row) is not dict or type(row.get("text")) is not str:
        raise InputRejected("Text must be a string")
    context = row.get("context")
    if context is None:
        return {"text": row["text"], "context": []}
    if type(context) is not list or not 1 <= len(context) <= 6:
        raise InputRejected("Context must contain one to six source turns")
    clean = []
    for turn in context:
        if (type(turn) is not dict or type(turn.get("speaker")) is not str
                or turn["speaker"] not in {"user", "assistant"} or type(turn.get("text")) is not str):
            raise InputRejected("Malformed context role/text")
        clean.append({"speaker": turn["speaker"], "text": turn["text"]})
    if clean[-1]["text"] != row["text"]:
        raise InputRejected("Latest context source differs from text")
    return {"text": row["text"], "context": clean}


def validate_row(row, split, taxa):
    if type(row) is not dict or row.get("split") != split:
        raise InputRejected("Source split mismatch")
    for key in ("record_id", "group_id", "source_id"):
        if type(row.get(key)) is not str or not row[key]:
            raise InputRejected("Missing source identity")
    source = row["source_id"]
    if source not in SOURCES:
        raise InputRejected("Unknown source")
    masks = row.get("head_mask")
    if type(masks) is not dict or set(masks) != set(HEADS) | {"bank_policy", "ledger"}:
        raise InputRejected("Head mask schema")
    if any(type(v) is not bool for v in masks.values()):
        raise InputRejected("Head masks require actual booleans")
    if masks["bank_policy"] or masks["ledger"]:
        raise InputRejected("Authority supervision forbidden")
    if {h for h in HEADS if masks[h]} != set(SOURCES[source]):
        raise InputRejected("Cross-source head coercion")
    targets = row.get("targets")
    if type(targets) is not dict or set(targets) != set(SOURCES[source]):
        raise InputRejected("Target/head mismatch")
    if row.get("bank_policy_target") is not None or row.get("ledger_target") is not None:
        raise InputRejected("Bank targets forbidden")
    if source == "banking77-publisher-train":
        y = targets["banking77_intent"]
        if type(y) is not int or not 0 <= y < 77 or row.get("publisher_split") != "train":
            raise InputRejected("Publisher TRAIN intent must be a bounded integer")
    if source == "polyai-nlupp":
        domain = row.get("source_domain")
        if domain not in {"banking", "hotels"} or row.get("slot_value_target_mask") is not False:
            raise InputRejected("Domain or slot-value mask")
        element_masks = row.get("target_element_masks")
        if type(element_masks) is not dict or set(element_masks) != {"nlupp_intents", "nlupp_slot_presence"}:
            raise InputRejected("Missing element masks")
        for head, field in (("nlupp_intents", "intents"), ("nlupp_slot_presence", "slots")):
            y, m, labels = targets[head], element_masks[head], taxa["nlupp-taxonomy.json"][field]
            if type(y) is not list or type(m) is not list or len(y) != len(labels) or len(m) != len(labels):
                raise InputRejected("Multilabel shape")
            for index, (value, known, label) in enumerate(zip(y, m, labels)):
                if type(value) is not int or value not in (0, 1) or type(known) is not bool:
                    raise InputRejected("Binary values and boolean masks required")
                expected = "general" in label["domain"] or domain in label["domain"]
                if known != expected or value and not known or label["id"] != index:
                    raise InputRejected("Unknown domain elements cannot be negatives/positives")
    if source == "google-taskmaster3-shard00":
        if type(targets["taskmaster_next_utterance"]) is not str or not targets["taskmaster_next_utterance"].strip():
            raise InputRejected("Observed response text required")
        if row.get("api_or_bank_target_mask") is not False:
            raise InputRejected("Taskmaster API target mask")
        context = inference_input(row)["context"]
        graph = row.get("graph")
        expected = [[i, i + 1, "observed_next_turn"] for i in range(len(context) - 1)]
        if type(graph) is not dict or graph.get("edges") != expected:
            raise InputRejected("Published graph must match observed source turn order")
    roots = row.get("conversation_root_ids")
    if type(roots) is not list or not roots or any(type(v) is not str or not v for v in roots):
        raise InputRejected("Missing lineage aliases")
    inference_input(row)
    return row


def load_split(split):
    if split not in SPLIT_SHA:
        raise InputRejected("Unapproved partition")
    path = DATA / (split + ".jsonl")
    if sha(path) != SPLIT_SHA[split]:
        raise InputRejected("Partition hash mismatch")
    taxa = taxonomy()
    with path.open(encoding="utf8") as source:
        return [validate_row(json.loads(line), split, taxa) for line in source if line.strip()]


def audit_partitions(partitions):
    """Local identity/template closure check; never an IID ancestry certificate."""
    owners, records, summary = {}, set(), {}
    for split, rows in partitions.items():
        for row in rows:
            if row["record_id"] in records:
                raise InputRejected("Duplicate record identity")
            records.add(row["record_id"])
            keys = ["group:" + row["group_id"]] + ["conversation:" + v for v in row["conversation_root_ids"]]
            for key in keys:
                if key in owners and owners[key] != split:
                    raise InputRejected("Lineage crosses partitions")
                owners[key] = split
        sources = {}
        for source in SOURCES:
            members = [r for r in rows if r["source_id"] == source]
            sources[source] = {"rows": len(members), "groups": len({r["group_id"] for r in members})}
        summary[split] = {"rows": len(rows), "sources": sources,
                          "known_head_rows": dict(Counter(h for r in rows for h in HEADS if r["head_mask"][h]))}
    return {"partitions": summary, "local_group_or_conversation_overlap": 0,
            "global_semantic_ancestry": "unresolved", "independent_IID_groups": False}
