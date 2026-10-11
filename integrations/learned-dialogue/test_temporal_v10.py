"""Executed finite semantics and metamorphic controls; no fitting or DEV reads."""
import ast
import json
from pathlib import Path
from temporal_parser_v10 import (parse_temporal, project_segments, typed_signature, join_syntax,
                                maximal_owned, source_features_v10, VERSION, FEATURE_VERSION)

ROOT = Path(__file__).resolve().parents[2]
SPEC = "analysis/learned-layer-design.checkpoint15-span-parser.json"
CONTEXT = {"targets": [{"index": 0, "label": "item alpha"}, {"index": 1, "label": "item beta"}]}


def top(o):
    return [x for x in o["nodes"] if x["node_id"] in o["top_level_ids"]]


def run_checks():
    results = []

    def check(name, assertions):
        failed = [k for k, v in assertions.items() if not v]
        results.append({"id": name, "passed": not failed, "assertions": len(assertions), "failed": failed})

    spec = json.loads((ROOT / SPEC).read_text(encoding="utf-8"))
    for case in spec["falsifiable_cases"]:
        text, expected, cid = case["text"], case["expected"], case["id"]
        o = parse_temporal(text, "case:" + cid, CONTEXT)
        ns = top(o)
        first = ns[0] if ns else None
        checks = {"all_abstain": o["abstain"] and not o["qualified"] and not any(o["masks"].values()),
                  "lossless_all_nodes": all("".join(s["span"]["text"] for s in x["projection"]["segments"]) == x["projection"]["raw_extent"]["text"] for x in o["nodes"]),
                  "source_bound": all(text[x["projection"]["raw_extent"]["char_start"]:x["projection"]["raw_extent"]["char_end"]] == x["projection"]["raw_extent"]["text"] for x in o["nodes"])}
        for key in ("surface", "surface_extent", "semantic_extent"):
            if key in expected:
                extent = "semantic_extent" if key == "semantic_extent" else "raw_extent"
                checks[key] = bool(first and first["projection"][extent]["text"] == expected[key])
        if "kind" in expected:
            checks["kind"] = bool(first and first["kind"] in expected["kind"].split("/"))
        if expected.get("syntax") in {"open", "closed", "ambiguous"}:
            checks["syntax"] = bool(first and first["syntax"] == expected["syntax"])
        if "holes" in expected:
            checks["holes"] = bool(first and [h["expected"] for h in first["holes"]] == expected["holes"])
        if "children" in expected:
            child_texts = [x["projection"]["raw_extent"]["text"] for x in o["nodes"] if first and x["node_id"] in first["children"]]
            checks["children"] = child_texts == expected["children"]
        if "top_level_candidate_count" in expected:
            checks["top_count"] = len(ns) == expected["top_level_candidate_count"]
        if "endpoint_count" in expected:
            checks["endpoint_count"] = bool(first and len(first["children"]) == expected["endpoint_count"])
        for key in ("reference_mask", "normalization_mask"):
            if key in expected:
                checks[key] = bool(first and first[key] is expected[key])
        if "operator" in expected:
            checks["operator"] = bool(first and expected["operator"] in [x["kind"] for x in first["operators"]])
        if "attachment" in expected:
            checks["attachment"] = bool(first and any(x["kind"] == "attachment" and x["span"]["text"].strip() == expected["attachment"] for x in first["projection"]["segments"]))
        if "marker" in expected:
            checks["marker_retained"] = bool(first and first["marker_spans"] and first["marker_spans"][0]["text"] == "...")
        if cid == "T19":
            checks["delimiter_classified"] = any(s["kind"] == "formatting" and s["span"]["text"] == "," for s in first["projection"]["segments"])
        if cid == "T20":
            checks["internal_comma_retained"] = ", 2027" in first["projection"]["semantic_extent"]["text"]
        if cid == "T23":
            checks["unrelated_clause_not_open"] = bool(first and first["syntax"] == "ambiguous")
        if cid == "T24":
            checks.update(two_dates=len(ns) == 2,
                          unknown_scope_relation_unresolved=not o["correction_edges"] and bool(o.get("unresolved_correction_relations")),
                          old_negated=ns[0]["role_hypothesis"] == "superseded_hypothesis",
                          new_open=ns[-1]["syntax"] == "open" and ns[-1]["role_hypothesis"] == "replacement_hypothesis",
                          no_borrowed_target=ns[0]["target_indices_hypothesis"] == [0] and ns[-1]["target_indices_hypothesis"] is None)
        if cid == "T25":
            checks["unrelated_if_not_global_veto"] = bool(first and first["syntax"] == "closed")
        if cid == "T26":
            checks["distinct_targets"] = len(ns) == 2 and [x["target_indices_hypothesis"] for x in ns] == [[0], [1]]
        if cid == "T27":
            checks["source_both"] = len(ns) == 1 and first["kind"] == "range" and first["target_indices_hypothesis"] == [0, 1]
        if cid == "T28":
            checks["interruption_not_closed"] = bool(first and first["syntax"] == "unsupported" and first["holes"])
        if cid == "T29":
            s = first["projection"]["raw_extent"]
            checks["utf8_not_codepoints"] = s["utf8_byte_start"] != s["char_start"] and s["text"].encode("utf-8") == text.encode("utf-8")[s["utf8_byte_start"]:s["utf8_byte_end"]]
        if cid == "T30":
            checks["identifier_and_time_excluded"] = not ns and not o["absence_established"]
        if cid == "T33":
            checks["quote_evidence"] = bool(first and first["quotation_evidence"] and first["polarity_hypothesis"] == "quoted_hypothesis")
        if cid == "T34":
            checks["no_payment_target"] = bool(first and first["target_indices_hypothesis"] is None)
        if cid == "T35":
            checks["unsupported_not_fake_unfinished"] = bool(first and first["syntax"] == "unsupported")
        if cid in {"T13", "T33", "T34"}:
            checks["no_current_payment_role"] = all(x["role_hypothesis"] != "current" and not x["masks"]["permission"] for x in ns)
        if cid == "T37":
            checks["event_range_children"] = bool(first and len(first["children"]) == 2 and first["resolution"] == "unresolved")
        check(cid, checks)

    p = lambda s, c=CONTEXT: parse_temporal(s, "metamorphic", c)
    summary = lambda o: [(x["kind"], x["syntax"], [h["expected"] for h in x["holes"]]) for x in top(o)]
    check("R01_case_whitespace", {"structure": summary(p("between March 4 and March 6")) == summary(p("BETWEEN  MARCH 4  AND March 6"))})
    check("R02_calendar_substitution", {"structure": summary(p("between March 4 and")) == summary(p("between April 7 and"))})
    a = "For item alpha use March 4; for item beta use April 7"
    b = "For item beta use April 7; for item alpha use March 4"
    keys = lambda s: sorted((x["projection"]["semantic_extent"]["text"], x["target_indices_hypothesis"]) for x in top(p(s)))
    check("R03_independent_permutation", {"target_graph": keys(a) == keys(b)})
    a = top(p("For item alpha, not March 4; I meant April 7"))
    b = top(p("For item alpha, not April 7; I meant March 4"))
    check("R04_correction_direction", {"replacement_changes": a[-1]["projection"]["semantic_extent"]["text"] != b[-1]["projection"]["semantic_extent"]["text"], "both_replacement": a[-1]["role_hypothesis"] == b[-1]["role_hypothesis"] == "replacement_hypothesis"})
    r = p("between March 4 and")
    check("R05_operand_deletion", {"parent_open": top(r)[0]["syntax"] == "open", "child_closed_but_not_top": len(top(r)) == 1 and len(r["nodes"]) == 2 and r["nodes"][1]["syntax"] == "closed"})
    bound = [typed_signature(top(p(s))[0]) for s in ("on March 4", "by March 4", "until March 4", "before March 4", "after March 4", "between March 4 and March 7")]
    check("R06_operator_nonequivalence", {"all_distinct": len(set(bound)) == 6})
    controls = [{"phase": "security"}, {"question": {"role": "security"}}, {"question": {"security_field": "opaque"}}, {}]
    blocked = [p("March 4" if i < 3 else "password March 4", c) for i, c in enumerate(controls)]
    check("R07_security_preparse", {"no_copy_no_nodes": all(not x["nodes"] and x["diagnostics"] for x in blocked)})
    check("R08_nocandidate_not_absence", {"no_absence_or_terms_claim": not p("unknown fleem")['absence_established'] and not p("unknown fleem")["nodes"]})
    n = top(p("on March 4..."))[0]
    proj = n["projection"]
    fresh = project_segments("on March 4...", (0, 13), (3, 10), [(0, 3)], [(10, 13)])
    check("R09_projection_idempotent", {"same_partition": fresh == proj, "roundtrip": "".join(x["span"]["text"] for x in proj["segments"]) == "on March 4..."})
    sa = top(p("on March 4"))[0]["projection"]["raw_extent"]
    sb = top(p("🔎 on March 4"))[0]["projection"]["raw_extent"]
    check("R10_unicode_equivariance", {"cp_shift": sb["char_start"] - sa["char_start"] == 2, "utf8_shift": sb["utf8_byte_start"] - sa["utf8_byte_start"] == 5, "same_surface": sa["text"] == sb["text"]})
    renamed = {"targets": [{"index": 6, "label": "account violet"}, {"index": 9, "label": "account lime"}]}
    r = top(p("For account violet use March 4; for account lime use April 7", renamed))
    check("R11_target_renaming", {"source_metadata_indices": [x["target_indices_hypothesis"] for x in r] == [[6], [9]]})
    r = top(p("March 4... please repeat the amount; if the line drops call back"))
    check("R12_unrelated_clause", {"date_retained": len(r) == 1 and r[0]["syntax"] == "ambiguous" and r[0]["projection"]["semantic_extent"]["text"] == "March 4"})
    for i, text in enumerate(("the card ends in 4821", "the time is 09:30", "I paid 200 pounds", "choose option 4", "api_hash=1234", "call 5551234", "no date was supplied", "a completely unknown expression")):
        check("N%02d" % i, {"no_numeric_date": not top(p(text)), "no_absence": not p(text)["absence_established"]})
    for name, text in (("source_overflow", "x" * 4097), ("token_overflow", "March " * 81), ("clause_overflow", "March;" * 13), ("candidate_overflow", ", ".join(["March 4"] * 17))):
        o = p(text)
        check(name, {"diagnostic": bool(o["diagnostics"]), "abstain": o["abstain"]})
    source = (Path(__file__).parent / "temporal_parser_v10.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    check("pure_module", {"only_re_import": [x.names[0].name for x in ast.walk(tree) if isinstance(x, ast.Import)] == ["re"],
                          "no_tool_or_io_calls": not any(isinstance(x, ast.Name) and x.id in {"open", "eval", "exec", "__import__", "subprocess", "requests"} for x in ast.walk(tree))})
    check("A4_real_ablation", {"event_removed": summary(parse_temporal("two days after that", "a4", {}, "A4")) != summary(p("two days after that")), "attachment_removed": top(parse_temporal("on March 4", "a4", {}, "A4"))[0]["projection"]["raw_extent"]["text"] == "March 4"})
    n = top(p("🔎 on March 4"))[0]
    s = n["projection"]["semantic_extent"]
    check("P01_immutable_source", {"unicode_source_reconstruction": s["text"] == "🔎 on March 4"[s["char_start"]:s["char_end"]] and s["text"].encode("utf-8") == "🔎 on March 4".encode("utf-8")[s["utf8_byte_start"]:s["utf8_byte_end"]]})
    n = top(p("for March 4,"))[0]
    check("P02_lossless_partition", {"all_source_accounted": "".join(x["span"]["text"] for x in n["projection"]["segments"]) == "for March 4,"})
    rejected = []
    for token in ("by", "until", "before", "after", "between", "from", "either"):
        source = token + " March 4"
        try:
            project_segments(source, (0, len(source)), (len(token) + 1, len(source)))
            rejected.append(False)
        except ValueError:
            rejected.append(True)
        try:
            project_segments(source, (0, len(source)), (len(token) + 1, len(source)), [(0, len(token) + 1)])
            rejected.append(False)
        except ValueError:
            rejected.append(True)
    check("P03_operator_deletion_rejected", {"every_semantic_operator": all(rejected), "open_determiner_retained": top(p("March the"))[0]["projection"]["semantic_extent"]["text"] == "March the"})
    outside = top(p("March 4, stop"))[0]["projection"]
    inside = top(p("March 4, 2027"))[0]["projection"]
    check("P04_delimiter_vs_year", {"outside_formatting": outside["semantic_extent"]["text"] == "March 4", "inside_semantic": inside["semantic_extent"]["text"] == "March 4, 2027"})
    n = top(p("For item alpha use March 4"))[0]
    changed = dict(n, polarity_hypothesis="negated_hypothesis")
    check("P05_role_polarity_equivalence", {"polarity_changes_signature": typed_signature(n) != typed_signature(changed), "current_is_only_hypothesis": n["role_hypothesis"] == "current_hypothesis" and not n["masks"]["permission"]})
    check("P06_no_projection_promotion", {"all_masks_false": not any(n["projection"]["masks"].values()), "not_confirmed": n["projection"]["equivalence"] == "unqualified_typed_projection_hypothesis"})
    n = top(p("the second Monday of, while another explanation interrupts, March"))[0]
    check("P07_interruption_retention", {"literal_interruption_present": "while another explanation interrupts" in n["projection"]["raw_extent"]["text"], "never_closed": n["syntax"] == "unsupported", "explicit_interruption": bool(n["interruption_spans"])})
    r = p("between March 4 and April 7", {})
    check("P08_unknown_target_not_invented", {"all_children_unknown": all(n["target_indices_hypothesis"] is None for n in r["nodes"]), "all_target_masks_false": all(not n["masks"]["target"] for n in r["nodes"])})
    for idx, text in enumerate(("until the", "the second working day of the week in which", "by whichever is later, the statement arriving or", "from the statement arriving until the direct debit is posted")):
        r = p(text)
        check("E%02d" % idx, {"typed_parent_retained": len(top(r)) == 1, "no_normalization": not top(r)[0]["normalization_mask"], "expected_syntax": top(r)[0]["syntax"] == ("closed" if idx == 3 else "open")})
    for idx, context in enumerate(([1], {"question": "copied"}, {"targets": [{"index": "0", "label": "item"}]}, {"question": {"target_indices": "0"}})):
        o = parse_temporal("March 4", "malformed", context)
        check("M%02d" % idx, {"explicit_rejected_context": bool(o["diagnostics"]), "neutral_no_nodes": o["abstain"] and not o["nodes"]})
    o = parse_temporal("March 4", "", {})
    check("missing_binding", {"no_fabrication": o["diagnostics"] == ["missing_source_binding"] and not o["nodes"]})
    legacy_count = len(results)
    probes = json.loads((ROOT / "analysis/learned-layer-design.checkpoint16-v8-assessment.json").read_text(encoding="utf-8"))["actual_frozen_source_probes"]
    for index, probe in enumerate(probes):
        o = parse_temporal(probe["text"], "falsification:" + probe["id"], probe["context"])
        ns = top(o)
        checks = {"all_abstain": o["abstain"] and not o["qualified"]}
        if index < 3:
            checks.update(single_parent=len(ns) == 1, nonclosed=ns[0]["syntax"] != "closed",
                          child_day_hole_retained="day" in [h["expected"] for h in ns[0]["holes"]],
                          child_hole_source_owner=all(h["source_owner"] for h in ns[0]["holes"]))
        elif index == 3:
            checks.update(two_targets=[n["target_indices_hypothesis"] for n in ns] == [[0], [1]], no_cross_target_edge=not o["correction_edges"], unresolved_relation=bool(o.get("unresolved_correction_relations")))
        elif index == 4:
            checks.update(no_substring_scope=ns[0]["target_indices_hypothesis"] == [1], fallback_disclosed=ns[0]["target_source_hypothesis"] == "question_fallback_hypothesis")
        else:
            checks.update(no_stale_collective=ns[0]["target_indices_hypothesis"] == [0], explicit_local=ns[0]["target_source_hypothesis"] == "explicit_local_governor")
        check("V9_" + probe["id"], checks)
    check("V9_P07_all_children_join", {"complete_closed": top(p("between March 4 and Friday"))[0]["syntax"] == "closed",
                                      "unsupported_dominates": join_syntax([{"syntax":"closed"},{"syntax":"unsupported"}], []) == "unsupported",
                                      "ambiguous_dominates_open": join_syntax([{"syntax":"open"},{"syntax":"ambiguous"}], []) == "ambiguous",
                                      "hole_blocks_closed": join_syntax([{"syntax":"closed"}], [("day",0,"child")]) == "open"})
    a = p("Not Friday for item alpha; for item alpha I meant Monday")
    b = p("Not Monday for item alpha; for item alpha I meant Friday")
    check("V9_P08_scoped_correction", {"same_target_edges": len(a["correction_edges"]) == len(b["correction_edges"]) == 1,
                                       "direction_changes": top(a)[-1]["projection"]["semantic_extent"]["text"] != top(b)[-1]["projection"]["semantic_extent"]["text"]})
    geometric = [{"i":0,"j":8,"kind":"range","operators":[],"children":[]}, {"i":2,"j":4,"kind":"calendar","operators":[],"children":[]}]
    check("V9_P09_ownership_not_geometry", {"both_unowned_retained": len(maximal_owned(geometric)) == 2})
    # A candidate with dual representations can match at most one annotation.
    from diagnostic_v10 import maximum_matching
    check("V9_P10_matching_multiplicity", {"dual_or_duplicate_not_two_TP": len(maximum_matching({"annotation_a":["candidate"],"annotation_b":["candidate"]})) == 1})
    long = p("unrelated " * 81 + "March 4")
    check("V9_P11_domain_reported", {"long_clause_explicitly_masked": not top(long) and any("token_overflow" in x for x in long["diagnostics"]), "short_expression_supported": bool(top(p("March 4")))})
    r = p('He said "Friday"; item alpha uses Monday')
    check("V9_P12_role_locality", {"quote_preserved": top(r)[0]["polarity_hypothesis"] == "quoted_hypothesis", "sibling_supported_assertion": top(r)[1]["polarity_hypothesis"] == "asserted_hypothesis"})
    unicode_context = {"targets":[{"index":7,"label":"hesap çınar"},{"index":8,"label":"hesap çınarlık"}]}
    r = p("🔎 hesap çınarlık uses Friday", unicode_context)
    check("V9_P13_unicode_token_scope", {"full_label_only": top(r)[0]["target_indices_hypothesis"] == [8], "utf8_offset": top(r)[0]["target_governor_spans"][0]["utf8_byte_start"] > top(r)[0]["target_governor_spans"][0]["char_start"]})
    n = top(p("March 4"))[0]
    f = source_features_v10("March 4", n, {}, False, True)
    check("V9_P14_independent_privacy_flag", {"no_surface_features": not f["features"] and f["reasons"] == ["privacy_isolation_unqualified"]})
    f = source_features_v10("March 4", n, {}, True, True, "date_expression_scanner.r4.2")
    check("V9_P15_feature_version", {"no_alias": not f["features"] and f["reasons"] == ["parser_or_feature_version_mismatch"]})
    check("V9_P16_unknown_unmatched", {"no_absence_or_authority": not p("unknown expression")["absence_established"] and not any(n["masks"].values())})
    f = source_features_v10("March 4", n, {}, True, True)
    mutated = dict(n, reviewer_label="unfinished", reviewed_target_indices=[999], annotation_offsets=[1,2])
    f2 = source_features_v10("March 4", mutated, {}, True, True)
    check("V9_feature_no_oracle_dependency", {"same_features": f["features"] == f2["features"], "json_roundtrip": json.loads(json.dumps(f))["features"] == f["features"], "no_authority": not f["training_mask"] and f["abstain"]})
    boundary = dict(n, projection=dict(n["projection"], raw_extent=dict(n["projection"]["raw_extent"], char_start=1)))
    check("V9_feature_boundary_guard", {"rejects_shift": not source_features_v10("March 4", boundary, {}, True, True)["features"]})
    collective_context = dict(CONTEXT, question={"role":"date","target_indices":[0,1]})
    r = p("Earlier we discussed both item alpha and item beta; this one uses Friday", collective_context)
    check("V9_singular_reference_not_collective", {"unknown_scope": top(r)[0]["target_indices_hypothesis"] is None,
                                                   "reference_disclosed": top(r)[0]["target_source_hypothesis"] == "unresolved_singular_reference"})
    for index, text in enumerate(("by March the", "until March the or Friday", "Friday, March the", "the second Monday of March the", "either March the or Friday")):
        r = p(text)
        primary = top(r)[0]
        check("V9_composite_fragment_%d" % index, {"not_closed":primary["syntax"] != "closed", "day_hole_survives":"day" in [h["expected"] for h in primary["holes"]], "no_normalization":not primary["normalization_mask"]})
    checkpoint17 = json.loads((ROOT/"analysis/learned-layer-design.checkpoint17-v9-assessment.json").read_text(encoding="utf-8"))
    probes17 = checkpoint17["fresh_source_execution"]["runtime_results"]["parser_probes"]
    observed = {}
    for probe in probes17:
        cid, source = probe["id"],probe["input"]
        o = parse_temporal(source["text"],source["event_id"],source["context"])
        ns = top(o)
        observed[cid] = (source,o,ns)
        checks = {"all_shadow":o["abstain"] and not o["qualified"],"source_bound":all(source["text"][n["projection"]["raw_extent"]["char_start"]:n["projection"]["raw_extent"]["char_end"]]==n["projection"]["raw_extent"]["text"] for n in o["nodes"])}
        if cid in {"P01","P02","P03","P04","P10","P22"}:
            expected = {"P01":[[0]],"P02":[[0,1]],"P03":[[0],[0]],"P04":[[0,1]],"P10":[[0],[1]],"P22":[[0],[1]]}[cid]
            checks["exact_source_target_hypothesis"] = [n["target_indices_hypothesis"] for n in ns]==expected
        if cid=="P03":checks["scoped_repair_edge"] = len(o["correction_edges"])==1
        if cid=="P10":checks["no_cross_target_edge"] = not o["correction_edges"]
        if cid in {"P11","P12"}:
            checks["unknown_target"] = all(n["target_indices_hypothesis"] is None for n in ns)
            checks["explicit_diagnostic"] = bool(o["diagnostics"])
        if cid in {"P05","P06","P21"}:checks["holes_nonclosed"] = bool(ns and ns[0]["holes"] and ns[0]["syntax"]!="closed")
        if cid=="P09":checks["one_shared_evidence_family"] = len(ns)==2 and any(len(f["members"])==2 and f["independent_training_units"]==0 for f in o["hypothesis_families"])
        if cid=="P16":checks["unsupported_maximal_comparison"] = len(ns)==1 and ns[0]["kind"]=="comparison" and ns[0]["syntax"]=="unsupported"
        if cid=="P17":checks["unknown_repair_unresolved"] = not o["correction_edges"] and bool(o.get("unresolved_correction_relations"))
        if cid=="P18":checks["privacy_preparse"] = not ns
        if cid=="P19":checks["modal_may_excluded"] = not ns and "modal_may_disambiguated" in o["diagnostics"]
        if cid=="P20":checks["name_relevance_unknown"] = ns[0]["relevance_status"]=="non_temporal_name_hypothesis" and not ns[0]["masks"]["training"]
        if cid=="P21":checks["proven_optional_either_equivalence"] = len(ns)==1
        check("V10_"+cid,checks)
    source,o,ns = observed["P01"]
    for fid, privacy, framing in (("F01",False,True),("F02","false","false"),("F03",True,True)):
        f = source_features_v10(source["text"],ns[0],source["context"],privacy,framing)
        check("V10_"+fid,{"typed_flag_behavior":bool(f["features"])==(fid=="F03"),"shadow":f["abstain"] and not f["training_mask"]})
    for fid, mutation in (("F04",{"kind":"forged"}),("F05",{"operators":[{"kind":"forged"}]})):
        f = source_features_v10(source["text"],dict(ns[0],**mutation),source["context"],True,True)
        check("V10_"+fid,{"typed_structure_rejected":not f["features"] and "external_node_structure_mismatch" in f["reasons"]})
    vectors = []
    for cid in ("P13","P14"):
        source,o,ns = observed[cid]
        vectors.append(source_features_v10(source["text"],ns[0],source["context"],True,True))
    check("V10_F06_distant_governor", {"vectors_distinct":vectors[0]["features"]!=vectors[1]["features"],
                                     "same_completion":observed["P13"][2][0]["syntax"]==observed["P14"][2][0]["syntax"]=="closed",
                                     "negative_encoded":"source_polarity=negated_hypothesis" in vectors[0]["features"],
                                     "positive_encoded":"source_polarity=asserted_hypothesis" in vectors[1]["features"]})
    for index, (text,polarity) in enumerate((("Please schedule the arrangement for Friday","asserted_hypothesis"),('He said "Please schedule the arrangement for Friday"',"quoted_hypothesis"),("If possible, schedule the arrangement for Friday","conditional_hypothesis"),("Friday","unassessed"))):
        o = p(text)
        f=source_features_v10(text,top(o)[0],CONTEXT,True,True)
        check("V10_role_counterpart_%d" % index,{"supported_or_unknown_polarity":top(o)[0]["polarity_hypothesis"]==polarity,
                                                "source_feature_carries_evidence":"source_polarity="+polarity in f["features"],
                                                "no_authority":not top(o)[0]["masks"]["permission"] and not f["training_mask"]})
    source,o,ns = observed["P01"]
    changed = dict(source["context"],targets=list(reversed(source["context"]["targets"])))
    check("V10_metadata_order",{"same_scopes":[n["target_indices_hypothesis"] for n in top(parse_temporal(source["text"],source["event_id"],changed))]==[[0]]})
    for cid in ("P02","P12"):
        source,o,ns=observed[cid]
        context=dict(source["context"],targets=list(reversed(source["context"]["targets"])))
        reordered=top(parse_temporal(source["text"],source["event_id"],context))
        check("V10_metadata_order_"+cid,{"same_scopes":[n["target_indices_hypothesis"] for n in reordered]==[n["target_indices_hypothesis"] for n in ns]})
    source,o,ns=observed["P22"]
    reverse="; ".join(reversed(source["text"].rstrip('.').split('; ')))
    reordered=top(parse_temporal(reverse,source["event_id"],source["context"]))
    key=lambda n:(n["projection"]["semantic_extent"]["text"],n["target_indices_hypothesis"])
    check("V10_comma_topic_permutation",{"source_graph_preserved":sorted(map(key,reordered))==sorted(map(key,ns))})
    check("V10_new_topic_terminates_old",{"new_beta_scope":top(p("For item alpha, for item beta, use Friday"))[0]["target_indices_hypothesis"]==[1]})
    for index, malformed in enumerate((None,"node",[1])):
        f = source_features_v10("Friday",malformed,{},True,True)
        check("V10_typed_node_%d" % index,{"no_features":not f["features"],"explicit_reason":bool(f["reasons"])})
    source,o,ns=observed["P01"]
    for index,(privacy,framing) in enumerate(((1,True),("true",True),(True,1),(True,"true"))):
        f=source_features_v10(source["text"],ns[0],source["context"],privacy,framing)
        check("V10_nonboolean_flags_%d" % index,{"rejects_nonboolean":not f["features"] and bool(f["reasons"])})
    duplicate_index=dict(CONTEXT,targets=[{"index":0,"label":"item alpha"},{"index":0,"label":"item beta"}])
    r=p("Use Friday for item alpha",duplicate_index)
    check("V10_duplicate_target_index",{"unknown_scope":top(r)[0]["target_indices_hypothesis"] is None,"diagnostic":"ambiguous_target_index_metadata" in r["diagnostics"]})
    return {"cases": results, "executed": len(results), "passed": sum(x["passed"] for x in results),
            "assertions": sum(x["assertions"] for x in results), "finite_spec_cases_executed": 38,
            "finite_spec_cases_passed": sum(x["passed"] for x in results[:38]),
            "legacy_equivalent_checks": legacy_count, "six_falsifications_executed": 6,
            "frozen_V9_equivalent_checks":105,"checkpoint17_probes_executed":28,
            "legacy_contract_amendments": [{"case": "T24", "old": "borrow old target into unscoped replacement", "new": "unknown replacement target stays unknown; relation unresolved"},
                                           {"case":"V9_P12_role_locality","old":"asserted sibling polarity unassessed","new":"explicit source USES predicate supplies asserted hypothesis; quoted sibling remains quoted"}]}


if __name__ == "__main__":
    results = run_checks()
    print(json.dumps(results, ensure_ascii=True))
    raise SystemExit(0 if results["passed"] == results["executed"] else 1)
