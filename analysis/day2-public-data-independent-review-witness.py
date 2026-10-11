"""Independent read-only BANKING77 row audit. Stdlib; no network, models or fits.

Run from the repository root: python -I -B analysis/day2-public-data-independent-review-witness.py
Only creates the two sibling review reports; refuses to replace existing reports.
Repeat with --check-only to rerun the row audit without creating any files.
Uses the frozen scrub implementation locally, but independently reconstructs keys,
lineage accounting, publisher labels, exclusions and deterministic split allocation.
Does not call compile_packet, verify, process, collect or the reproduction launcher.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import ast
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import types
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research/customer-benchmark/day2-training-data"
BASE = Path(__file__).with_name("day2-public-data-independent-review")
OUTPUTS = [BASE.with_suffix(".json"), BASE.with_suffix(".txt")]
CHECK_ONLY = sys.argv[1:] == ["--check-only"]
assert not sys.argv[1:] or CHECK_ONLY, "Only --check-only is supported"
assert CHECK_ONLY or not any(p.exists() for p in OUTPUTS), "Review outputs already exist; use --check-only to rerun without writes"


def digest(b):
    return hashlib.sha256(b).hexdigest()


def load_json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def rows(p):
    return [json.loads(s) for s in p.read_text(encoding="utf-8").splitlines()]


def exact(t):
    return " ".join(unicodedata.normalize("NFKC", t).casefold().split())


def template(t):
    t = exact(t).replace("\u2019", "'")
    for a, b in [("can't", "cannot"), ("won't", "will not"), ("i'm", "i am"), ("it's", "it is"), ("i've", "i have")]:
        t = t.replace(a, b)
    t = re.sub(r"\[redacted_[a-z_]+\]", " slotvalue ", t)
    t = re.sub(r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million)\b", " slotvalue ", t)
    t = re.sub(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december)\b", " slotdate ", t)
    t = re.sub(r"\b(?:usd|eur|gbp|dollars?|euros?|pounds?|sterling)\b", " slotcurrency ", t)
    t = re.sub(r"[\u00a3\u20ac$]", " slotcurrency ", t)
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


manifest_bytes = (PACKET / "manifest.json").read_bytes()
manifest = json.loads(manifest_bytes)
spec = load_json(PACKET / "sources-v1.json")
source_checks, data = {}, {}
for item in spec["files"]:
    path = PACKET / ".cache" / item["cache_name"]
    if not path.exists():
        path = ROOT / item["existing_adapter_cache"]
    b = path.read_bytes()
    source_checks[item["role"]] = {"path": path.relative_to(ROOT).as_posix(), "bytes": len(b), "sha256": digest(b), "pin_match": len(b) == item["bytes"] and digest(b) == item["sha256"]}
    assert source_checks[item["role"]]["pin_match"], item["role"]
    data[item["role"]] = b
raw = list(csv.DictReader(io.StringIO(data["train"].decode("utf-8-sig"), newline="")))
assert len(raw) == 10003 and all(set(r) == {"text", "category"} for r in raw)
labels = json.loads(data["taxonomy"])
assert len(labels) == len(set(labels)) == 77
# TEST is used solely for text/key overlap guards: no test labels enter checks,
# examples, supervised targets, calibration, evaluation, fitting or metrics.
test_text = [r["text"] for r in csv.DictReader(io.StringIO(data["exposed_test_overlap_guard_only"].decode("utf-8-sig"), newline=""))]
assert len(test_text) == 3080

# Local execution of frozen definitions; no CLI entry point, bytecode or writes.
frozen_code = (PACKET / "processor-v1.py").read_bytes()
module = types.ModuleType("independent_day2_frozen_definitions")
module.__file__ = str(PACKET / "processor-v1.py")
exec(compile(frozen_code, module.__file__, "exec"), module.__dict__)
direct_cli_scope = {"resolved_repo": str(module.REPO), "resolved_sources": str(module.SOURCES), "sources_exists": module.SOURCES.exists(), "repo_is_actual_repo": module.REPO == ROOT}
module.REPO, module.OUT, module.CACHE, module.SOURCES = ROOT, PACKET, PACKET / ".cache", PACKET / "sources-v1.json"

output_checks = {}
for name, expected in manifest["outputs"].items():
    b = (PACKET / name).read_bytes()
    output_checks[name] = {"bytes": len(b), "sha256": digest(b), "manifest_hash_match": len(b) == expected["bytes"] and digest(b) == expected["sha256"]}
    assert output_checks[name]["manifest_hash_match"], name
splits = {s: rows(PACKET / (s + ".jsonl")) for s in ["train", "calibration", "eval"]}
all_rows = [r for rr in splits.values() for r in rr]
assert {s: len(rr) for s, rr in splits.items()} == {"train": 7943, "calibration": 993, "eval": 993}
taxonomy = load_json(PACKET / "taxonomy.json")
assert [(r["id"], r["source_label"]) for r in taxonomy["labels"]] == list(enumerate(labels))
publisher_counts = Counter(r["category"] for r in raw)
for t in taxonomy["labels"]:
    assert t["publisher_train_rows"] == publisher_counts[t["source_label"]]
    assert t["retained_by_split"] == {s: sum(r["source_label"] == t["source_label"] for r in rr) for s, rr in splits.items()}

test_clean = [module.scrub(t)[0] for t in test_text]
test_exact = {exact(t) for t in test_clean}
test_template = {template(t) for t in test_clean}
del test_text, test_clean
groups = defaultdict(list)
raw_redactions = Counter()
redacted_raw_count = 0
for i, r in enumerate(raw):
    clean, redactions = module.scrub(r["text"])
    assert module.exact_key(clean) == exact(clean) and module.template_key(clean) == template(clean)
    root = "banking77:" + digest(template(clean).encode())
    groups[root].append({"index": i, "text": clean, "label": r["category"], "redactions": redactions})
    raw_redactions.update(redactions)
    redacted_raw_count += bool(redactions)
quarantine, expected_retained, exclusion_rows = {}, {}, Counter()
for group, members in groups.items():
    categories = {m["label"] for m in members}
    reason = "conflicting_source_labels" if len(categories) > 1 else "exposed_publisher_test_overlap" if any(exact(m["text"]) in test_exact or template(m["text"]) in test_template for m in members) else None
    if reason:
        quarantine[group] = reason
        exclusion_rows[reason] += len(members)
    else:
        expected_retained[group] = members
actual_groups = {r["group_id"]: r for r in all_rows}
assert len(actual_groups) == len(all_rows) == 9929 and set(actual_groups) == set(expected_retained)
dimension_seen = {k: set() for k in ["exact", "template", "record_id", "source_indices", "conversation_roots", "variant_root"]}
neg_pattern = re.compile(r"\b(?:not|no|never|without|cannot)\b|\b\w+n['\u2019]t\b", re.I)
neg_loss, retained_redactions, special_redactions = [], Counter(), []
policy_rows = 0
by_index = {}
allowed_fields = set(all_rows[0])
for split, rr in splits.items():
    assert {r["source_label"] for r in rr} == set(labels)
    for r in rr:
        assert set(r) == allowed_fields
        assert r["source_id"] == "banking77-publisher-train" and r["publisher_split"] == "train"
        assert r["split"] == split and r["task"] == "source_intent_auxiliary"
        assert r["bank_policy_target"] is None and r["ledger_target"] is None
        policy_rows += r["bank_policy_target"] is not None or r["ledger_target"] is not None
        members = expected_retained[r["group_id"]]
        ids = sorted(m["index"] for m in members)
        assert r["source_record_indices"] == ids
        assert r["conversation_root_ids"] == ["banking77-train-row:" + str(i) for i in ids]
        representative = min(members, key=lambda m: (sum(m["redactions"].values()), m["index"]))
        i = representative["index"]
        assert r["record_id"] == "banking77-train:" + str(i).zfill(5)
        assert all(raw[j]["category"] == r["source_label"] for j in ids)
        assert r["source_label_id"] == labels.index(raw[i]["category"])
        assert r["source_text_sha256"] == digest(raw[i]["text"].encode("utf-8"))
        assert r["text"] == representative["text"] and r["redactions"] == representative["redactions"]
        assert r["group_id"] == r["variant_root_id"] == "banking77:" + digest(template(r["text"]).encode())
        assert exact(r["text"]) not in test_exact and template(r["text"]) not in test_template
        values = {"exact": [exact(r["text"])], "template": [template(r["text"])], "record_id": [r["record_id"]], "source_indices": ids, "conversation_roots": r["conversation_root_ids"], "variant_root": [r["variant_root_id"]]}
        for key, vv in values.items():
            assert not dimension_seen[key].intersection(vv), (split, key, r["record_id"])
            dimension_seen[key].update(vv)
        original_neg = Counter(x.lower().replace("\u2019", "'") for x in neg_pattern.findall(unicodedata.normalize("NFKC", raw[i]["text"])))
        current_neg = Counter(x.lower().replace("\u2019", "'") for x in neg_pattern.findall(r["text"]))
        if original_neg - current_neg:
            neg_loss.append({"record_id": r["record_id"], "split": split, "lost_negation_markers": dict(original_neg - current_neg)})
        retained_redactions.update(r["redactions"])
        if "secret_value" in r["redactions"] or "declared_contact" in r["redactions"]:
            special_redactions.append({"record_id": r["record_id"], "split": split, "label": r["source_label"], "original_public_text": raw[i]["text"], "processed_text": r["text"]})
        by_index[i] = r

# Reconstruct hash allocation without calling assign_splits or compile_packet.
expected_split = {}
for label in labels:
    rr = sorted((r for r in all_rows if r["source_label"] == label), key=lambda r: digest(("banking77-source-intent-internal-v1:" + r["group_id"]).encode()))
    held = max(1, round(len(rr) * .1))
    for s, part in [("train", rr[:-2 * held]), ("calibration", rr[-2 * held:-held]), ("eval", rr[-held:])]:
        for r in part:
            assert r["split"] == s
            expected_split[r["group_id"]] = s
assert len(expected_split) == 9929
audits = rows(PACKET / "dedup-quarantine-audit.jsonl")
audit_groups = {r["group_id"]: r for r in audits}
assert set(audit_groups) == {g for g, m in groups.items() if len(m) > 1 or g in quarantine}
for g, audit in audit_groups.items():
    assert audit["source_record_indices"] == sorted(m["index"] for m in groups[g])
    assert audit["source_labels"] == sorted({m["label"] for m in groups[g]})
    assert audit["disposition"] == quarantine.get(g, "deduplicated_to_one_representative")
aliases = sum(len(m) for m in expected_retained.values())
collapsed = aliases - len(all_rows)
assert aliases == 9964 and collapsed == 35 and sum(exclusion_rows.values()) == 39
assert len(quarantine) == 35 and len(groups) == 9964
assert len(raw) == len(all_rows) + collapsed + sum(exclusion_rows.values())

independent_pii_patterns = {
    "email": r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b",
    "url": r"(?:https?://|www\.)\S+",
    "digit": r"\d",
    "iban": r"\b[A-Z]{2}\s?\d{2}(?:\s?[A-Z0-9]){10,30}\b",
    "declared_name": r"\b(?:my name is|i am named|i'm named)\s+(?!\[REDACTED)\w+",
    "kinship_name_candidate": r"\bmy\s+(?:son|daughter|wife|husband|mother|father)\s+([A-Z][a-z]{2,})\b",
}
pii = {k: [] for k in independent_pii_patterns}
for r in all_rows:
    for name, pattern in independent_pii_patterns.items():
        flags = 0 if name == "kinship_name_candidate" else re.I
        if re.search(pattern, r["text"], flags):
            pii[name].append(r["record_id"])

# A stricter contraction alias scan probes a LIMIT, not a declared invariant.
broader_alias = defaultdict(list)
for r in all_rows:
    t = exact(r["text"]).replace("\u2019", "'")
    for a, b in [("don't", "do not"), ("didn't", "did not"), ("doesn't", "does not"), ("isn't", "is not"), ("aren't", "are not"), ("wasn't", "was not"), ("weren't", "were not"), ("hasn't", "has not"), ("haven't", "have not"), ("couldn't", "could not"), ("wouldn't", "would not"), ("shouldn't", "should not")]:
        t = t.replace(a, b)
    broader_alias[template(t)].append(r)
alias_cross = [rr for rr in broader_alias.values() if len({r["split"] for r in rr}) > 1]


def witness(i, include_original=False):
    r = by_index[i]
    out = {"record_id": r["record_id"], "split": r["split"], "source_label": r["source_label"], "text": r["text"]}
    if include_original:
        out["original_public_text"] = raw[i]["text"]
    return out


canonical_code = (ROOT / "integrations/customer-datasets/day2_training_data.py").read_bytes()
canonical_config_path = ROOT / "integrations/customer-datasets/day2_training_sources.json"
canonical_config_bytes = canonical_config_path.read_bytes()
canonical_config = json.loads(canonical_config_bytes)
config_changed = sorted(k for k in set(spec) | set(canonical_config) if spec.get(k) != canonical_config.get(k))
assert all(canonical_config[k] == spec[k] for k in spec)
distribution = {}
for s, rr in splits.items():
    c = Counter(r["source_label"] for r in rr)
    distribution[s] = {"rows": len(rr), "labels": len(c), "min_rows_per_label": min(c.values()), "max_rows_per_label": max(c.values()), "max_min_ratio": round(max(c.values()) / min(c.values()), 4), "per_label": dict(sorted(c.items())), "rows_with_redaction": sum(bool(r["redactions"]) for r in rr), "rows_with_numeric_redaction": sum("numeric_value" in r["redactions"] for r in rr)}

result = {
    "schema_version": 1,
    "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
    "verdict": "source_valid_auxiliary_with_semantic_and_reproducibility_limits",
    "corpus_integrity_blocker": False,
    "bank_permission_or_policy_approval": False,
    "scope": {"packet": PACKET.relative_to(ROOT).as_posix(), "manifest_sha256": digest(manifest_bytes), "writes": [p.relative_to(ROOT).as_posix() for p in OUTPUTS] + [Path(__file__).relative_to(ROOT).as_posix()], "no_network_secrets_env_private_freya_git_models_metrics_or_fits": True, "publisher_test": "3080 rows read solely as exact/delexicalized text contamination guard; no test-label analysis or metrics", "new_source_expansion_reviewed": False},
    "source_pins": source_checks,
    "output_hashes": output_checks,
    "publisher_row_mapping": {"checked_retained_representatives": 9929, "checked_retained_lineage_aliases": aliases, "wrong_source_labels": 0, "wrong_label_ids": 0, "wrong_original_text_hashes": 0, "wrong_scrubbed_text_or_redaction_counts": 0, "publisher_taxonomy_order_match": True, "publisher_train_counts_match": True},
    "accounting": {"publisher_train_rows": len(raw), "template_groups_before_filter": len(groups), "retained_rows": len(all_rows), "retained_original_aliases": aliases, "collapsed_duplicates": collapsed, "quarantined_groups": len(quarantine), "quarantined_source_rows_by_reason": dict(exclusion_rows), "identity": "10003 = 9929 emitted + 35 duplicate aliases collapsed + 39 quarantined original rows"},
    "split_closure": {"declared_exact_template_record_alias_variant_and_row_conversation_keys": "all unique within and across splits", "all_aliases_of_every_retained_raw_template_group_in_one_split": True, "independent_hash_allocation_match": True, "exposed_test_exact_or_declared_template_overlaps": 0, "broader_contraction_alias_cross_split_groups": len(alias_cross), "broader_alias_examples": [[{"record_id": r["record_id"], "split": r["split"], "label": r["source_label"], "text": r["text"]} for r in rr] for rr in alias_cross[:4]], "limits": "Row conversation_root_ids are synthetic original-row identities, not publisher conversation gold. Declared template grouping does not establish all-paraphrase closure or independent/IID semantic gold."},
    "distribution": distribution,
    "policy_mapping": {"non_null_bank_policy_or_ledger_targets": policy_rows, "all_row_fields": sorted(allowed_fields), "target_namespace": taxonomy["label_namespace"], "conclusion": "Publisher support-intent auxiliary targets only. No permission, identity state, debt/payment promise, policy, action authorization, or ledger truth labels exist."},
    "reproducibility": {"frozen_processor_sha256": digest(frozen_code), "manifest_processor_sha_match": digest(frozen_code) == manifest["processor"]["sha256"], "canonical_processor_equal_frozen": canonical_code == frozen_code, "frozen_config_sha256": digest((PACKET / "sources-v1.json").read_bytes()), "manifest_frozen_config_sha_match": digest((PACKET / "sources-v1.json").read_bytes()) == manifest["source_config"]["sha256"], "canonical_config_actual_sha256": digest(canonical_config_bytes), "canonical_config_manifest_sha256": manifest["source_config"]["sha256"], "canonical_config_changed_top_level_fields": config_changed, "all_original_frozen_config_fields_unchanged": True, "copied_processor_direct_cli_scope": direct_cli_scope, "parent_full_recompilation_evidence": "Parent directly recomputed all 13/13 derived artifact bytes and found exact matches; only source_config SHA metadata changed. Accepted as parent evidence, not claimed as repeated independent compilation.", "own_verification": "13 output byte/hash pins plus all retained row mappings/group membership and independent split allocation checked; no full compile_packet repeat or launcher modification", "assessment": "Canonical manifest-only source_config SHA drift due to extra source configuration fields; copied CLI has invalid relative source/root scope. Neither establishes corpus corruption. Collector owns separate reproduction wrapper fix."},
    "redaction": {"raw_rows_with_redactions": redacted_raw_count, "raw_redaction_spans": dict(raw_redactions), "retained_redaction_spans": dict(retained_redactions), "negation_marker_loss_rows": neg_loss, "negation_check_limit": "Literal finite regex marker preservation only; not a semantic negation or intent validation", "secret_or_contact_redaction_witnesses": special_redactions, "digit_loss_examples": [witness(i, True) for i in [1600,3992,2359,3298]], "finding": "All digits are deliberately removed, including non-identifying ages, elapsed durations, transaction amounts and 3D security terminology. Secret regex also consumes ordinary status/question clauses; eval row 01708 has almost no recoverable intent context. A clean hash and source label do not certify transformed-label recoverability."},
    "independent_pii_heuristics": {"pattern_hit_counts": {k: len(v) for k, v in pii.items()}, "record_ids": {k: v[:20] for k, v in pii.items() if v}, "assessment": "No residual digits/email/URL/IBAN or declared-name matches under these patterns. Kinship-name candidates show indirect names are not comprehensively scrubbed. Public/synthetic provenance does not establish that every named entity is fictional; no privacy certification."},
    "quality_witnesses": {"publisher_label_ambiguity": [witness(i, True) for i in [4042,6771,5198,3524,8858]], "answer_like_publisher_rows": [witness(i) for i in [3905,3910,3932,3934]], "cross_split_semantic_family": [witness(i) for i in [8791,8794]], "assessment": "Original labels are faithfully inherited but represent one publisher label per utterance, including composite concerns, ambiguous pending/reverted/failed states and answer-like text. Examples flag review candidates, not independent relabeling gold."},
    "claims_and_recommendations": [
        "Accept as pinned public BANKING77 TRAIN-derived auxiliary support-intent data, with the exact frozen hashes recorded here.",
        "Do not block auxiliary use for metadata drift alone; use the collector's separate frozen-source reproduction launcher once its owner validates it.",
        "Treat severely over-redacted rows and publisher ambiguity as known label-recoverability limitations. In a separately versioned future packet, review status-preserving secret scrubbing and non-identifying numeric semantics; this review changes no rows or splits.",
        "Any future intent-head metrics describe this transformed, grouped internal BANKING77 task. Report per-intent distribution and redaction/ambiguity sensitivity if separately authorized; no metric or model was read here.",
        "Do not claim all-paraphrase leakage elimination, fresh TEST evaluation, IID semantic gold or independent conversation separation. Freeze model/settings before internal eval; keep calibration for threshold selection only.",
        "No supported bank-permission, ledger-correctness, identity verification, debt collection/payment-promise, Turkish/multilingual, multi-turn/context, numeric-threshold/reconciliation, blind-policy-OOD or unknown-intent domain evidence exists in this packet.",
        "NLU++ and Taskmaster expansion data and the collector launcher are outside this bounded frozen BANKING77 review.",
    ],
    "attribution_and_license": {"publisher_license_exact_pinned_bytes": output_checks["BANKING77-LICENSE.txt"]["sha256"] == source_checks["license"]["sha256"], "publisher_readme_exact_pinned_bytes": output_checks["BANKING77-PUBLISHER-README.md"]["sha256"] == source_checks["publisher_readme"]["sha256"], "notice_has_revision_attribution_license_modifications": all(x in (PACKET / "NOTICE.txt").read_text(encoding="utf-8") for x in [spec["revision"], spec["attribution"], "CC-BY-4.0", "Modified:"]), "scope": "Artifact/provenance check, not legal interpretation"},
}
text = [
    "INDEPENDENT FROZEN BANKING77 PUBLIC DATA REVIEW",
    "Verdict: source-valid auxiliary support-intent data, with semantic and reproducibility limits. No corpus-integrity blocker found. No bank permission/policy approval.",
    "Manifest SHA256: " + result["scope"]["manifest_sha256"],
    "Pinned publisher TRAIN: 10003 rows / 77 labels. Emitted train/calibration/eval: 7943/993/993; all 77 labels in every split.",
    "Every 9929 retained representative and 9964 lineage alias maps to its original publisher TRAIN label, taxonomy ID, source-text hash and scrubbed text. No mismatches.",
    "Accounting: 10003 = 9929 emitted + 35 duplicate aliases collapsed + 39 quarantined original rows (5 conflicting-label, 34 exposed-TEST overlaps); 35 quarantined groups.",
    "All 13 manifest-listed output byte/hash pins match. Exact/template/variant/root/original-row aliases are unique across splits; all raw aliases stay in their retained root. Independent deterministic split allocation matches.",
    "Publisher TEST: 3080 rows, strict text contamination guard only; zero declared exact/delex overlaps. No test labels, model inputs, fits or performance metrics used.",
    "Reproducibility: canonical source_config SHA drift fddb66f3... -> 9c5f6d1e... comes solely from expansion_sources and expansion_note; all frozen fields unchanged. Canonical and frozen processor bytes match. Parent reports 13/13 full derived recompilation byte matches; this reviewer did not repeat full compilation.",
    "Copied processor direct CLI has incorrect root/source relative paths. Local definitions were scoped explicitly in memory; no source changes persisted. Collector owns separate reproduction wrapper fix.",
    "Redaction quality: " + str(redacted_raw_count) + " raw rows changed; " + str(retained_redactions["secret_value"]) + " retained secret-regex spans include ordinary PIN/passcode status or question clauses. Eval 01708: 'If my PIN number is rejected, how do I solve it?' becomes 'If [REDACTED_SECRET_VALUE]?'",
    "Digits: age row 01600 loses '16'; identity row 03992 redacts '18' in 'under 18'; withdrawal row 02359 loses 100 versus 80; eval row 03298 changes '3D secure' to '[REDACTED_NUMERIC_VALUE]D secure'. This limits numeric/intent recoverability even with faithful original labels.",
    "Finite literal negation-marker loss count: " + str(len(neg_loss)) + "; this does not certify semantic negation quality.",
    "Independent PII pattern hits: " + json.dumps({k: len(v) for k, v in pii.items()}, sort_keys=True) + ". Indirect-name candidates remain; no privacy certification.",
    "Source quality: row 04042 asks about a PIN but publisher label is get_physical_card; eval 06771 concerns seller non-receipt but carries reverted_card_payment?; eval 03524 combines freeze/investigate/refund under card_payment_not_recognised. These are publisher ambiguity candidates, not corrected labels.",
    "Some unable_to_verify_identity rows are answer-like verification/eligibility prose. Same semantic family appears in calibration 08791 and eval 08794 despite different declared template roots. Broader contraction-alias cross-split groups: " + str(len(alias_cross)) + ". All-paraphrase closure and IID semantic gold are unsupported.",
    "Concrete broader aliases: train 03984 'isn't working' / calibration 03968 'is not working'; train 03980 'doesn't believe' / eval 03922 'does not believe'. Both pairs carry unable_to_verify_identity. These fall outside the processor's five declared contraction expansions.",
    "Distribution: train per-intent counts range 27..149; each held-out split ranges 4..19. Tiny held-out classes and class imbalance constrain per-intent metric interpretation.",
    "Bank-policy and ledger targets: all null. Support intents imply no permission, verification success, debt/payment commitment, policy authority or ledger truth.",
    "Unsupported evidence domains: Turkish/multilingual debt collection; multi-turn context; safe bank actions; numeric threshold/reconciliation; blind policy OOD; unknown-intent rejection. New source expansions/launcher are not reviewed here.",
    "No packet/config mutation, network, secrets/env/private/Freya/Git access, training, weights, model metrics or fitting. Only the new review witness/JSON/TXT files are owned by this reviewer.",
    "See JSON for exact hashes, per-label distributions and concrete row witnesses. Any future metrics apply only to the transformed internal source-intent task and should disclose redaction and source ambiguity limits.",
]
if not CHECK_ONLY:
    with OUTPUTS[0].open("x", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    with OUTPUTS[1].open("x", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(text) + "\n")
print(json.dumps({"verdict": result["verdict"], "mapping_checks": result["publisher_row_mapping"], "split_distribution": {s: {k: v for k, v in d.items() if k != "per_label"} for s, d in distribution.items()}, "raw_redactions": dict(raw_redactions), "negation_loss_rows": len(neg_loss), "pii_hits": {k: len(v) for k, v in pii.items()}, "broader_contraction_alias_cross_split_groups": len(alias_cross), "reports": [str(p) for p in OUTPUTS]}, ensure_ascii=False))
