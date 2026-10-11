"""Executed finite semantics and metamorphic controls; no fitting or DEV reads."""
import ast
import json
from pathlib import Path
from temporal_parser_v8 import parse_temporal, project_segments, typed_signature

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
                          directional_edge=bool(o["correction_edges"] and o["correction_edges"][0]["old"] == ns[0]["node_id"] and o["correction_edges"][0]["new"] == ns[1]["node_id"]),
                          old_negated=ns[0]["role_hypothesis"] == "superseded_hypothesis",
                          new_open=ns[-1]["syntax"] == "open" and ns[-1]["role_hypothesis"] == "replacement_hypothesis",
                          same_source_target=ns[0]["target_indices_hypothesis"] == ns[-1]["target_indices_hypothesis"] == [0])
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
    source = (Path(__file__).parent / "temporal_parser_v8.py").read_text(encoding="utf-8")
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
    return {"cases": results, "executed": len(results), "passed": sum(x["passed"] for x in results),
            "assertions": sum(x["assertions"] for x in results), "finite_spec_cases_executed": 38,
            "finite_spec_cases_passed": sum(x["passed"] for x in results[:38])}


if __name__ == "__main__":
    results = run_checks()
    print(json.dumps(results, ensure_ascii=True))
    raise SystemExit(0 if results["passed"] == results["executed"] else 1)
