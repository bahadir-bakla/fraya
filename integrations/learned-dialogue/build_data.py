"""Freeze label-free records and independent static oracle; never overwrite."""
import csv
import hashlib
import io
import json
from pathlib import Path

from authoring import PACKS, PUBLIC_FAMILIES

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "research/customer-benchmark"
PREFIX = DATA / "learned-dialogue-data"
REVISION = "57ec275d8078af65b7731c2a98be812d844a6d6b"
SOURCE_SHA = "d12d6e3bc4c3103966ae786dc435913c0c563dfa328f5a3646d0e62cfeeb474d"
LICENSE_SHA = "7e7170e3cebf88a9f60c7b8421418323c09304da1af4d5e90f4da1dc1c8a2661"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def freeze(path, data):
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Frozen artifact differs; create a new version: " + str(path))
        return
    with path.open("xb") as stream:
        stream.write(data)


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode()


def main():
    cache = ROOT / "integrations/customer-datasets/cache/banking77-test.data"
    source = cache.read_bytes()
    if sha(source) != SOURCE_SHA:
        raise ValueError("Pinned source changed")
    license_blob = (ROOT / "integrations/customer-datasets/cache/banking77-test-license.data").read_bytes()
    if sha(license_blob) != LICENSE_SHA or b"Attribution 4.0 International" not in license_blob:
        raise ValueError("Pinned official license notice changed")
    rows = list(csv.DictReader(io.StringIO(source.decode())))
    locators = {}
    for family, (row, label) in PUBLIC_FAMILIES.items():
        sample = rows[row - 2]
        if sample["category"] != label:
            raise ValueError("Source locator changed")
        locators[family] = {"csv_row_including_header": row, "source_intent": label,
                            "utterance_sha256": sha(sample["text"].encode())}
    records, oracle = [], {}
    for split, specs in PACKS.items():
        for index, (family, primary, secondary, completion, unresolved, text) in enumerate(specs):
            record_id = f"LD-v1-{split}-{index:03d}"
            origin = "polyai-banking77-pinned" if split == "train" and family in PUBLIC_FAMILIES else f"fictional-original-{split}-v1"
            record = {"id": record_id, "utterance": text, "split": split,
                      "semantic_template_group": family,
                      "scenario_family": family, "source_group": origin,
                      "augmentation_parent": None,
                      "provenance": {"fictional": True, "author": "Sol pre-fit authoring v1",
                                     "origin": origin, "raw_public_text_copied": False,
                                     "policy_oracle": False, "source_locator": locators.get(family) if origin.startswith("polyai") else None}}
            records.append(record)
            oracle[record_id] = {"primaryintent": primary, "secondaryintent": secondary,
                                 "completion": completion, "unresolvedcomponent": unresolved,
                                 "must_abstain": completion != "complete" or primary == "unknown",
                                 "rationale": "Independent declared fictional semantics; " + completion}
    record_bytes = b"".join((json.dumps(r, sort_keys=True) + "\n").encode() for r in records)
    oracle_bytes = encoded({"schema_version": 1, "independence": "Static pre-fit labels; not model predictions or policy labels; not human adjudicated", "labels": oracle})
    sources = {"banking77": {"origin": "PolyAI-LDN/task-specific-datasets", "revision": REVISION,
                              "source_url": f"https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/{REVISION}/banking_data/test.csv",
                              "source_sha256": SOURCE_SHA, "license": "CC-BY-4.0",
                              "license_url": f"https://github.com/PolyAI-LDN/task-specific-datasets/blob/{REVISION}/LICENSE",
                              "license_sha256": LICENSE_SHA,
                              "license_terms_url": "https://creativecommons.org/licenses/by/4.0/",
                              "attribution": "PolyAI; Casanueva, Temcinas, Gerz, Henderson, Vulic (2020), Efficient Intent Detection with Dual Sentence Encoders, https://arxiv.org/abs/2003.04807",
                              "verified_date": "2026-10-11", "use": "Four public samples as linguistic inspiration only, fictional rewriting; train only; no BANKING77 score"},
               "local": {"origin": "Separately authored fictional v1 packs", "use": "No real customer facts; same Sol author across packs is a limitation"}}
    manifest = {"version": 1, "record_sha256": sha(record_bytes), "oracle_sha256": sha(oracle_bytes),
                "sources_sha256": sha(encoded(sources)), "split_counts": {s: len(v) for s, v in PACKS.items()},
                "augmentation": "none", "immutable": "Content-addressed and write-once; existing mismatches fail closed",
                "group_dimensions": ["semantic_template_group", "source_group", "scenario_family"]}
    for suffix, blob in [("jsonl", record_bytes), ("oracle.json", oracle_bytes), ("sources.json", encoded(sources)), ("manifest.json", encoded(manifest))]:
        freeze(Path(str(PREFIX) + "." + suffix), blob)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
