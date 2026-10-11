"""Audited deterministic English candidate proposer; no semantic absence claim.

Candidates are source-span hypotheses, not normalized values or qualified labels.
No dataset labels are loaded. Unmatched/unreviewed candidates stay masked.
"""
import re

DETECTOR_VERSION="scoped_candidate_proposer.v3.1"
COMPONENT_NAMES=("amount","date","time","security_answer","recipient","allocation")


def clause_ranges_v3(text):
    cuts=[0]
    for match in re.finditer(r";|\n|(?<!\d)[.!?]\s+|\s+\bbut\b\s+",text,re.I):
        cuts.append(match.end())
    cuts.append(len(text))
    result=[]
    for start,end in zip(cuts,cuts[1:]):
        while start < end and text[start].isspace(): start+=1
        while start < end and text[end-1].isspace(): end-=1
        if start < end: result.append({"clause_id":"c"+str(len(result)),"start":start,"end":end})
    return result


def detect_candidates_v3(text,question_role="none",targets=None,security_fields=None,locale="en"):
    if type(text) is not str or not text or len(text)>4096:
        return {"version":DETECTOR_VERSION,"status":"overflow" if type(text) is str and len(text)>4096 else "unsupported_context","candidates":[],"candidate_count":0,"clauses":[],"missing_kind_diagnostics":{},"absence_established":False}
    clauses=clause_ranges_v3(text)
    candidates=[]; exclusions=[]; unsupported=[]
    def add(kind,start,end,role_start=None,role_end=None,hint=None):
        if not 0 <= start < end <= len(text): return
        if any(c["kind"]==kind and c["start"]==start and c["end"]==end for c in candidates): return
        clause=next((c["clause_id"] for c in clauses if c["start"]<=start and end<=c["end"]),None)
        candidates.append({"candidate_id":"h"+str(len(candidates)),"kind":kind,"name":kind,"start":start,"end":end,
                           "clause_id_or_unknown":clause,"proposer_version":DETECTOR_VERSION,"possible_kinds":[kind],
                           "role_evidence_spans":[] if role_start is None else [{"start":role_start,"end":role_end}],
                           "detector_status":"candidate","validity_mask":False,"completion_hint":hint})
    if locale != "en":
        return {"version":DETECTOR_VERSION,"status":"unsupported_context","candidates":[],"candidate_count":0,"clauses":clauses,"missing_kind_diagnostics":dict.fromkeys(COMPONENT_NAMES,"unsupported_context"),"absence_established":False}
    if question_role == "security":
        # Descriptor is an independent wrapper argument, never a whole-turn regex.
        if not security_fields:
            unsupported.append("security_field_isolation_unavailable")
        else:
            for descriptor in security_fields:
                if type(descriptor) is not dict or descriptor.get("source_bound") is not True or type(descriptor.get("start")) is not int or type(descriptor.get("end")) is not int or not 0<=descriptor["start"]<descriptor["end"]<=len(text):
                    unsupported.append("invalid_security_field_descriptor")
                    continue
                add("security_answer",descriptor["start"],descriptor["end"])
        return {"version":DETECTOR_VERSION,"status":"unsupported_context" if unsupported else "candidate",
                "candidates":candidates,"candidate_count":len(candidates),"clauses":clauses,
                "missing_kind_diagnostics":dict.fromkeys(COMPONENT_NAMES,"unsupported_context"),
                "absence_established":False,"surface_features_masked":True,"lost_admin_head_capability":True,"unsupported":unsupported}
    # Typed competing spans retained for false-candidate audit, never money labels.
    for match in re.finditer(r"\b(?:card|account)\s+(?:ending|number|suffix)(?:\s+in)?\s+([0-9]+)\b",text,re.I):
        exclusions.append({"kind":"identifier","start":match.start(1),"end":match.end(1),"role_start":match.start(),"role_end":match.start(1)})
    dates=(r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|today|tomorrow|next\s+week|this\s+week|another\s+date|that\s+date)\b",
           r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?(?:,?\s+\d{4})?\b",
           r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
           r"\b(?:on|next|Fri|Mon)(?:\s*)?(?:\.\.\.|\u2026)(?!\w)")
    for pattern in dates:
        for match in re.finditer(pattern,text,re.I):
            hint="unfinished" if match.group().rstrip().endswith(("...","\u2026")) else "complete_expression_unparsed"
            add("date",match.start(),match.end(),hint=hint)
    for match in re.finditer(r"\b\d{1,2}:\d{2}(?:\s*(?:am|pm))?\b",text,re.I):
        add("time",match.start(),match.end())
    numeric=r"\d+(?:[.,]\d+)?"
    words=r"(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|hundred|thousand)(?:\s+(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|hundred|thousand|and))*(?:\.\.\.|\u2026)?"
    for match in re.finditer(r"[$\u00a3\u20ac]\s*("+numeric+r")",text):
        add("amount",match.start(1),match.end(1),match.start(),match.start(1))
    pattern=r"\b(?:pay|paid|payment|amount|budget|afford)\b(?:\s+(?:is|of|was|about|around|only|a|total|to|be)){0,4}\s+[$\u00a3\u20ac]?\s*("+numeric+"|"+words+r")\b"
    for match in re.finditer(pattern,text,re.I):
        add("amount",match.start(1),match.end(1),match.start(),match.start(1))
    if question_role == "amount":
        match=re.fullmatch(r"\s*([$\u00a3\u20ac]?\s*"+numeric+r")\s*[.!]?\s*",text)
        if match: add("amount",match.start(1),match.end(1))
    # Numerically overlapping date/time/identifier hypotheses remain explicit.
    for candidate in candidates:
        competing=[other["kind"] for other in candidates+exclusions if other["kind"]!=candidate["kind"] and max(other["start"],candidate["start"])<min(other["end"],candidate["end"])]
        if competing:
            candidate["possible_kinds"]=sorted(set([candidate["kind"]]+competing))
            candidate["detector_status"]="conflicting_candidates"
    present={candidate["kind"] for candidate in candidates}
    status="overflow" if len(candidates)>16 or len(clauses)>12 else "conflicting_candidates" if any(c["detector_status"]=="conflicting_candidates" for c in candidates) else "candidate" if candidates else "no_candidate"
    return {"version":DETECTOR_VERSION,"status":status,"candidates":candidates,"candidate_count":len(candidates),"clauses":clauses,
            "competing_kind_spans":exclusions,"missing_kind_diagnostics":{kind:"detector_no_candidate" for kind in COMPONENT_NAMES if kind not in present},
            "absence_established":False,"surface_features_masked":False,"language_pattern_coverage_qualified":False}


def align_candidates_v3(diagnostics,reviewed_components,whole_turn_absence=None):
    """Exact kind/Unicode spans ONLY. Never use nearest span as a training target.

    Candidate validity negatives require explicit reviewed absence for that kind.
    Completion/polarity labels attach only to exact matched reviewed masks.
    """
    rows=[]; matched=set()
    for candidate in diagnostics["candidates"]:
        hits=[(i,gold) for i,gold in enumerate(reviewed_components) if gold["kind"]==candidate["kind"] and gold["start"]==candidate["start"] and gold["end"]==candidate["end"]]
        row={"candidate":candidate,"validity_label":None,"validity_mask":False,"completion_label":None,"completion_mask":False,"polarity_label":None,"polarity_mask":False}
        if len(hits)==1:
            index,gold=hits[0]; matched.add(index)
            row.update(validity_label=True,validity_mask=gold.get("presence_mask") is True,
                       completion_label=gold.get("completion"),completion_mask=gold.get("completion_mask") is True,
                       polarity_label=gold.get("polarity"),polarity_mask=gold.get("polarity_mask") is True)
        elif (whole_turn_absence or {}).get(candidate["kind"]) is True:
            row.update(validity_label=False,validity_mask=True)
        rows.append(row)
    return {"rows":rows,"missed_reviewed_component_indices":[i for i in range(len(reviewed_components)) if i not in matched],
            "unreviewed_candidates":sum(not r["validity_mask"] for r in rows),"oracle_span_metric":False}
