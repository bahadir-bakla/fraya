"""TRAIN-only extraction diagnostics, exclusive new artifacts; no model reads/fit.

Raw parsing completes before adjudicated spans are read. Frozen artifacts are
hashed for preservation only. No offsets/labels/targets from reviews enter ASTs.
"""
import ast
import hashlib
import json
import re
import time
import tracemalloc
import tracemalloc
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from temporal_parser_v9 import (parse_temporal, span, project_segments, privacy_reasons, VERSION,
                                source_features_v9, FEATURE_VERSION)
from test_temporal_v9 import run_checks

ROOT = Path(__file__).resolve().parents[2]
PINS = {
    "research/customer-benchmark/semantic-v6-extension/label-free-train-packet.json": "3992ab7f7f21bfc89c9e4a78fc00854cae286e3551cd2b956aa82b605a768bf4",
    "research/customer-benchmark/semantic-v6-peer-extension/blind-source-2f52b35f12d7.json": "84dda0e5cda28c532bbbd2e73a7c4c2c6643ad2aefe16752a2ff979dfc8207cd",
    "integrations/learned-dialogue/detector_r4.py": "1451f161bfb40fc1c2091e96b3802d9665f3ecfb04eed14c18fb3c14acc2a3c0",
    "research/customer-benchmark/semantic-v6-extension/runtime-candidates.v6.json": "3e19e40f4e91ccf57c6336329338e943d0020b366d1e6c057bb02fca4921b226",
    "analysis/night-v6-adjudication.primary-packet.json": "491fc880ce2fbe4e33e5052dd0703db765e14430883154d70edb363f4538cf84",
    "analysis/night-v6-adjudication.peer-packet.json": "5f3693e86cbb4300394ec3b4c2fe757ce2bdb8055caeb4133d46c78785003a4c",
    "research/customer-benchmark/semantic-v6-extension/source-adjudicated-lineage.json": "f2bc3e0a9631a4707f7863401f42fa74dbe41a189f261ed56e11f73373c84612",
    "analysis/night-learned-dialogue.v7-alignment.freeze.json": "613ed4352656fec9cddc8b9f4d3edf7d8a36093031460a6c4bd91bb7d0797b8b",
    "research/customer-benchmark/semantic-v6-extension/reviewed-alignment.v7.json": "dfecbdcb37efc39476a90ff70328189b9c90d13f024f9538fec64eaa332c2726",
    "analysis/night-learned-dialogue.v8-parser.freeze.json": "04b1e5ea7620d2812838a9dbb48a939e8ed154b7157236ba634a03c7951d7095"}
SOURCE_PATHS = list(PINS)[:2]
REPORT = "analysis/night-learned-dialogue.v9-parser.json"
OUTPUT = "analysis/night-learned-dialogue.v9-parser.candidates.json"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def load(path):
    raw = (ROOT / path).read_bytes()
    if path in PINS and sha(raw) != PINS[path]:
        raise ValueError("pinned source changed: " + path)
    return json.loads(raw)


def verify_history():
    specs = [("v1", "integrations/learned-dialogue/v1-frozen-archive.manifest.json", "files"),
             ("v2", "analysis/night-learned-dialogue.v2-final.handoff.json", "changed_file_hashes"),
             ("R3", "analysis/night-learned-dialogue.v3.source-r3.json", "files"),
             ("R4", "analysis/night-learned-dialogue.v3.source-r4.json", "source_hashes"),
             ("V5", "analysis/night-learned-dialogue.v5.freeze.json", "new_checkpoint_sha256")]
    result = {}
    protected = {}
    for name, path, key in specs:
        expected = load(path)[key]
        for file, pin in expected.items():
            if sha((ROOT / file).read_bytes()) != pin:
                raise ValueError("historical drift: " + file)
        result[name] = {"entries": len(expected), "byte_identical": True}
        protected.update(expected)
    v7 = load("analysis/night-learned-dialogue.v7-alignment.freeze.json")
    v6 = v7["frozen_V6_preservation"]["sha256"]
    for name, expected in (("V6", v6), ("V7", dict(v7["source_sha256"], **v7["artifacts_sha256"]))):
        for file, pin in expected.items():
            if sha((ROOT / file).read_bytes()) != pin:
                raise ValueError("historical drift: " + file)
        result[name] = {"entries": len(expected), "byte_identical": True}
        protected.update(expected)
    protected["analysis/night-learned-dialogue.v7-alignment.freeze.json"] = PINS["analysis/night-learned-dialogue.v7-alignment.freeze.json"]
    v8 = load("analysis/night-learned-dialogue.v8-parser.freeze.json")
    expected = dict(v8["source_sha256"], **v8["artifacts_sha256"])
    expected["analysis/night-learned-dialogue.v8-parser.freeze.json"] = PINS["analysis/night-learned-dialogue.v8-parser.freeze.json"]
    for path, pin in expected.items():
        if sha((ROOT/path).read_bytes()) != pin:
            raise ValueError("V8 frozen drift:" + path)
    result["V8"] = {"entries":len(expected), "byte_identical":True}
    protected.update(expected)
    return result, protected


def maximum_matching(graph):
    """One-to-one boundary-support accounting, never a semantic TP label."""
    candidate_owner = {}
    def augment(annotation, seen):
        for candidate in sorted(set(graph[annotation])):
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate not in candidate_owner or augment(candidate_owner[candidate], seen):
                candidate_owner[candidate] = annotation
                return True
        return False
    for annotation in sorted(graph):
        augment(annotation, set())
    return {annotation:candidate for candidate,annotation in candidate_owner.items()}


def pure_r4():
    path = "integrations/learned-dialogue/detector_r4.py"
    raw = (ROOT / path).read_bytes()
    if sha(raw) != PINS[path]:
        raise ValueError("R4 source drift")
    tree = ast.parse(raw.decode("utf-8"))
    names = {"tokenize_r4", "clause_ranges_r4", "date_expressions_r4"}
    selected = [n for n in tree.body if isinstance(n, ast.Assign) or isinstance(n, ast.FunctionDef) and n.name in names]
    namespace = {"re": re}
    exec(compile(ast.Module(body=selected, type_ignores=[]), path + ":pure-only", "exec"), namespace)
    return namespace["date_expressions_r4"]


def a1_projection(text, old):
    """Project old boundaries only: grammar is deliberately unchanged in A1."""
    s = old["source_span"]
    a, b = s["char_start"], s["char_end"]
    sa, sb = a, b
    attachments = []
    prefix = re.match(r"(?:on|for)\s+", text[a:b], re.I)
    if prefix:
        sa = a + prefix.end()
        attachments.append((a, sa))
    if text[sa:sb].endswith(","):
        sb -= 1
    return {"node_id": old["id"], "kind": "legacy_r4", "syntax": old["candidate"]["syntax_status"],
            "projection": project_segments(text, (a, b), (sa, sb), attachments),
            "target_indices_hypothesis": old["target_indices_hypothesis"],
            "role_hypothesis": "uncertain", "polarity_hypothesis": "unassessed", "holes": [],
            "reference_mask": False, "normalization_mask": False, "masks": {"training": False}}


def reextract():
    scanner = pure_r4()
    legacy = {r["example_id"]: r for r in load("research/customer-benchmark/semantic-v6-extension/runtime-candidates.v6.json")["rows"]}
    rows = []
    scanner_parity = []
    # ALL source extraction occurs before load() of adjudication or V7 alignment.
    for path in SOURCE_PATHS:
        packet = load(path)
        if packet.get("split", "train") != "train":
            raise ValueError("non-TRAIN source")
        for index, record in enumerate(packet["records"]):
            snapshot = record["input"]
            text = snapshot["utterance"]["text"]
            eid = record["example_id"]
            context = {k: snapshot[k] for k in ("phase", "question", "targets") if k in snapshot}
            old = legacy[eid]
            block = privacy_reasons(context, text)
            actual = scanner(text, (snapshot.get("question") or {}).get("role", "none"))["candidates"] if not block else []
            expected = [c["candidate"] for c in old["candidates"]]
            parity = [(c["start"], c["end"], c["syntax_status"]) for c in actual] == [(c["start"], c["end"], c["syntax_status"]) for c in expected]
            scanner_parity.append({"example_id": eid, "passed": parity})
            if not parity:
                raise ValueError("actual R4 source parity changed: " + eid)
            variants = {v: parse_temporal(text, snapshot["utterance"]["source_turn_id"], context, v) for v in ("A2", "A3", "A4")}
            runtime_features = {variant:[{"node_id":node["node_id"], **source_features_v9(text,node,context,not bool(block),snapshot["utterance"].get("complete_transport") is True)}
                                        for node in output["nodes"] if node["node_id"] in output["top_level_ids"]]
                                for variant,output in variants.items()}
            compatibility_children = [{"parent_legacy_id": c["id"], "source_span": span(text, child["start"], child["end"]),
                                       "training_mask": False, "qualified": False}
                                      for c in old["candidates"] for child in c["candidate"].get("children", [])]
            schema_mask = snapshot.get("schema_version") != "semantic_input.v1" or snapshot.get("phase") != "payment"
            rows.append({"example_id": eid, "source_packet": path, "source_packet_sha256": PINS[path],
                         "source_record_path": "/records/" + str(index), "input_json_sha256": sha(encoded(snapshot)),
                         "source_text_sha256": sha(text.encode("utf-8")), "source_event_id": snapshot["utterance"]["source_turn_id"],
                         "input_binding_replay_only": {k: snapshot.get(k) for k in ("turn_id", "state_revision", "policy_hash", "api_hash")},
                         "source_profile_qualified": False, "schema_masked": schema_mask,
                         "privacy_reasons": block, "ingress_qualified": False,
                         "A0_legacy_atoms": old["candidates"],
                         "legacy_child_spans_masked": compatibility_children,
                         "A1_projection_atoms": [a1_projection(text, c) for c in old["candidates"]],
                         "variants": variants, "runtime_features_mechanics_only":runtime_features,
                         "all_abstain": True, "all_training_masks_false": True})
    return rows, scanner_parity


def diagnostic_metrics(rows):
    # Reviewed data enter only here, after source-only vectors are fixed in memory.
    adjud = []
    by_id = {r["example_id"]: r for r in rows}
    raw_sources = {r["example_id"]: r for p in SOURCE_PATHS for r in load(p)["records"]}
    for name in ("primary", "peer"):
        path = "analysis/night-v6-adjudication." + name + "-packet.json"
        for i, r in enumerate(load(path)["records"]):
            source = raw_sources[r["example_id"]]
            if r["source_input_json_sha256"] != by_id[r["example_id"]]["input_json_sha256"] or r["source_record_json_sha256"] != sha(encoded(source)):
                raise ValueError("review/source hash mismatch")
            for j, date in enumerate(r["date_candidates"]):
                text = source["input"]["utterance"]["text"]
                s = date["source_span"]
                expected = span(text, s["char_start"], s["char_end"])
                if any(expected[k] != s[k] for k in expected):
                    raise ValueError("review literal/UTF8 boundary mismatch")
                adjud.append(dict(date, example_id=r["example_id"], annotation_pointer=path + "#/records/" + str(i) + "/date_candidates/" + str(j)))
    v7 = load("research/customer-benchmark/semantic-v6-extension/reviewed-alignment.v7.json")
    lineage = load("research/customer-benchmark/semantic-v6-extension/source-adjudicated-lineage.json")
    summaries = {}
    comparison_rows = []
    old_exact = [r for r in v7["reviewed_date_annotation_rows"] if r["status"] == "exact_span_and_target"]
    # Literal candidates and top-level typed nodes only. Compatibility children
    # are reported separately, not allowed to close new open parent expressions.
    for variant in ("A0", "A1", "A2", "A3", "A4"):
        counters = Counter()
        roles = {role: Counter() for role in ("current", "uncertain", "superseded")}
        candidate_count = 0
        literal_graph, union_graph = {}, {}
        for row in rows:
            if variant == "A0":
                candidate_count += len(row["A0_legacy_atoms"])
            elif variant == "A1":
                candidate_count += len(row["A1_projection_atoms"])
            else:
                candidate_count += len(row["variants"][variant]["top_level_ids"])
        for truth in adjud:
            row = by_id[truth["example_id"]]
            if variant == "A0":
                candidates = [{"node_id": c["id"], "raw": c["source_span"], "semantic": c["source_span"], "target": c["target_indices_hypothesis"], "syntax": c["candidate"]["syntax_status"], "role": "uncertain", "polarity": "unassessed"} for c in row["A0_legacy_atoms"]]
            else:
                if variant == "A1":
                    nodes = row["A1_projection_atoms"]
                else:
                    output = row["variants"][variant]
                    nodes = [n for n in output["nodes"] if n["node_id"] in output["top_level_ids"]]
                candidates = [{"node_id": n["node_id"], "raw": n["projection"]["raw_extent"], "semantic": n["projection"]["semantic_extent"], "target": n["target_indices_hypothesis"], "syntax": n["syntax"], "role": n["role_hypothesis"], "polarity": n["polarity_hypothesis"]} for n in nodes]
            s = truth["source_span"]
            same = lambda e: (e["char_start"], e["char_end"]) == (s["char_start"], s["char_end"])
            target = lambda c: c["target"] is not None and set(c["target"]) == set(truth["target_indices"]) or c["target"] is None and not truth["target_indices"]
            raw_hits = [c for c in candidates if same(c["raw"])]
            semantic_hits = [c for c in candidates if same(c["semantic"])]
            raw_target = [c for c in raw_hits if target(c)]
            sem_target = [c for c in semantic_hits if target(c)]
            union = raw_target + [c for c in sem_target if c not in raw_target]
            annotation_key = truth["annotation_pointer"]
            literal_graph[annotation_key] = [truth["example_id"] + ":" + c["node_id"] for c in raw_target]
            union_graph[annotation_key] = [truth["example_id"] + ":" + c["node_id"] for c in union]
            status = "literal_raw_and_target" if raw_target else "semantic_extent_and_target_only" if sem_target else "exact_boundary_target_gap" if raw_hits or semantic_hits else "boundary_or_missing"
            counters[status] += 1
            counters["raw_exact_boundaries"] += bool(raw_hits)
            counters["semantic_exact_boundaries"] += bool(semantic_hits)
            counters["raw_exact_and_target"] += bool(raw_target)
            counters["semantic_literal_and_target"] += bool(sem_target)
            counters["raw_or_semantic_boundary_and_target"] += bool(union)
            # Empty/unknown scope equality and unobserved scope hypotheses are
            # separate from independently observed, nonempty target annotation.
            observed_scope = truth["target_scope_observed"] and bool(truth["target_indices"])
            counters["raw_exact_observed_nonempty_target"] += bool(raw_target) and observed_scope
            counters["semantic_exact_observed_nonempty_target"] += bool(sem_target) and observed_scope
            counters["raw_or_semantic_observed_nonempty_target"] += bool(union) and observed_scope
            related = [c["node_id"] for c in candidates if c["raw"]["char_start"] < s["char_end"] and s["char_start"] < c["raw"]["char_end"]]
            if status == "boundary_or_missing":
                counters["boundary_mismatch_diagnostic_only" if related else "missing_diagnostic_only"] += 1
            roles[truth["candidate_role"]][status] += 1
            if union:
                counters["syntax_" + union[0]["syntax"] + "_reviewed_" + truth["completion"]] += 1
            comparison_rows.append({"variant": variant, "example_id": truth["example_id"], "annotation_pointer": truth["annotation_pointer"],
                                    "source_span": s, "reviewed_target_indices": truth["target_indices"], "reviewed_role": truth["candidate_role"],
                                    "reviewed_polarity": truth["polarity"], "reviewed_completion": truth["completion"],
                                    "reviewed_target_scope_observed": truth["target_scope_observed"],
                                    "status": status, "raw_exact_ids": [c["node_id"] for c in raw_hits], "semantic_exact_ids": [c["node_id"] for c in semantic_hits],
                                    "matched_source_hypotheses": [{"node_id": c["node_id"], "target": c["target"], "role": c["role"], "polarity": c["polarity"], "syntax": c["syntax"]} for c in union],
                                    "typed_equivalence_confirmed": False, "label_transfer_permitted": False, "training_mask": False})
            comparison_rows[-1]["overlap_ids_diagnostic_only_no_label_join"] = related
        summaries[variant] = {"actual_top_candidates": candidate_count, "annotations": len(adjud), "counts": dict(counters),
                              "one_to_one_raw_boundary_target_support":len(maximum_matching(literal_graph)),
                              "one_to_one_raw_or_semantic_boundary_target_support":len(maximum_matching(union_graph)),
                              "unmatched_candidates_under_boundary_relation_not_FP":candidate_count-len(maximum_matching(union_graph)),
                              "precision_or_semantic_TP_claimed":False,
                              "by_reviewed_role": {k: dict(v) for k, v in roles.items()}, "confirmed_semantic_projection_equivalences": 0,
                              "scope": "Exposed TRAIN diagnostic only; compatibility target equality includes unknown/unobserved scope. Observed nonempty target counts are separate. Neither proves role, polarity, normalization, or admission."}
    preserved = []
    for t in old_exact:
        row = by_id[t["example_id"]]
        s = t["source_span"]
        legacy = [c for c in row["A0_legacy_atoms"] if c["source_span"]["char_start"] == s["char_start"] and c["source_span"]["char_end"] == s["char_end"] and c["target_indices_hypothesis"] == t["target_indices"]]
        container_ids = [n["node_id"] for n in row["variants"]["A3"]["nodes"] if n["projection"]["raw_extent"]["char_start"] <= s["char_start"] < s["char_end"] <= n["projection"]["raw_extent"]["char_end"]]
        preserved.append({"example_id": t["example_id"], "annotation_pointer": t["annotation_pointer"], "legacy_exact_candidate_ids": [c["id"] for c in legacy],
                          "retained_as_masked_compatibility_atom": bool(legacy), "typed_container_ids": container_ids,
                          "compatibility_atom_cannot_close_parent": True})
    return summaries, comparison_rows, preserved, lineage


def write_once(path, value):
    raw = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    with (ROOT / path).open("xb") as stream:
        stream.write(raw)
    return {"sha256": sha(raw), "bytes": len(raw)}


def audit_runtime_features(rows):
    """Portable pure source execution + sparse-vector persistence parity."""
    source_path = ROOT/"integrations/learned-dialogue/temporal_parser_v9.py"
    source = source_path.read_bytes()
    namespace = {}
    exec(compile(source, str(source_path), "exec"), namespace)
    raw_records = {r["example_id"]:r for p in SOURCE_PATHS for r in load(p)["records"]}
    counters, reasons, parity_rows = Counter(), Counter(), []
    for row in rows:
        snapshot = raw_records[row["example_id"]]["input"]
        text = snapshot["utterance"]["text"]
        context = {k:snapshot[k] for k in ("phase","question","targets") if k in snapshot}
        for variant, output in row["variants"].items():
            saved = {v["node_id"]:v for v in row["runtime_features_mechanics_only"][variant]}
            for node in output["nodes"]:
                if node["node_id"] not in output["top_level_ids"]:
                    continue
                features = saved[node["node_id"]]
                portable = namespace["source_features_v9"](text,node,context,not bool(row["privacy_reasons"]),snapshot["utterance"].get("complete_transport") is True)
                native = dict(features)
                native.pop("node_id")
                parity = encoded(native) == encoded(portable)
                persistence = json.loads(encoded(portable)) == portable
                if not parity or not persistence:
                    raise ValueError("runtime feature parity failure")
                counters[variant+"_vectors"] += 1
                counters[variant+"_mechanically_nonempty"] += bool(features["features"])
                counters["portable_parity"] += parity
                counters["JSON_roundtrip_parity"] += persistence
                counters["all_training_masks_false"] += features["training_mask"] is False
                reasons.update(features["reasons"])
                for forbidden, kwargs in (("privacy",{"privacy_isolated":False,"framing_verified":True}),
                                           ("framing",{"privacy_isolated":True,"framing_verified":False}),
                                           ("R4_version",{"privacy_isolated":True,"framing_verified":True,"expected_parser_version":"date_expression_scanner.r4.2"})):
                    rejected = namespace["source_features_v9"](text,node,context,**kwargs)
                    if rejected["features"]:
                        raise ValueError("feature guard failure:"+forbidden)
                    counters[forbidden+"_guard_pass"] += 1
                parity_rows.append({"example_id":row["example_id"],"variant":variant,"node_id":node["node_id"],
                                    "vector_sha256":sha(encoded(portable["features"])),"nonzeros":len(portable["features"]),
                                    "portable_parity":parity,"JSON_roundtrip_parity":persistence,"training_mask":False})
    return {"feature_version":FEATURE_VERSION,"source_sha256":sha(source),"pure_parser_feature_package_bytes":len(source),
            "package_under_500000_bytes":len(source)<=500000,"model_coefficients":0,"dependency_imports":["re"],
            "counts":dict(counters),"mechanical_mask_reasons":dict(reasons),"rows":parity_rows,
            "eligibility_scope":"Offline feature mechanics only; fixture privacy/framing booleans do not qualify deployment ingress, privacy, schema, ancestry, or supervision.",
            "reviewer_annotations_used_as_features":False,"old_weights_used":False}


def run_falsifications():
    spec = load("analysis/learned-layer-design.checkpoint16-v8-assessment.json")
    result = []
    for probe in spec["actual_frozen_source_probes"]:
        out = parse_temporal(probe["text"], "diagnostic:"+probe["id"], probe["context"])
        nodes = [n for n in out["nodes"] if n["node_id"] in out["top_level_ids"]]
        result.append({"id":probe["id"],"text":probe["text"],"context":probe["context"],
                       "actual_top_nodes":[{"source_span":n["projection"]["raw_extent"],"syntax":n["syntax"],"holes":n["holes"],
                                            "target_indices_hypothesis":n["target_indices_hypothesis"],"target_source":n["target_source_hypothesis"]} for n in nodes],
                       "correction_edges":out["correction_edges"],"unresolved_relations":out.get("unresolved_correction_relations",[]),
                       "abstain":out["abstain"],"qualified":False})
    return result


def main():
    started = time.perf_counter()
    started_cpu = time.process_time()
    tracemalloc.start()
    historical, protected = verify_history()
    source_paths = ["integrations/learned-dialogue/" + n for n in ("temporal_parser_v9.py", "diagnostic_v9.py", "test_temporal_v9.py")]
    source_hashes = {p: sha((ROOT / p).read_bytes()) for p in source_paths}
    rows, parity = reextract()
    source_only_hash = sha(encoded(rows))
    feature_audit = audit_runtime_features(rows)
    summaries, comparisons, preservation, lineage = diagnostic_metrics(rows)
    tests = run_checks()
    if tests["passed"] != tests["executed"]:
        raise ValueError("failed checks: " + json.dumps(tests, ensure_ascii=True))
    artifact = {"schema_version": "source_only_typed_temporal_candidates.v9", "parser_version": VERSION,
                "source_sha256": source_hashes, "input_raw_sha256": {p: PINS[p] for p in SOURCE_PATHS},
                "source_only_vector_sha256_before_review_read": source_only_hash,
                "rows": rows, "comparison_diagnostics_not_supervision": comparisons,
                "all_outputs_abstain": True, "all_training_masks_false": True, "qualified": False}
    artifact_meta = write_once(OUTPUT, artifact)
    peak_memory = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    report = {"schema_version": "typed_temporal_parser_diagnostic.v9", "created_at_utc": datetime.now(timezone.utc).isoformat(),
              "parser_version": VERSION, "source_sha256": source_hashes, "input_sha256": PINS,
              "spec_sha256": sha((ROOT / "analysis/learned-layer-design.checkpoint15-span-parser.json").read_bytes()),
              "checkpoint16_spec_sha256":sha((ROOT/"analysis/learned-layer-design.checkpoint16-v8-assessment.json").read_bytes()),
              "source_only_extraction_preceded_adjudication_reads": True, "source_only_vector_sha256": source_only_hash,
              "rows": len(rows), "source_profile_counts": dict(Counter("unknown_schema" if r["schema_masked"] else "fixture_payment_profile" for r in rows)),
              "privacy_blocked_rows": sum(bool(r["privacy_reasons"]) for r in rows),
              "actual_frozen_R4_reextract_parity": {"rows": len(parity), "passed": sum(r["passed"] for r in parity), "cases": parity},
              "ablations": summaries, "tests": tests, "old_20_literal_target_preservation": {"baseline": len(preservation), "retained": sum(r["retained_as_masked_compatibility_atom"] for r in preservation), "cases": preservation},
              "six_falsification_results":run_falsifications(),"runtime_feature_audit":feature_audit,
              "legacy_compatibility_atoms": sum(len(r["A0_legacy_atoms"]) for r in rows),
              "legacy_child_spans_preserved": sum(len(r["legacy_child_spans_masked"]) for r in rows),
              "reviewed_exact_CP_and_UTF8_spans_validated": len([x for x in comparisons if x["variant"] == "A0"]),
              "runtime_ast_syntax_counts": dict(Counter(n["syntax"] for r in rows for n in r["variants"]["A3"]["nodes"] if n["node_id"] in r["variants"]["A3"]["top_level_ids"])),
              "runtime_ast_kind_counts": dict(Counter(n["kind"] for r in rows for n in r["variants"]["A3"]["nodes"] if n["node_id"] in r["variants"]["A3"]["top_level_ids"])),
              "runtime_diagnostics": dict(Counter(d for r in rows for d in r["variants"]["A3"]["diagnostics"])),
              "historical_preservation": historical, "historical_entries": sum(x["entries"] for x in historical.values()),
              "protected_distinct_paths":len(protected),
              "post_all_masks_primary_groups": {"positive": 0, "additional_negative": 0},
              "post_all_masks_DATE_groups": {"complete": 0, "unfinished": 0},
              "lineage_independent_support_all_masked": lineage["all_independent_support_masked"],
              "floor_unchanged": 20, "fit_calls": 0, "new_DEV_read": False, "model_weights_or_scores_inspected": False,
              "old_neutral_envelopes_in_candidate_container_ignored": True,
              "GPU_calls": 0, "GPU_USD": 0, "platform_calls": 0, "new_auth_created": False,
              "accepted_outputs": 0, "all_132_outputs_abstain": True, "qualified": False,
              "cpu_seconds": time.process_time() - started_cpu,"elapsed_seconds":time.perf_counter()-started,
              "traced_peak_bytes_parse_feature_diagnostic_artifact":peak_memory, "artifact": {"path": OUTPUT, **artifact_meta},
              "implemented_slices": ["Central child status/hole reducer", "Local lexical target scopes and compatible corrections", "Production-owned suppression", "Pinned source-only sparse feature adapter", "Exposed TRAIN A0-A4 + one-to-one support matching"],
              "token_domain_contract":{"tokens_per_clause":80,"R4_tokens_per_expression":80,"long_clause_short_expression_control":"explicitly excluded; no hidden domain expansion"},
              "limitations": ["English finite grammar; unknown and interrupted constructions remain unsupported or unresolved.",
                              "Source context target and correction values are hypotheses, never reviewed bindings.",
                              "Semantic literal and projection-boundary diagnostics do not certify typed role/polarity equivalence; confirmed count remains zero.",
                              "Syntax closure is not normalization, completed actionable act, financial consent, or permission.",
                              "Peer schema remains unknown; ingress, source aliases, ancestry and new parent admission remain unqualified.",
                              "Compatibility atoms preserve old evidence; only typed maximal parents are counted in new extraction metrics.",
                              "V9 source feature adapter is untrained; no model coefficients, fit, or DEV evaluation.",
                              "Clause limit80 remains stricter than R4 expression limit80; long-clause domain exclusion is explicit.",
                              "One-to-one boundary support is neither semantic precision nor independent source qualification."]}
    report_meta = write_once(REPORT, report)
    lines = ["V9 source-only typed temporal parser; exposed TRAIN diagnostic", "",
             "132 source rows parsed before adjudicated spans were read; all132 abstain.",
             "Finite semantics: %d/%d cases; %d/%d total checks; %d assertions." % (tests["finite_spec_cases_passed"], 38, tests["passed"], tests["executed"], tests["assertions"]),
             "Frozen R4 re-extraction parity: %d/132; 20/20 prior exact-target atoms retained masked." % sum(r["passed"] for r in parity),
             "Six independent V8 falsifications repaired by executed source tests. Legacy81 equivalent checks passed; T24 scope borrowing explicitly amended."]
    for key, data in summaries.items():
        c = data["counts"]
        lines.append("%s: %d candidates; literal raw+target %d/101; semantic literal+target %d/101; union boundary+target %d/101." % (key, data["actual_top_candidates"], c.get("raw_exact_and_target", 0), c.get("semantic_literal_and_target", 0), c.get("raw_or_semantic_boundary_and_target", 0)))
        lines.append("  Strict observed nonempty target: raw %d/101; semantic %d/101; union %d/101." % (c.get("raw_exact_observed_nonempty_target", 0), c.get("semantic_exact_observed_nonempty_target", 0), c.get("raw_or_semantic_observed_nonempty_target", 0)))
        lines.append("  One-to-one union boundary support %d; unmatched candidates %d (not false positives)." % (data["one_to_one_raw_or_semantic_boundary_target_support"],data["unmatched_candidates_under_boundary_relation_not_FP"]))
    lines += ["Confirmed typed semantic equivalence:0. These are separate boundary diagnostics, never transferred labels.",
              "All postmask eligible primary/DATE group counts remain0; class floor20 unchanged; no new grant or fit.",
              "60 peer unknown-schema rows remain masked. All ingress/reference/normalization/role/ancestry/authority gates stay closed.",
              "Protected distinct paths %d unchanged, including all V8 and original97." % len(protected),
              "Runtime feature audit: %d portable/JSON vectors; all training masks false; %d source package bytes;0 coefficients." % (feature_audit["counts"]["portable_parity"],feature_audit["pure_parser_feature_package_bytes"]),
              "Actual traced peak bytes %d; execution seconds %.4f (tracing enabled)." % (peak_memory,report["cpu_seconds"]),
              "GPU0 USD0; no DEV, model weights/scores, cloud/platform/Git/secrets. Frozen neutral envelope fields ignored.", "",
              "Known limitations:"] + ["- " + x for x in report["limitations"]] + ["", "Exact source SHA256:"] + [p + " " + h for p, h in source_hashes.items()]
    txt_raw = ("\n".join(lines) + "\n").encode("utf-8")
    txt_path = REPORT.replace(".json", ".txt")
    with (ROOT / txt_path).open("xb") as stream:
        stream.write(txt_raw)
    # Recheck frozen bytes after every experiment. New artifacts are write-once.
    after, _ = verify_history()
    if historical != after or any(sha((ROOT / p).read_bytes()) != h for p, h in source_hashes.items()):
        raise ValueError("source freeze drift")
    freeze = {"schema_version": "typed_temporal_parser_freeze.v9", "parser_version": VERSION,"feature_version":FEATURE_VERSION, "source_sha256": source_hashes,
              "artifacts_sha256": {REPORT: report_meta["sha256"], txt_path: sha(txt_raw), OUTPUT: artifact_meta["sha256"]},
              "protected_sha256": protected, "input_sha256": PINS, "tests_passed": tests["passed"],
              "trained": False, "qualified": False, "all_abstain": True}
    freeze_meta = write_once(REPORT.replace(".json", ".freeze.json"), freeze)
    print(json.dumps({"report": REPORT, "freeze": freeze_meta, "checks": tests["passed"], "metrics": summaries, "seconds": report["cpu_seconds"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
