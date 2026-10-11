"""Independent v2 collection/processing; leaves every handed-off v1 byte frozen."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import time
import types

BASE = Path(__file__).resolve().parent
REPO = BASE.parents[2]
OUT = BASE / "v2"
CONFIG = OUT / "sources.json"
v1 = types.ModuleType("frozen_v1")
v1.__file__ = str(BASE / "processor-v1.py")
exec(compile(Path(v1.__file__).read_bytes(), v1.__file__, "exec"), v1.__dict__)
v1.REPO, v1.OUT, v1.CACHE = REPO, BASE, BASE / ".cache"
v1.HERE, v1.SOURCES = REPO / "integrations/customer-datasets", BASE / "sources-v1.json"
HEADS = ("banking77_intent", "nlupp_intents", "nlupp_slot_presence", "taskmaster_next_utterance", "bank_policy", "ledger")


def mask(*heads):
    return {head: head in heads for head in HEADS}


def collect(offline=False):
    config = json.loads(CONFIG.read_bytes())
    inputs, provenance = {}, []
    deadline = time.monotonic() + 120
    for item in config["expansion_sources"]:
        v1.require(re.fullmatch(r"https://raw\.githubusercontent\.com/(?:PolyAI-LDN/task-specific-datasets/57ec275d8078af65b7731c2a98be812d844a6d6b|google-research-datasets/Taskmaster/d92cb6af3005f1dc09c39e75e7daf4a04905e00b)/[\w./-]+", item["url"]), "Unpinned/nonofficial source")
        v1.require(0 < item["bytes"] <= item["max_bytes"] <= 20_000_000, "Invalid source size")
        inputs[item["cache_name"]] = v1.source_bytes(item, offline=offline, deadline=deadline)
        provenance.append({key: item[key] for key in ("role", "url", "sha256", "bytes")})
    return config, inputs, provenance


def spans_scrub(text, spans):
    # Values are masked from publisher-annotated spans, before generic scrubbing.
    intervals = []
    for span in spans:
        v1.require(isinstance(span, (list, tuple)) and len(span) == 2, "Invalid entity span")
        a, b = span
        v1.require(type(a) is int and type(b) is int and 0 <= a < b <= len(text), "Invalid entity bounds")
        intervals.append((a, b))
    merged = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    for a, b in reversed(merged):
        text = text[:a] + "[REDACTED_ENTITY]" + text[b:]
    return v1.scrub(text)[0]


def nlupp(config, inputs, forbidden):
    ontology = json.loads(inputs["nlupp-ontology.json"])
    intents, slots = list(ontology["intents"]), list(ontology["slots"])
    buckets, audit, raw_count = defaultdict(list), [], 0
    for spec in config["expansion_sources"]:
        if spec["role"] != "nlupp_fold":
            continue
        for index, row in enumerate(json.loads(inputs[spec["cache_name"]])):
            raw_count += 1
            domain = spec["domain"]
            annotations = row.get("slots", {})
            cleaned = spans_scrub(row["text"], [s["span"] for s in annotations.values()])
            source_intents = sorted(row.get("intents", []))
            source_slots = sorted(annotations)
            v1.require(set(source_intents) <= set(intents) and set(source_slots) <= set(slots), "Unknown NLU++ annotation")
            intent_mask = ["general" in ontology["intents"][x]["domain"] or domain in ontology["intents"][x]["domain"] for x in intents]
            slot_mask = ["general" in ontology["slots"][x]["domain"] or domain in ontology["slots"][x]["domain"] for x in slots]
            v1.require(all(intent_mask[intents.index(x)] for x in source_intents), "Positive intent outside domain mask")
            v1.require(all(slot_mask[slots.index(x)] for x in source_slots), "Positive slot outside domain mask")
            key = v1.template_key(cleaned)
            ident = "nlupp:" + domain + ":fold" + str(spec["fold"]) + ":" + str(index)
            record = {"record_id": ident, "source_id": "polyai-nlupp", "publisher_source": "folds0..17; large-regime training when18..19 held out",
                      "source_domain": domain, "source_fold": spec["fold"], "source_record_ids": [ident], "text": cleaned,
                      "source_text_sha256": v1.sha(row["text"].encode()), "source_intents": source_intents, "source_slot_types": source_slots,
                      "head_mask": mask("nlupp_intents", "nlupp_slot_presence"),
                      "targets": {"nlupp_intents": [int(x in source_intents) for x in intents], "nlupp_slot_presence": [int(x in source_slots) for x in slots]},
                      "target_element_masks": {"nlupp_intents": intent_mask, "nlupp_slot_presence": slot_mask},
                      "slot_value_target_mask": False, "canonical_slot_reference": {"date": "2022-03-15", "time": "09:00", "scope": "publisher_only_not_bank_calendar"},
                      "group_id": "nlupp:" + v1.sha(key.encode()), "conversation_root_ids": [ident]}
            # Guard both raw generic-scrubbed and annotated-value-scrubbed forms.
            generic = v1.scrub(row["text"])[0]
            record["_forbidden"] = v1.exact_key(generic) in forbidden[0] or v1.template_key(generic) in forbidden[1] or v1.template_key(cleaned) in forbidden[1]
            buckets[key].append(record)
    retained, dropped = [], Counter()
    for key, rows in sorted(buckets.items()):
        signatures = {(tuple(r["source_intents"]), tuple(r["source_slot_types"]), r["source_domain"]) for r in rows}
        reason = "frozen_banking77_or_exposed_test_overlap" if any(r["_forbidden"] for r in rows) else "conflicting_annotations" if len(signatures) > 1 else None
        if reason:
            dropped[reason] += len(rows)
        else:
            winner = min(rows, key=lambda r: r["record_id"])
            winner["source_record_ids"] = sorted(r["record_id"] for r in rows)
            winner["conversation_root_ids"] = winner["source_record_ids"].copy()
            winner.pop("_forbidden")
            retained.append(winner)
            dropped["deduplicated"] += len(rows) - 1
        if reason or len(rows) > 1:
            audit.append({"source": "nlupp", "group_id": rows[0]["group_id"], "source_record_ids": sorted(r["record_id"] for r in rows), "disposition": reason or "deduplicated"})
    taxonomy = {"intents": [{"id": i, "name": name, **ontology["intents"][name]} for i, name in enumerate(intents)],
                "slots": [{"id": i, "name": name, **ontology["slots"][name]} for i, name in enumerate(slots)], "element_masks": "general plus source domain only; other-domain targets unknown/masked", "slot_values": "removed; not policy dates"}
    return retained, audit, {"raw_rows": raw_count, "retained": len(retained), "disposition_rows": dict(dropped), "original_domains": {"banking": 1867, "hotels": 911}, "publisher_heldout_folds18_19": "not_downloaded_or_refit"}, taxonomy


class Closure:
    def __init__(self, ids):
        self.parent = {x: x for x in ids}
    def root(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x
    def join(self, a, b):
        a, b = self.root(a), self.root(b)
        self.parent[max(a, b)] = min(a, b)


def taskmaster(inputs):
    source = json.loads(inputs["taskmaster3-shard00.data"])
    ids = [c["conversation_id"] for c in source]
    v1.require(len(set(ids)) == len(ids) == 1188, "Unexpected Taskmaster shard")
    closure, keys, candidates = Closure(ids), {}, []
    empty_turns = 0
    for conv in source:
        ident = conv["conversation_id"]
        # Scenario titles are publisher template IDs (their numbers are not PII).
        scenario_key = "scenario:" + v1.exact_key(conv["scenario"])
        instruction_key = "instructions:" + v1.template_key(v1.scrub(conv["instructions"])[0])
        for key in (scenario_key, instruction_key):
            if key in keys:
                closure.join(ident, keys[key])
            keys[key] = ident
        turns = []
        for i, turn in enumerate(conv["utterances"]):
            v1.require(turn["index"] == i and turn["speaker"] in ("user", "assistant"), "Invalid source turn")
            if not turn["text"].strip():
                text = "[EMPTY_SOURCE_TURN]"
                empty_turns += 1
            else:
                text = spans_scrub(turn["text"], [(s["start_index"], s["end_index"]) for s in turn.get("segments", [])])
            turns.append({"source_turn_index": i, "speaker": turn["speaker"], "text": text})
        valid = [i for i, t in enumerate(turns) if i >= 3 and t["speaker"] == "assistant" and t["text"] != "[EMPTY_SOURCE_TURN]"]
        if not valid:
            continue
        selected = sorted({valid[len(valid) // 2], valid[-1]})
        for target_index in selected:
            context = turns[max(0, target_index - 6):target_index]
            context_key = "context:" + "|".join(t["speaker"] + ":" + v1.template_key(t["text"]) for t in context)
            if context_key in keys:
                closure.join(ident, keys[context_key])
            keys[context_key] = ident
            row = {"record_id": "taskmaster3:" + ident + ":" + str(target_index), "source_id": "google-taskmaster3-shard00",
                   "source_conversation_id": ident, "source_scenario": conv["scenario"], "source_record_ids": ["taskmaster3:" + ident + ":" + str(target_index)],
                   "conversation_root_ids": [ident], "context": context, "text": context[-1]["text"],
                   "graph": {"node_ids": [str(t["source_turn_index"]) for t in context], "edges": [[i, i + 1, "observed_next_turn"] for i in range(len(context) - 1)]},
                   "targets": {"taskmaster_next_utterance": turns[target_index]["text"]}, "target_speaker": "assistant",
                   "target_source_turn_index": target_index, "head_mask": mask("taskmaster_next_utterance"), "api_or_bank_target_mask": False}
            row["_template"] = context_key + ":target:" + v1.template_key(row["targets"]["taskmaster_next_utterance"])
            candidates.append(row)
    roots = defaultdict(list)
    for ident in ids:
        roots[closure.root(ident)].append(ident)
    group_ids = {root: "taskmaster3:" + v1.sha(v1.jsonl(sorted(members))) for root, members in roots.items()}
    unique, duplicates = {}, 0
    for row in candidates:
        row["group_id"] = group_ids[closure.root(row["source_conversation_id"])]
        key = row.pop("_template")
        if key in unique:
            previous = unique[key]
            v1.require(previous["group_id"] == row["group_id"], "Template closure failed")
            previous["source_record_ids"].extend(row["source_record_ids"])
            previous["conversation_root_ids"] = sorted(set(previous["conversation_root_ids"] + row["conversation_root_ids"]))
            duplicates += 1
        else:
            unique[key] = row
    v1.require(len(unique) <= 2400, "Context-pair bound exceeded")
    return list(unique.values()), {"raw_conversations": len(source), "raw_turns": sum(len(c["utterances"]) for c in source), "empty_source_turns_preserved": empty_turns,
                                 "selected_actual_context_pairs": len(candidates), "deduplicated_pairs": duplicates, "retained_pairs": len(unique), "conversation_template_closure_groups": len(roots)},


def grouped(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["group_id"]].append(row)
    ordered = sorted(groups, key=lambda x: v1.sha(("v2-internal-source-context:" + x).encode()))
    v1.require(len(ordered) >= 3, "Insufficient independent closure groups")
    hold = max(1, round(len(ordered) * .1))
    assigned = {x: "train" for x in ordered[:-2 * hold]}
    assigned.update({x: "calibration" for x in ordered[-2 * hold:-hold]})
    assigned.update({x: "eval" for x in ordered[-hold:]})
    return [dict(row, split=assigned[row["group_id"]]) for row in rows]


def compile_v2(offline):
    config, inputs, provenance = collect(offline)
    bank_manifest = json.loads((BASE / "manifest.json").read_bytes())
    forbidden = (set(), set())
    bank = []
    for split in v1.SPLITS:
        content = (BASE / (split + ".jsonl")).read_bytes()
        v1.require(v1.sha(content) == bank_manifest["outputs"][split + ".jsonl"]["sha256"], "Frozen BANKING77 changed")
        for row in map(json.loads, content.splitlines()):
            forbidden[0].add(v1.exact_key(row["text"]))
            forbidden[1].add(v1.template_key(row["text"]))
            row["head_mask"], row["targets"] = mask("banking77_intent"), {"banking77_intent": row["source_label_id"]}
            bank.append(row)
    for row in v1.csv_rows(v1.source_bytes(v1.specs()["files"][-1], offline=True)):
        clean = v1.scrub(row["text"])[0]
        forbidden[0].add(v1.exact_key(clean)); forbidden[1].add(v1.template_key(clean))
    nlu, audit, nlu_counts, taxonomy = nlupp(config, inputs, forbidden)
    tm, tm_counts = taskmaster(inputs)
    rows = bank + grouped(nlu) + grouped(tm)
    parts = {split: sorted((r for r in rows if r["split"] == split), key=lambda r: r["record_id"]) for split in v1.SPLITS}
    source_counts = {source: {split: sum(r["source_id"] == source for r in parts[split]) for split in parts} for source in sorted({r["source_id"] for r in rows})}
    owners, contexts, ids = {}, {}, set()
    for row in rows:
        v1.require(row["record_id"] not in ids, "Duplicate ID"); ids.add(row["record_id"])
        v1.require(not row["head_mask"]["bank_policy"] and not row["head_mask"]["ledger"], "Invented policy/ledger targets")
        v1.require(set(row["targets"]) == {k for k,v in row["head_mask"].items() if v}, "Head mask mismatch")
        for key in [row["group_id"]] + row["conversation_root_ids"]:
            v1.require(key not in owners or owners[key] == row["split"], "Group/conversation split leakage")
            owners[key] = row["split"]
        texts = [t["text"] for t in row["context"]] + [row["targets"]["taskmaster_next_utterance"]] if "context" in row else [row["text"]]
        for text in texts:
            v1.require(v1.scrub(text)[0] == text, "Residual sensitive span / scrub not idempotent")
        if "context" in row:
            key = "|".join(t["speaker"] + ":" + v1.template_key(t["text"]) for t in row["context"])
        else:
            key = v1.template_key(row["text"])
        v1.require(key not in contexts or contexts[key] == row["split"], "Cross-source/cross-split template leakage")
        contexts[key] = row["split"]
    coverage = {split: {name: sum(name in r.get("source_intents", []) for r in parts[split] if r["source_id"] == "polyai-nlupp") for name in [x["name"] for x in taxonomy["intents"]]} for split in parts}
    validation = {"status": "passed", "group_conversation_template_cross_split_overlap": 0, "cross_source_text_template_split_overlap": 0,
                  "head_mask_target_mismatches": 0, "bank_policy_ledger_targets": 0, "scrubbing_idempotence": "passed", "nlupp_positive_intent_coverage_per_split": coverage,
                  "eval_scope": "internal train-fold/shard-derived; not fresh publisher benchmark or blind policy OOD", "privacy_limit": "heuristic regex and publisher entity spans; no universal anonymity guarantee"}
    notice = """V2 actual public source-specific training packet. BANKING77 support labels (77), NLU++ multi-label intents (62) and slot-type presence (17), and Taskmaster actual assistant next-turn context are separate heads. Never merge them into 77-class gold. head_mask and NLU++ target_element_masks exclude unknown/incompatible targets. No bank-policy or ledger target exists.

NLU++: PolyAI; Inigo Casanueva, Ivan Vulic, Georgios Spithourakis and Pawel Budzianowski (2022), NLU++: A Multi-Label, Slot-Rich, Generalisable Dataset for Natural Language Understanding in Task-Oriented Dialogue. https://arxiv.org/abs/2204.13021 . Official pinned README/ontology retained. Only banking/hotels folds0..17 collected. Folds18..19 are untouched (publisher large-regime heldout for that rotation). New splits here are internal grouped splits, not publisher benchmark scores. Canonical slot date reference2022-03-15,time09:00 is publisher metadata, never Freya/bank policy dates. Slot values/spans are redacted; only original intent and slot-type annotations supervise source heads.

Taskmaster3/TicketTalk: Bill Byrne, Karthik Krishnamoorthi, Saravanan Ganesh; Google LLC. Pinned shard00 contains1188 conversations/24059 turns, a subset of the full23789 crowdsourced self-dialogues. At most2 actual assistant targets per conversation, with up to6 actual preceding turns and observed sequence graph edges. No API payloads, fabricated clarification labels, or bank-action targets exported. All conversation descendants, same publisher scenario/template instructions and detected duplicate contexts close into groups BEFORE splitting. Duplicate pair representatives retain original aliases.

All three public datasets use CC-BY-4.0; full publisher license, notices and readmes retained. See frozen V1 NOTICE for BANKING77 attribution. Modified: entity/value/PII scrubbing, dedup/quarantine, lineage, graph/target packaging and internal splits. Source text and next-turn labels are actual publisher examples, not synthetic policy gold. Annotation masks and provenance are part of training input contract. Bank adaptation independent domain review is pending. Actual blind policy OOD remains reserved separately with parent. No model training or hosted calls performed here.

Collect: python research/customer-benchmark/day2-training-data/build-v2.py --collect-only --offline
Process: python research/customer-benchmark/day2-training-data/build-v2.py --process-only
Reproduce both stages: python research/customer-benchmark/day2-training-data/build-v2.py --offline
Verify: python research/customer-benchmark/day2-training-data/build-v2.py --verify --offline
V1 independently: python research/customer-benchmark/day2-training-data/reproduce-v1.py
Read train.jsonl and route losses by head_mask; for multi-label losses also apply target_element_masks. calibration/eval are internal holdouts. Do not use heldout rows for weight fitting. Variants/translation descendants must inherit source group_id and split.
"""
    artifacts = {split + ".jsonl": v1.jsonl(parts[split]) for split in parts}
    artifacts.update({"nlupp-taxonomy.json": v1.encoded(taxonomy), "validation.json": v1.encoded(validation), "quarantine-audit.jsonl": v1.jsonl(audit), "NOTICE.txt": notice.encode(),
                      "banking77-taxonomy.json": (BASE / "taxonomy.json").read_bytes(),
                      "collection-manifest.json": v1.encoded({"stage": "collection", "source_config_sha256": v1.sha(CONFIG.read_bytes()), "verified_sources": provenance}),
                      "NLUPP-PUBLISHER-README.md": inputs["nlupp-readme.md"], "TASKMASTER3-PUBLISHER-NOTICE.md": inputs["taskmaster3-shard00-license.data"], "CC-BY-4.0-LICENSE.txt": (BASE / "BANKING77-LICENSE.txt").read_bytes()})
    v1.require(sum(map(len, artifacts.values())) <= 32_000_000, "V2 derived size bound exceeded")
    manifest = {"schema_version": 2, "status": "ready_for_source_head_training", "actual_training_executed": False,
                "frozen_v1_manifest": {"path": v1.relative(BASE / "manifest.json"), "sha256": v1.sha((BASE / "manifest.json").read_bytes())},
                "source_files": provenance, "license": "CC-BY-4.0", "counts": {"banking77": bank_manifest["counts"], "nlupp": nlu_counts, "taskmaster": tm_counts, "split_source_examples": source_counts, "split_total_examples": {s:len(parts[s]) for s in parts}},
                "heads": {"banking77_intent": "77-class source intent; inherited V1 splits", "nlupp_intents": "62-class multi-label with domain masks", "nlupp_slot_presence": "17-class multi-label slot types; values unknown/masked", "taskmaster_next_utterance": "actual sanitized next assistant text from observed context", "bank_policy": "unknown/masked", "ledger": "unknown/masked"},
                "invariants": validation, "raw_cache": "ignored parent .cache; Taskmaster existing ignored adapter cache", "bank_adaptation": "independent domain review pending; auxiliary source training is ready",
                "processor": {"path": v1.relative(Path(__file__).resolve()), "sha256": v1.sha(Path(__file__).read_bytes())}, "source_config": {"path": v1.relative(CONFIG), "sha256": v1.sha(CONFIG.read_bytes())},
                "outputs": {name:{"path":v1.relative(OUT/name),"sha256":v1.sha(data),"bytes":len(data),"rows":len(parts[name[:-6]]) if name.endswith('.jsonl') and name[:-6] in parts else None} for name,data in sorted(artifacts.items())}}
    return artifacts, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--verify", action="store_true")
    modes.add_argument("--collect-only", action="store_true")
    modes.add_argument("--process-only", action="store_true")
    args = parser.parse_args()
    if args.collect_only:
        _, _, sources = collect(args.offline)
        data = {"stage": "collection", "source_config_sha256": v1.sha(CONFIG.read_bytes()), "verified_sources": sources}
        (OUT/"collection-manifest.json").write_bytes(v1.encoded(data))
        print(json.dumps({"collection": "ready", "verified_source_files": len(sources)}, sort_keys=True))
        return
    if args.process_only:
        v1.require((OUT/"collection-manifest.json").is_file(), "Collect expansion sources before processing")
    artifacts, manifest = compile_v2(args.offline or args.process_only or args.verify)
    if args.verify:
        v1.require((OUT/"manifest.json").read_bytes() == v1.encoded(manifest), "V2 manifest recompute mismatch")
        for name,data in artifacts.items():
            v1.require((OUT/name).read_bytes() == data, "V2 artifact recompute mismatch:"+name)
    else:
        for name,data in artifacts.items():
            (OUT/name).write_bytes(data)
        (OUT/"manifest.json").write_bytes(v1.encoded(manifest))
    summary = {"status": manifest["status"], "verified": args.verify, "manifest_path": v1.relative(OUT/"manifest.json"), "manifest_sha256": v1.sha(v1.encoded(manifest)), "counts": manifest["counts"], "ready_files": {s:manifest["outputs"][s+'.jsonl'] for s in v1.SPLITS}, "invariants": manifest["invariants"], "frozen_v1_manifest": manifest["frozen_v1_manifest"]}
    (REPO/"analysis/day2-data-collection.json").write_bytes(v1.encoded(summary))
    lines=["Actual V1 BANKING77 frozen; V2 additional NLU++/Taskmaster source-head packet ready.",json.dumps({"manifest":summary["manifest_path"],"sha256":summary["manifest_sha256"],"counts":manifest["counts"]["split_source_examples"]},sort_keys=True),"Recompute verification: "+str(args.verify),"No policy/ledger gold; all holdouts internal. Independent bank adaptation review pending."]
    (REPO/"analysis/day2-data-collection.txt").write_bytes(('\n'.join(lines)+'\n').encode())
    print(json.dumps({k:summary[k] for k in ('status','verified','manifest_path','manifest_sha256','counts')},sort_keys=True))


if __name__ == "__main__":
    main()
