"""Collect pinned public bytes, then process an auxiliary source-intent corpus.

Stdlib only. No model training, environment inspection, credentials, Git, GPU,
Freya, private corpus, or policy labels. Collection and processing are separate
CLI stages. Run --collect-only, then --process-only, then --verify.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import time
import unicodedata
import urllib.request


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = REPO / "research/customer-benchmark/day2-training-data"
CACHE = OUT / ".cache"
SOURCES = HERE / "day2_training_sources.json"
SEED = "banking77-source-intent-internal-v1"
SPLITS = ("train", "calibration", "eval")
MAX_DERIVED_BYTES = 16_000_000
REVISION = "57ec275d8078af65b7731c2a98be812d844a6d6b"
BASE = "https://raw.githubusercontent.com/PolyAI-LDN/task-specific-datasets/" + REVISION + "/"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def jsonl(rows) -> bytes:
    return b"".join((json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8") for r in rows)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def relative(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def specs():
    spec = json.loads(SOURCES.read_text(encoding="utf-8"))
    require(spec["revision"] == REVISION and spec["publisher_split"] == "train", "Unexpected source revision/split")
    require(len(spec["files"]) == 5, "Expected train, license, readme, taxonomy and exposed-test guard")
    require({f["role"] for f in spec["files"]} == {"train", "license", "publisher_readme", "taxonomy", "exposed_test_overlap_guard_only"}, "Unexpected roles")
    for item in spec["files"]:
        require(item["url"].startswith(BASE), "Only the pinned official publisher URLs are allowed")
        require(re.fullmatch(r"[\w.-]+", item["cache_name"]), "Invalid cache filename")
        require(re.fullmatch(r"[a-f0-9]{64}", item["sha256"]), "Invalid digest")
        require(0 < item["bytes"] <= item["max_bytes"] <= 2_000_000, "Invalid size limits")
    return spec


def checked(data: bytes, item):
    require(len(data) == item["bytes"] and len(data) <= item["max_bytes"], "Source byte count mismatch: " + item["role"])
    require(sha(data) == item["sha256"], "Source SHA256 mismatch: " + item["role"])
    return data


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Publisher download redirects are forbidden")


def source_bytes(item, offline=False, deadline=None):
    target = CACHE / item["cache_name"]
    if target.exists():
        require(target.stat().st_size <= item["max_bytes"], "Oversize cached source")
        return checked(target.read_bytes(), item)
    existing = item.get("existing_adapter_cache")
    if existing:
        old = REPO / existing
        if old.is_file():
            require(old.stat().st_size <= item["max_bytes"], "Oversize adapter cache")
            return checked(old.read_bytes(), item)
    require(not offline, "Offline source missing: " + item["cache_name"])
    require(deadline is not None and time.monotonic() < deadline, "Collection deadline exceeded")
    # Disable environment proxy discovery and reject redirects/auth/cookies.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(item["url"], headers={"User-Agent": "fraya-public-training-data/1"})
    started = time.monotonic()
    chunks, size = [], 0
    with opener.open(request, timeout=10) as response:
        require(response.geturl() == item["url"], "Unexpected final URL")
        while True:
            require(time.monotonic() < min(deadline, started + 45), "Download time bound exceeded")
            chunk = response.read(min(65536, item["max_bytes"] + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            require(size <= item["max_bytes"], "Download size bound exceeded")
    data = checked(b"".join(chunks), item)
    CACHE.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return data


def collect(offline=False):
    spec = specs()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / ".gitignore").write_bytes(b".cache/\n")
    deadline = time.monotonic() + 120
    entries = []
    for item in spec["files"]:
        data = source_bytes(item, offline=offline, deadline=deadline)
        entries.append({"role": item["role"], "url": item["url"], "bytes": len(data), "sha256": sha(data),
                        "use": "overlap_guard_only_never_train" if item["role"].startswith("exposed_test") else "public_source_input"})
    result = {"schema_version": 1, "stage": "collection", "credential_free_official_downloads": True,
              "raw_cache_ignored_by": relative(OUT / ".gitignore"), "sources": entries}
    (OUT / "collection-manifest.json").write_bytes(encoded(result))
    return result


# Conservative value scrubbing. Banking/security CONCEPTS remain in the input;
# actual identifier/secret-like values are replaced. All digits are removed.
SCRUBBERS = [
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("contact_url", re.compile(r"\b(?:https?://|www\.)\S+", re.I)),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?:[ -]?[A-Z0-9]){10,30}\b", re.I)),
    ("street_address", re.compile(r"\b\d{1,6}\s+(?:[A-Z][\w'-]*\s+){1,6}(?:street|st|road|rd|avenue|ave|lane|ln|drive|dr)\b", re.I)),
    ("declared_person", re.compile(r"\b(?:my name is|i am named|i'm named|i am called|mother'?s maiden name is|maiden name is)\s+[^.!?;\n]+", re.I)),
    ("declared_contact", re.compile(r"\b(?:my address is|i live at|my email is|my phone number is|my telephone number is|my date of birth is|my birthday is|my username is|my user name is)\s+[^.!?;\n]+", re.I)),
    ("secret_value", re.compile(r"\b(?:my\s+)?(?:password|passcode|security answer|secret answer|cvv|cvc|pin(?: number| code)?)\s*(?:is|was|:|=)\s+(?!(?:not|wrong|incorrect|invalid|blocked|locked|forgotten|missing|expired|unknown|working|needed|unavailable|the|a|an)\b)[^.!?;\n]+", re.I)),
    ("long_identifier", re.compile(r"\b(?=[A-Z0-9_-]{12,}\b)(?=[A-Z0-9_-]*\d)[A-Z0-9_-]+\b", re.I)),
    ("spoken_contact_number", re.compile(r"\b(?:(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)[ ,.-]+){3,}(?:zero|oh|one|two|three|four|five|six|seven|eight|nine)\b", re.I)),
    ("numeric_value", re.compile(r"\d+(?:[ .,/:'-]\d+)*")),
]
NUMBER_WORDS = re.compile(r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million)\b", re.I)
DATES = re.compile(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)\b", re.I)
CURRENCIES = re.compile(r"\b(?:usd|eur|gbp|dollars?|euros?|pounds?|sterling)\b", re.I)


def scrub(text):
    require(isinstance(text, str) and 0 < len(text.strip()) <= 20000, "Invalid input text")
    result = unicodedata.normalize("NFKC", text)
    counts = Counter()
    for name, pattern in SCRUBBERS:
        result, count = pattern.subn("[REDACTED_" + name.upper() + "]", result)
        if count:
            counts[name] = count
    result = " ".join(result.split())
    require(bool(result), "Empty scrubbed text")
    require(not any(ch.isdigit() for ch in result), "Numeric value escaped scrubber")
    require(not SCRUBBERS[0][1].search(result) and not SCRUBBERS[1][1].search(result), "Contact span escaped scrubber")
    return result, dict(sorted(counts.items()))


def exact_key(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def template_key(text):
    value = exact_key(text).replace("\u2019", "'")
    for short, expanded in (("can't", "cannot"), ("won't", "will not"), ("i'm", "i am"), ("it's", "it is"), ("i've", "i have")):
        value = value.replace(short, expanded)
    value = re.sub(r"\[redacted_[a-z_]+\]", " slotvalue ", value)
    value = NUMBER_WORDS.sub(" slotvalue ", value)
    value = DATES.sub(" slotdate ", value)
    value = CURRENCIES.sub(" slotcurrency ", value)
    value = re.sub(r"[\u00a3\u20ac$]", " slotcurrency ", value)
    return " ".join(re.sub(r"[^\w\s]", " ", value).split())


def csv_rows(data):
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig"), newline=""))
    require(reader.fieldnames == ["text", "category"], "Unexpected publisher CSV schema")
    rows = list(reader)
    require(rows and len(rows) <= 20000, "Unexpected row count")
    for row in rows:
        require(set(row) == {"text", "category"} and all(isinstance(v, str) and v.strip() for v in row.values()), "Missing/invalid source text or label")
    return rows


def prepare(raw, exposed_test, labels):
    require(len(labels) == len(set(labels)) and all(isinstance(x, str) and x for x in labels), "Invalid taxonomy")
    label_ids = {label: i for i, label in enumerate(labels)}
    require(all(r["category"] in label_ids for r in raw + exposed_test), "Unknown source label")
    test_exact, test_templates = set(), set()
    for row in exposed_test:
        cleaned, _ = scrub(row["text"])
        test_exact.add(exact_key(cleaned))
        test_templates.add(template_key(cleaned))
    groups = defaultdict(list)
    redaction_rows, redaction_totals = [], Counter()
    for index, row in enumerate(raw):
        cleaned, redactions = scrub(row["text"])
        root = sha(template_key(cleaned).encode("utf-8"))
        member = {"index": index, "source_label": row["category"], "text": cleaned,
                  "source_text_sha256": sha(row["text"].encode("utf-8")), "redactions": redactions}
        groups[root].append(member)
        redaction_totals.update(redactions)
        if redactions:
            redaction_rows.append({"source_record_index": index, "source_text_sha256": member["source_text_sha256"], "redactions": redactions})
    ready, audit = [], []
    removed, duplicate_rows = Counter(), 0
    for root, members in sorted(groups.items()):
        ids = sorted(m["index"] for m in members)
        group_labels = sorted({m["source_label"] for m in members})
        exact_overlap = any(exact_key(m["text"]) in test_exact for m in members)
        template_overlap = any(template_key(m["text"]) in test_templates for m in members)
        reason = "conflicting_source_labels" if len(group_labels) > 1 else "exposed_publisher_test_overlap" if exact_overlap or template_overlap else None
        if reason:
            removed[reason] += len(members)
        elif len(members) > 1:
            duplicate_rows += len(members) - 1
        if reason or len(members) > 1:
            audit.append({"group_id": "banking77:" + root, "source_record_indices": ids,
                          "source_labels": group_labels, "disposition": reason or "deduplicated_to_one_representative",
                          "exposed_test_exact_match": exact_overlap, "exposed_test_template_match": template_overlap,
                          "distinct_exact_keys": len({exact_key(m["text"]) for m in members})})
        if reason:
            continue
        representative = min(members, key=lambda m: (sum(m["redactions"].values()), m["index"]))
        ready.append({"record_id": "banking77-train:" + str(representative["index"]).zfill(5),
                      "source_id": "banking77-publisher-train", "publisher_split": "train",
                      "source_record_indices": ids, "source_text_sha256": representative["source_text_sha256"],
                      "text": representative["text"], "source_label": representative["source_label"],
                      "source_label_id": label_ids[representative["source_label"]],
                      "group_id": "banking77:" + root, "variant_root_id": "banking77:" + root,
                      "conversation_root_ids": ["banking77-train-row:" + str(i) for i in ids],
                      "redactions": representative["redactions"], "task": "source_intent_auxiliary",
                      "bank_policy_target": None, "ledger_target": None})
    summary = {"publisher_train_rows": len(raw), "publisher_exposed_test_rows_guard_only": len(exposed_test),
               "missing_label_rows": 0, "unknown_label_rows": 0, "template_groups_before_filter": len(groups),
               "quarantined_source_rows_by_reason": dict(sorted(removed.items())),
               "quarantined_groups": sum(a["disposition"] != "deduplicated_to_one_representative" for a in audit),
               "duplicate_source_rows_collapsed": duplicate_rows, "retained_examples": len(ready),
               "retained_original_row_lineage_count": sum(len(r["source_record_indices"]) for r in ready),
               "raw_rows_with_redactions": len(redaction_rows), "raw_redaction_span_counts": dict(sorted(redaction_totals.items()))}
    require(len(raw) == sum(removed.values()) + duplicate_rows + len(ready), "Row-accounting invariant failed")
    return ready, audit, redaction_rows, summary, (test_exact, test_templates)


def assign_splits(ready, labels):
    buckets = defaultdict(list)
    for row in ready:
        buckets[row["source_label"]].append(row)
    result = {split: [] for split in SPLITS}
    for label in labels:
        ordered = sorted(buckets[label], key=lambda r: sha((SEED + ":" + r["group_id"]).encode()))
        require(len(ordered) >= 3, "Label cannot have disjoint train/calibration/eval groups: " + label)
        held = max(1, round(len(ordered) * 0.1))
        partitions = {"train": ordered[:-2 * held], "calibration": ordered[-2 * held:-held], "eval": ordered[-held:]}
        for split, rows in partitions.items():
            for row in rows:
                result[split].append(dict(row, split=split))
    for split in SPLITS:
        result[split].sort(key=lambda r: r["group_id"])
    return result


def verify_invariants(partitions, labels, guards):
    dimensions = {kind: {} for kind in ("group_id", "source_record_index", "conversation_root_id", "exact", "template")}
    residual = Counter()
    for split, rows in partitions.items():
        require(rows and {r["source_label"] for r in rows} == set(labels), "Missing split labels")
        seen_ids = set()
        for row in rows:
            require(row["record_id"] not in seen_ids, "Duplicate record ID")
            seen_ids.add(row["record_id"])
            require(row["source_label_id"] == labels.index(row["source_label"]), "Taxonomy ID mismatch")
            require(row["publisher_split"] == "train" and row["split"] == split and row["task"] == "source_intent_auxiliary", "Wrong source/task/split")
            require(row["bank_policy_target"] is None and row["ledger_target"] is None, "Invented bank targets")
            require(row["group_id"] == row["variant_root_id"] == "banking77:" + sha(template_key(row["text"]).encode()), "Invalid variant root")
            require(exact_key(row["text"]) not in guards[0] and template_key(row["text"]) not in guards[1], "Exposed-test contamination")
            require(scrub(row["text"])[0] == row["text"], "Scrubbing is not idempotent")
            residual["numeric_value"] += any(ch.isdigit() for ch in row["text"])
            for name, pattern in SCRUBBERS[:4]:
                residual[name] += bool(pattern.search(row["text"]))
            keys = {"group_id": [row["group_id"]], "source_record_index": row["source_record_indices"],
                    "conversation_root_id": row["conversation_root_ids"], "exact": [exact_key(row["text"])],
                    "template": [template_key(row["text"])]}
            for dimension, values in keys.items():
                for value in values:
                    require(value not in dimensions[dimension], "Duplicate or overlapping " + dimension)
                    dimensions[dimension][value] = split
    require(not any(residual.values()), "Residual machine-detectable sensitive spans")
    return {"status": "passed", "missing_labels_each_split": 0, "unknown_labels": 0,
            "duplicate_exact_keys": 0, "duplicate_delexicalized_template_keys": 0,
            "cross_split_group_overlap": 0, "cross_split_conversation_root_overlap": 0,
            "cross_split_original_record_overlap": 0, "exposed_publisher_test_exact_overlap": 0,
            "exposed_publisher_test_delexicalized_overlap": 0, "invented_bank_policy_targets": 0,
            "residual_detectable_sensitive_spans": dict(sorted(residual.items())),
            "limits": "Regex scrubbing is heuristic; it does not certify absence of all names, indirect identifiers, paraphrase leakage, or unannotated shared conversations."}


def adaptation_plan():
    return {
        "schema_version": 1,
        "status": "auxiliary_corpus_ready_bank_adaptation_not_approved",
        "independent_bank_domain_review": {"status": "pending_parent_or_domain_reviewer", "reviewer": None, "approved_mapping": None},
        "local_scope_review": {"status": "completed", "method": "explicit label/target/split invariant review; not independent bank-domain approval",
                               "checks": ["Original 77 support-intent labels preserved", "No policy/action/ledger targets generated", "No transfer-to-debt-payment mapping", "English support queries are not Turkish collection dialogue", "Internal held-out data is not blind policy OOD"]},
        "ready_training_task": {"objective": "Supervised 77-class source-intent classification using only train.jsonl",
                                "target": "source_label_id in taxonomy.json publisher order", "input": "text",
                                "calibration": "Use calibration.jsonl only to choose source-intent confidence thresholds; do not optimize weights on it",
                                "evaluation": "Freeze model/settings, then evaluate eval.jsonl with macro F1, per-intent recall and confusion matrix",
                                "claim_limit": "Measures internal BANKING77 source-intent recognition; provides no evidence of safe bank actions or ledger correctness"},
        "bank_adaptation_review_steps": [
            "A bank-domain reviewer checks corpus applicability, redaction samples, label ambiguity and language mismatch before any bank-domain use.",
            "If an auxiliary classifier is used, its output is a linguistic hypothesis. Keep bank policy, identity state, tool permission and ledger facts in the independently reviewed bank workflow.",
            "Create bank action labels only from separately reviewed fixture facts, conversational state and observed tool results. Support taxonomy alone supplies none of these.",
            "Review ambiguous transfer queries individually. Domestic/international transfer, pending transfer and failed transfer support intents imply neither debt nor willingness nor a payment promise.",
            "Any translation, paraphrase, synthetic bank adaptation or multi-turn variant must retain this corpus group_id and stay in its assigned split. Do not mix translated variants across splits.",
            "Reserve and lock a genuinely unseen policy OOD set outside this packet before model/threshold selection. Another owner supplies it; no OOD gold or blind examples are invented here.",
            "Parent records reviewer identity, exact artifact hashes and approved use, then separately authorizes the actual training run."
        ],
        "blind_policy_ood": {"status": "reserved_separately_uncollected_here", "examples": 0, "owner": "parent / independent policy evaluation owner", "must_not_use": ["publisher test already exposed", "this packet's internal eval", "known public policy fixtures as blind evidence"]},
        "prohibited_inferences": ["source intent => bank permission", "source intent => ledger truth", "transfer question => debt payment proposal", "publisher test => fresh evaluation"],
        "review_result": "No bank adaptation gold exists in this packet. Independent review remains required for bank adaptation."
    }


def self_test():
    vectors = ["Contact me at test.person@example.com", "Call +44 1234 567890", "Card 4111 1111 1111 1111", "IBAN GB82 WEST 1234 5698 7654 32", "My password is huntertwo.", "My name is Example Person.", "I live at 42 Example Street.", "My PIN is four five six seven."]
    for value in vectors:
        cleaned, changes = scrub(value)
        require(bool(changes) and "example.com" not in cleaned and "huntertwo" not in cleaned and "Example Person" not in cleaned, "Scrubber regression")
        require(scrub(cleaned)[0] == cleaned, "Scrubber idempotence regression")
    require("not working" in scrub("My PIN is not working")[0], "Security concept incorrectly removed")
    require(template_key(scrub("I paid 20 dollars.")[0]) == template_key(scrub("I paid 30 pounds!")[0]), "Value variant not grouped")
    fixture = [{"text": "Unique phrase alpha", "category": "a"}, {"text": "Unique phrase alpha!", "category": "a"},
               {"text": "Collision phrase", "category": "a"}, {"text": "Collision phrase!", "category": "b"},
               {"text": "Public overlap", "category": "a"}]
    ready, audit, _, summary, _ = prepare(fixture, [{"text": "Public overlap!", "category": "a"}], ["a", "b"])
    require(len(ready) == 1 and ready[0]["source_record_indices"] == [0, 1], "Variant dedup regression")
    require(summary["quarantined_source_rows_by_reason"] == {"conflicting_source_labels": 2, "exposed_publisher_test_overlap": 1}, "Conflict/contamination quarantine regression")
    try:
        checked(b"wrong", {"bytes": 5, "max_bytes": 5, "sha256": "0" * 64, "role": "test"})
    except ValueError:
        pass
    else:
        raise ValueError("Hash mismatch not rejected")
    return {"status": "passed", "redaction_vectors": len(vectors), "checks": ["scrubber idempotence", "security concept preservation", "delexicalized variants", "conflicting-label quarantine", "exposed-test quarantine", "byte/hash rejection"]}


def compile_packet():
    spec = specs()
    data = {item["role"]: source_bytes(item, offline=True) for item in spec["files"]}
    labels = json.loads(data["taxonomy"].decode("utf-8"))
    raw = csv_rows(data["train"])
    test = csv_rows(data["exposed_test_overlap_guard_only"])
    require(len(raw) == spec["expected_rows"] and len(labels) == spec["expected_labels"] and len(test) == 3080, "Unexpected actual publisher counts")
    require(b"Attribution 4.0 International" in data["license"], "Unexpected license notice")
    ready, audit, redaction_audit, counts, guards = prepare(raw, test, labels)
    partitions = assign_splits(ready, labels)
    invariants = verify_invariants(partitions, labels, guards)
    invariants["self_tests"] = self_test()
    original_counts = Counter(r["category"] for r in raw)
    taxonomy = {"schema_version": 1, "label_namespace": "banking77_publisher_support_intent", "label_id_order": "publisher_categories_json_order",
                "not_bank_policy_or_ledger_gold": True,
                "labels": [{"id": i, "source_label": label, "publisher_train_rows": original_counts[label],
                            "retained_by_split": {split: sum(r["source_label"] == label for r in partitions[split]) for split in SPLITS}}
                           for i, label in enumerate(labels)]}
    notice = ("BANKING77 public TRAIN-derived auxiliary source-intent corpus\n\n" + spec["attribution"] + "\n" + spec["citation_url"] + "\n"
              "Original material: " + BASE + "banking_data/train.csv\nRevision: " + REVISION + "\n"
              "License: Creative Commons Attribution 4.0 International (CC-BY-4.0)\n" + spec["license_terms_url"] + "\n"
              "Full unmodified publisher license and its warranty disclaimer: BANKING77-LICENSE.txt\n"
              "Publisher README and requested citation retained in BANKING77-PUBLISHER-README.md.\n"
              "Modified: Unicode/whitespace normalization, heuristic PII/contact/identifier/secret value redaction (including all digits), exact/delexicalized template deduplication, conflicting-label and exposed-test overlap quarantine, deterministic grouped internal splits, provenance metadata.\n"
              "Support labels remain publisher labels. No bank permission, policy, payment proposal, ledger truth or endorsement is supplied.\n")
    readme = """This packet contains actual BANKING77 publisher TRAIN utterances and their original support-intent labels. It is ready for auxiliary 77-class source-intent training. It contains no bank policy or action gold.

Load UTF-8 train.jsonl; use `text` as input and `source_label_id` as the supervised target. taxonomy.json retains the publisher label order. Use calibration.jsonl for source-intent confidence/threshold selection only. Freeze model/settings before eval.jsonl. Both held-out splits derive from publisher TRAIN and are internal evaluation, not fresh public test or blind policy OOD.

The publisher TEST already exists in the repository and has inspired other data. It is read only as a contamination guard. Any detected train root matching an exposed-test exact/delexicalized key is quarantined before splitting; test utterances and labels never enter this corpus.

Group before split: normalized/delexicalized template roots collect all literal case/punctuation/value variants. Conflicting-label roots are quarantined. One representative per retained root is emitted; all original row aliases and conversation_root_ids stay with it. BANKING77 provides single utterances, not conversation IDs. Each original row is its own unknown conversation root; this does not assert detection of actual shared conversations or all semantic paraphrases. New descendants/translations must inherit group_id and split.

All digit spans and detected contacts, explicit names/addresses, identifier and secret values are redacted. Exact pattern definitions are in the processor. Redaction auditing publishes only indices, hashes and counts; raw bytes stay under ignored .cache/. Regex scrubbing is heuristic and does not guarantee absence of all indirect identifiers or names.

Independent bank-domain approval of bank-adaptation-plan.json is pending. The plan prohibits transfer-intent-to-debt-payment mappings, supplies no invented policy labels, and reserves blind policy OOD separately with the parent. No model training has been run by this processor.

Reproduce from repository root, with Python 3.11+ and no third-party packages:
  python integrations/customer-datasets/day2_training_data.py --collect-only
  python integrations/customer-datasets/day2_training_data.py --process-only
  python integrations/customer-datasets/day2_training_data.py --verify
Cached offline collection: append --offline to --collect-only. Processing and verification perform no network calls. Run --self-test for focused scrub/group/hash regression checks. --verify recomputes every derived artifact from pinned raw bytes and requires byte-identical files and manifest.

The collector uses official immutable publisher raw URLs, byte/SHA256 pins, no redirects or environment proxy discovery, 10-second socket timeout, 45-second per-file and 120-second total download checks, and at most 2 MB per source. Derived corpus plus notices/audits is capped at 16 MB. Read manifest.json and validation.json for exact accounting and checks. Review NOTICE.txt and the retained publisher license/README before sharing.
"""
    artifacts = {split + ".jsonl": jsonl(partitions[split]) for split in SPLITS}
    artifacts.update({"taxonomy.json": encoded(taxonomy), "dedup-quarantine-audit.jsonl": jsonl(audit),
                      "redaction-audit.jsonl": jsonl(redaction_audit), "validation.json": encoded(invariants),
                      "bank-adaptation-plan.json": encoded(adaptation_plan()), "NOTICE.txt": notice.encode("utf-8"),
                      "README.txt": readme.encode("utf-8"), "BANKING77-LICENSE.txt": data["license"],
                      "BANKING77-PUBLISHER-README.md": data["publisher_readme"], ".gitignore": b".cache/\n"})
    require(sum(map(len, artifacts.values())) <= MAX_DERIVED_BYTES, "Derived corpus size bound exceeded")
    counts["split_examples"] = {split: len(partitions[split]) for split in SPLITS}
    counts["labels_each_split"] = {split: len({r["source_label"] for r in partitions[split]}) for split in SPLITS}
    counts["split_groups"] = counts["split_examples"].copy()
    manifest = {"schema_version": 1, "status": "ready_for_auxiliary_source_intent_training", "model_training_executed": False,
                "task": "77-class BANKING77 source-intent auxiliary supervised training", "target": "source_label_id", "input": "text",
                "source": {k: spec[k] for k in ("source_id", "repo", "revision", "license", "license_terms_url", "attribution", "citation_url", "publisher_split")},
                "source_files": [{k: f[k] for k in ("role", "url", "sha256", "bytes")} for f in spec["files"]],
                "processor": {"path": relative(Path(__file__).resolve()), "sha256": sha(Path(__file__).read_bytes()), "hash_method": "exact_bytes"},
                "source_config": {"path": relative(SOURCES), "sha256": sha(SOURCES.read_bytes())},
                "counts": counts, "label_namespace": taxonomy["label_namespace"],
                "split_method": {"seed": SEED, "method": "stratified per-label hash ordering of delexicalized roots before 80/10/10 allocation", "heldout_per_label": "max(1, round(retained_group_count * 0.1))", "dedup_before_split": True},
                "exposure": {"publisher_test_already_exposed": True, "publisher_test_usage": "overlap_guard_only", "internal_eval_from_publisher_train": True, "blind_policy_ood": "reserved_separately_uncollected_here", "blind_policy_ood_examples_in_packet": 0},
                "bank_adaptation": {"policy_or_ledger_gold_rows": 0, "independent_review_status": "pending_parent_or_domain_reviewer", "plan": "bank-adaptation-plan.json"},
                "invariants": invariants, "derived_bytes": sum(map(len, artifacts.values())),
                "outputs": {name: {"path": relative(OUT / name), "sha256": sha(value), "bytes": len(value), "rows": len(partitions[name[:-6]]) if name.endswith(".jsonl") and name[:-6] in partitions else None} for name, value in sorted(artifacts.items())}}
    return artifacts, manifest


def report(manifest, verified):
    result = {"status": manifest["status"], "collection_stage": "complete_verified_pinned_public_bytes",
              "processing_stage": "complete", "local_recompute_verification": "passed" if verified else "not_run",
              "manifest_path": relative(OUT / "manifest.json"), "manifest_sha256": sha(encoded(manifest)),
              "counts": manifest["counts"], "ready_files": {split: manifest["outputs"][split + ".jsonl"] for split in SPLITS},
              "source_train_sha256": manifest["source_files"][0]["sha256"], "source_license_sha256": manifest["source_files"][1]["sha256"],
              "taxonomy": manifest["outputs"]["taxonomy.json"], "processor": manifest["processor"],
              "invariants": manifest["invariants"], "training_executed": False,
              "training_handoff": "Parent may authorize real auxiliary source-intent training on train.jsonl. Bank adaptation requires separate independent domain review; no bank gold was invented.",
              "optional_second_source": "not_collected; complete mandatory TRAIN corpus prioritized", "scope": "Only new day2 data processor/config, day2-training-data outputs/cache and day2-data-collection reports"}
    analysis = REPO / "analysis"
    analysis.mkdir(exist_ok=True)
    (analysis / "day2-data-collection.json").write_bytes(encoded(result))
    text = ["Actual public TRAIN collection and processing complete; auxiliary source-intent training data ready.",
            "Publisher TRAIN: " + str(manifest["counts"]["publisher_train_rows"]) + " rows, 77 original labels.",
            "Internal split counts: " + json.dumps(manifest["counts"]["split_examples"], sort_keys=True),
            "Manifest: " + result["manifest_path"] + " sha256=" + result["manifest_sha256"],
            "Recomputed byte-identical artifact verification: " + result["local_recompute_verification"]]
    for split in SPLITS:
        entry = result["ready_files"][split]
        text.append(split + ": " + entry["path"] + " sha256=" + entry["sha256"])
    text.extend(["Exact/delexicalized/group/conversation/original-row cross-split overlap: 0; missing labels: 0; exposed-test overlap: 0.",
                 "The publisher TEST is already exposed; it is excluded from training and used only as a contamination guard.",
                 "Internal eval is publisher-TRAIN-derived; actual blind policy OOD is reserved separately and uncollected here.",
                 "No training executed; no bank permission/ledger gold; no transfer-to-debt-payment mapping.",
                 "Bank adaptation plan has local scope review; independent bank-domain review is pending.",
                 "Regex PII/secret scrubbing limitations, complete attribution/license and exact row accounting are retained in the packet."])
    (analysis / "day2-data-collection.txt").write_bytes(("\n".join(text) + "\n").encode("utf-8"))
    return result


def process():
    require((OUT / "collection-manifest.json").is_file(), "Collect pinned sources before processing")
    collection = json.loads((OUT / "collection-manifest.json").read_text(encoding="utf-8"))
    require(collection["stage"] == "collection", "Invalid collection manifest")
    artifacts, manifest = compile_packet()
    for name, value in artifacts.items():
        (OUT / name).write_bytes(value)
    (OUT / "manifest.json").write_bytes(encoded(manifest))
    return verify()


def verify():
    artifacts, expected = compile_packet()
    actual = json.loads((OUT / "manifest.json").read_text(encoding="utf-8"))
    require(actual == expected and (OUT / "manifest.json").read_bytes() == encoded(expected), "Manifest differs from deterministic processing")
    for name, value in artifacts.items():
        require((OUT / name).read_bytes() == value, "Artifact differs from deterministic processing: " + name)
    return report(expected, verified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--collect-only", action="store_true")
    modes.add_argument("--process-only", action="store_true")
    modes.add_argument("--verify", action="store_true")
    modes.add_argument("--self-test", action="store_true")
    parser.add_argument("--offline", action="store_true", help="No network during collection; processing/verification are always offline")
    args = parser.parse_args()
    if args.self_test:
        result = self_test()
    elif args.verify:
        result = verify()
    elif args.process_only:
        result = process()
    else:
        result = collect(offline=args.offline)
        if not args.collect_only:
            result = process()
    print(json.dumps({k: result[k] for k in ("status", "manifest_path", "manifest_sha256", "counts") if k in result}, sort_keys=True))


if __name__ == "__main__":
    main()
