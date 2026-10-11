"""Bounded English maximal temporal-expression proposer, checkpoint08.

Syntax diagnostics are hypotheses, never adjudicated labels/normalization.
All offsets refer to the unmodified delivered Unicode source.
"""
import re
from detector_v3 import detect_candidates_v3

DETECTOR_R4_VERSION="date_expression_scanner.r4.2"
MONTHS_R4=set("january february march april may june july august september october november december".split())
WEEKDAYS_R4=set("monday tuesday wednesday thursday friday saturday sunday".split())
ORDINALS_R4=set("first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth thirteenth fourteenth fifteenth sixteenth seventeenth eighteenth nineteenth twentieth thirtieth".split())
NUMWORDS_R4=set("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty thirty".split())
PERIODS_R4=set("day days week weeks month months year years quarter quarters summer winter spring autumn fall morning afternoon evening".split())
TOKEN_R4=re.compile(r"\.\.\.|…|[^\W\d_]+(?:['’][^\W\d_]+)?|\d+(?:st|nd|rd|th)?|[-/,:;.!?]|[^\s]",re.I)

def tokenize_r4(text):
    result=[]
    for m in TOKEN_R4.finditer(text):
        value=m.group().lower()
        if value.endswith(("'s","’s")) and value[:-2] in PERIODS_R4: value=value[:-2]
        result.append({"value":value,"start":m.start(),"end":m.end()})
    return result

def clause_ranges_r4(text):
    cuts=[0]+[m.end() for m in re.finditer(r";|\n|(?<![\d.])[.!?](?!\.)\s+|\s+\bbut\b\s+",text,re.I)]+[len(text)]
    result=[]
    for a,b in zip(cuts,cuts[1:]):
        while a<b and text[a].isspace(): a+=1
        while a<b and text[b-1].isspace(): b-=1
        if a<b: result.append({"clause_id":"c"+str(len(result)),"start":a,"end":b})
    return result

def date_expressions_r4(text,question_role="none",locale="en"):
    if type(text) is not str or not text.strip() or len(text)>4096 or locale!="en":
        return {"version":DETECTOR_R4_VERSION,"status":"unsupported_context","candidates":[],"clauses":[],
                "absence_established":False,"reason":"unsupported_source_or_locale"}
    clauses=clause_ranges_r4(text); proposed=[]
    for clause in clauses:
        ts=[t for t in tokenize_r4(text) if clause["start"]<=t["start"] and t["end"]<=clause["end"]]
        n=len(ts)
        def v(i): return ts[i]["value"] if 0<=i<n else ""
        def number(i):
            if re.fullmatch(r"\d+(?:st|nd|rd|th)?",v(i)) or v(i) in ORDINALS_R4|NUMWORDS_R4:
                j=i+1
                if v(i) in {"twenty","thirty"} and v(j)=="-" and v(j+1) in ORDINALS_R4: j+=2
                return j
            return None
        def result(start,end,status="closed",reference=False,depth=0,reason=None):
            return {"a":start,"b":end,"syntax_status":status,"reference_required":reference,"depth":depth,"reason":reason}
        def atom(i,allow_fragment=False):
            if not 0<=i<n: return None
            start=i; j=i
            if v(j) in {"the","a","an","some"}: j+=1
            prefix=v(j)
            if prefix in {"today","tomorrow","yesterday"}: return result(start,j+1)
            if prefix in {"next","this","last","another","that"}:
                if v(j+1) in PERIODS_R4|{"date"}:
                    return result(start,j+2,reference=prefix in {"that","another"})
                if allow_fragment and (not v(j+1) or v(j+1) in {"...","…"}): return result(start,j+1,"open",reason="missing_temporal_operand")
            if prefix in MONTHS_R4:
                j+=1; day=number(j)
                if day: j=day
                if v(j)==",": j+=1
                if re.fullmatch(r"\d{4}",v(j)): j+=1
                elif v(j) in NUMWORDS_R4 and v(j+1) in NUMWORDS_R4:
                    j+=2
                    if v(j)=="-" and v(j+1) in NUMWORDS_R4: j+=2
                elif v(j) in NUMWORDS_R4 and v(j+1) in {"...","…"}:
                    return result(start,j+1,"open",reason="unfinished_spoken_year")
                return result(start,j)
            if prefix in WEEKDAYS_R4:
                j+=1
                k=j+1 if v(j)=="," else j
                rest=calendar(k)
                if rest:
                    rest["a"]=start; return rest
                return result(start,j)
            numeric=number(j)
            if numeric:
                j=numeric
                if v(j) in {"/","-"} and re.fullmatch(r"\d+",v(start)):
                    j+=1
                    if re.fullmatch(r"\d+",v(j)):
                        j+=1
                        if v(j) in {"/","-"}:
                            j+=1
                            if re.fullmatch(r"\d+",v(j)): j+=1
                            else: return result(start,j,"open",reason="open_numeric_date")
                        return result(start,j,reference=True)
                    return result(start,j,"open",reason="open_numeric_date")
                if v(j)=="of":
                    j+=1
                    if v(j) in MONTHS_R4:
                        j+=1
                        if re.fullmatch(r"\d{4}",v(j)): j+=1
                        return result(start,j)
                    return result(start,j,"open",reason="open_of_complement")
                if v(j) in MONTHS_R4:
                    j+=1
                    if re.fullmatch(r"\d{4}",v(j)): j+=1
                    return result(start,j)
                if v(j) in {"business","working"} and v(j+1) in {"day","days"}: j+=2
                elif v(j) in {"day","days"}: j+=1
                else:
                    ordinal=any(v(k) in ORDINALS_R4 or re.fullmatch(r"\d+(?:st|nd|rd|th)",v(k)) for k in range(start,j))
                    if ordinal and (allow_fragment or v(start)=="the"): return result(start,j,reference=True)
                    return None
                return result(start,j,reference=True)
            if prefix in {"final","last","first","start","end"}:
                j+=1
                if v(j) in {"working","business"}: j+=1
                if v(j) in PERIODS_R4: j+=1
                if j>start+1: return result(start,j,reference=True)
            if prefix in {"business","working"} and v(j+1)=="day": return result(start,j+2,reference=True)
            if prefix in PERIODS_R4:
                if j>start or v(j+1) in {"of","before","after","in"}:
                    return result(start,j+1,reference=True)
                return None
            if prefix=="date" and v(start) in {"that","another"}: return result(start,j+1,reference=True)
            if allow_fragment and v(start)=="the" and v(j) in {"...","…",""}:
                return result(start,j,"open",reason="open_determiner")
            return None
        def calendar(i):
            # Calendar-only continuation prevents weekday + unrelated quantity join.
            if v(i) in MONTHS_R4: return atom(i,True)
            j=i+1 if v(i)=="the" else i; k=number(j)
            if k and (v(k)=="of" or v(k) in MONTHS_R4): return atom(i,True)
            return None
        def expression(i,depth=0):
            if depth>1 or not 0<=i<n: return None
            prefix=v(i)
            if prefix in {"from","either"}:
                if v(i+1) in {"from","either"}:
                    return result(i,i+2,"unsupported",True,depth,"nested_range_prefix_unsupported")
                first=expression(i+1,depth)
                if not first: return None
                first["a"]=i
            elif prefix in {"before","after","immediately"}:
                op=i+1 if prefix=="immediately" else i
                if v(op) not in {"before","after"}: return None
                operand=expression(op+1,depth+1)
                if operand:
                    operand["a"]=i; operand["reference_required"]=True; operand["depth"]=depth+1
                    return operand
                return result(i,op+1,"open",True,depth,"open_relation")
            else:
                first=atom(i,allow_fragment=question_role in {"date","payment","callback"} or bool(re.search(r"\b(?:pay|payment|date|calendar|on)\b",text[max(clause["start"],ts[i]["start"]-48):ts[i]["start"]],re.I)))
                if not first: return None
            j=first["b"]
            # Retain dependent operators only inside a supported temporal production.
            if v(j) in {"of","before","after"} or (v(j)=="in" and v(j-1) in PERIODS_R4):
                op=v(j); operand=expression(j+1,depth+1) if depth<1 else None
                if op in {"before","after"} and v(j+1) in {"my","the","our"}:
                    k=j+2
                    while k<n and v(k) in {"return","trip","flight","arrival","departure","payday","birthday","deposit","clears"}: k+=1
                    if k>j+2: operand=result(j+1,k,reference=True)
                if operand:
                    first["b"]=operand["b"]; first["syntax_status"]=operand["syntax_status"]
                    first["reference_required"]=True; first["depth"]=max(first["depth"],depth+1)
                    first["reason"]=operand["reason"]
                elif op=="after" and v(j+1)=="next":
                    first["b"]=j+2; first["reference_required"]=True
                else:
                    shallow=atom(j+1,True) if depth>=1 else None
                    first["b"]=shallow["b"] if shallow else j+1
                    first["syntax_status"]="open" if depth<1 else "unsupported"
                    first["reason"]="open_relation" if depth<1 else "dependency_depth_limit"
                j=first["b"]
            # Adjacent period is consumed only as a temporal modifier.
            if v(j) in {"next","this","last"} and v(j+1) in PERIODS_R4:
                first["b"]=j+2; first["reference_required"]=True; j+=2
            if v(j) in {"to","or"}:
                endpoint=expression(j+1,depth+1)
                first["b"]=endpoint["b"] if endpoint else j+1
                first["syntax_status"]=endpoint["syntax_status"] if endpoint else "open"
                first["reason"]=endpoint["reason"] if endpoint else "open_range_endpoint"
            return first
        parses=[]
        for i in range(n):
            parsed=expression(i)
            if parsed and parsed["b"]>parsed["a"]:
                end=parsed["b"]
                if v(end) in {"...","…"} and parsed["syntax_status"]=="open": end+=1
                elif v(end) in {"...","…"} and (not v(end+1) or v(end+1) in {'"',"”","’"}):
                    parsed["syntax_status"]="ambiguous"; parsed["reason"]="unresolved_terminal_hesitation"
                a,b=ts[parsed["a"]]["start"],ts[end-1]["end"]
                if b-a>512 or end-parsed["a"]>80:
                    parsed["syntax_status"]="unsupported"; parsed["reason"]="expression_size_limit"
                parses.append(dict(parsed,start=a,end=b))
        maximal=[p for p in parses if not any(q["start"]<=p["start"] and p["end"]<=q["end"] and (q["start"],q["end"])!=(p["start"],p["end"]) for q in parses)]
        seen=set()
        for p in maximal:
            if (p["start"],p["end"]) in seen: continue
            seen.add((p["start"],p["end"]))
            children=[{"start":q["start"],"end":q["end"]} for q in parses if p["start"]<=q["start"]<q["end"]<=p["end"] and (p["start"],p["end"])!=(q["start"],q["end"])]
            proposed.append({"candidate_id":"d"+str(len(proposed)),"kind":"date","name":"date","start":p["start"],"end":p["end"],
                             "clause_id_or_unknown":clause["clause_id"],"proposer_version":DETECTOR_R4_VERSION,
                             "syntax_status":p["syntax_status"],"syntax_reason":p["reason"],"reference_required":p["reference_required"],
                             "dependency_incomplete":p["syntax_status"] in {"open","unsupported"},"children":children,
                             "possible_kinds":["date"],"validity_mask":False,"normalization_mask":False,"reference_mask":False})
    overflow=len(proposed)>16 or len(clauses)>12
    return {"version":DETECTOR_R4_VERSION,"status":"overflow" if overflow else ("candidate" if proposed else "no_candidate"),
            "candidate_count":len(proposed),"candidates":proposed,"clauses":clauses,"absence_established":False,
            "normalization":"not_implemented","all_validity_masks_unqualified":True}

def detect_candidates_r4(text,question_role="none",targets=None,security_fields=None,locale="en"):
    legacy=detect_candidates_v3(text,question_role,targets,security_fields,locale)
    if question_role=="security" or security_fields is not None:
        return dict(legacy,version=DETECTOR_R4_VERSION,dates_masked_for_security=True)
    dates=date_expressions_r4(text,question_role,locale)
    # R3 nondate hypotheses retained as competing-type witnesses, never authorities.
    nondate=[c for c in legacy["candidates"] if c["kind"]!="date"]
    conflicts=[]; identifiers=legacy.get("competing_kind_spans",[])
    for c in dates["candidates"]:
        competing=[x["kind"] for x in nondate+identifiers if x["start"]<c["end"] and c["start"]<x["end"]]
        if competing:
            c["possible_kinds"]=sorted(set(["date"]+competing)); c["boundary_ambiguous"]=True
            conflicts.append(c["candidate_id"])
    return dict(dates,nondate_candidates=nondate,competing_candidate_ids=conflicts,
                identifier_exclusions=identifiers)
