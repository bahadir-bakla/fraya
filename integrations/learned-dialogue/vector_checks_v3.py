"""Run designer checkpoint07 fixtures through actual new modules; no fitting.

Adapter is explicitly synthetic. Observer binding/dependencies come from the
designer sidecar, protocol identities from fixture snapshot; copied raw text is
not independent authentication. Literal independent controls in test_v3 cover
payload-only mutations separately. Expected labels never enter learned features.
"""
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from unittest.mock import patch
import jsonschema
from context_v2 import BindingContext,InputRejected
from context_v3 import predict_v3
from detector_v3 import detect_candidates_v3
from reference_v3 import TrustedCallV3,resolve_reference_v3
from merge_v3 import merge_components_v3
from test_v3 import BUNDLE,SCHEMA

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[1]

def adapt(vector):
    s=vector["input_snapshot"]; o=vector["observer"]
    if o is None: return None,{},{}
    ctx=BindingContext({k:o[k] for k in ("turn_id","state_revision","policy_hash","api_hash")},BUNDLE["model_id"])
    q=s["question"]
    t=TrustedCallV3(ctx,o["call_local_id"],o["source_event_id"],o["event_order"][o["source_event_id"]],
                    s["utterance"]["text"],True,(q["question_id"],q["spoken_turn_id"],q["role"]),
                    tuple((x["index"],x["product_id"]) for x in s["targets"]))
    registry={"source_events":[],"references":[]}; state={"targets":{}}
    index_ids={x["index"]:x["product_id"] for x in s["targets"]}
    for index,tid in index_ids.items():
        components={key.split("/",1)[1]:{"revision":token} for key,token in o["current_component_tokens"].items() if key.startswith(str(index)+"/")}
        state["targets"][tid]={"target_index":index,"disposition_epoch":"fixture-epoch:"+str(index),"components":components,"current_offer_id":q.get("spoken_offer_id")}
    for eid,ordinal in o["event_order"].items():
        registry["source_events"].append({"event_id":eid,"ordinal":ordinal,"call_local_id":o["call_local_id"],
                                         "role":"user" if eid==o["source_event_id"] else "assistant","completed":True})
    for rid,raw in o["registry"].items():
        deps={}
        for key,token in raw["dependency_tokens"].items():
            index,name=key.split("/",1); deps.setdefault(index_ids[int(index)],{})[name]=token
        entry={"reference_id":rid,"kind":raw["kind"],"created_state_revision":raw["created_state_revision"],
               "spoken_event_id":raw["spoken_event_id"],"call_local_id":raw["call_local_id"],"question_id":q["question_id"],
               "completed_speech":raw["completed_speech"],"superseded_or_invalidated":raw["superseded"],
               "policy_hash":raw["policy_hash"],"api_hash":raw["api_hash"],"target_ids":[index_ids[i] for i in raw["target_indices"]],
               "dependency_component_tokens":deps,"target_disposition_epochs":{tid:"fixture-epoch:"+str(state["targets"][tid]["target_index"]) for tid in deps}}
        terms={tid:{name:"opaque-fictional-term" for name in names} for tid,names in deps.items()}
        if raw["kind"]=="readback":
            entry.update(readback_component_tokens=copy.deepcopy(deps),exact_spoken_terms=terms,active_readback_id=rid)
            state["active_readback_id"]=rid
        else: entry.update(base_component_tokens=copy.deepcopy(deps),immutable_terms=terms)
        registry["references"].append(entry)
    return t,registry,state

def detector_comparison(expected,observed):
    candidates=observed["candidates"]; errors=[]; exercised=[]
    triples={(c["kind"],c["start"],c["end"]) for c in candidates}
    for span in expected.get("required_typed_spans",[]):
        exercised.append("required_span")
        if (span["kind"],span["start"],span["end"]) not in triples: errors.append("missing_required_span")
    for span in expected.get("forbidden_typed_spans",[]):
        exercised.append("forbidden_span")
        if (span["kind"],span["start"],span["end"]) in triples: errors.append("forbidden_span")
    for span in expected.get("forbidden_amount_spans",[]):
        exercised.append("forbidden_amount")
        if any(c["kind"]=="amount" and c["start"]<span["end"] and span["start"]<c["end"] for c in candidates): errors.append("forbidden_amount_overlap")
    if "required_amount_anchor_start" in expected:
        exercised.append("four_digit_control")
        if not any(c["kind"]=="amount" and c["start"]==expected["required_amount_anchor_start"] for c in candidates): errors.append("missing_four_digit_money")
        if any(c["kind"]=="amount" and c["start"]==expected["forbidden_amount_start"] for c in candidates): errors.append("identifier_money")
    if "expected_date_candidates" in expected:
        exercised.append("absence_control_without_wire_absence")
        if [c for c in candidates if c["kind"]=="date"]!=expected["expected_date_candidates"]: errors.append("unexpected_date")
    if "security_evidence_must_not_cover" in expected:
        exercised.append("security_admin_bound")
        span=expected["security_evidence_must_not_cover"]
        if any(c["kind"]=="security_answer" and c["start"]<span["end"] and span["start"]<c["end"] for c in candidates): errors.append("security_admin_overlap")
    if expected.get("must_not_infer_absent_on_no_candidate") or expected.get("if_no_candidate"):
        exercised.append("no_absence_on_miss")
        if observed["absence_established"]: errors.append("absence_invented")
    return {"state":"contract_fail" if errors else ("contract_pass" if exercised else "not_exercised"),"errors":errors,"exercised":exercised}

def run_vectors():
    path=ROOT/"analysis/learned-layer-design.checkpoint07-vectors.json"; raw=path.read_bytes(); doc=json.loads(raw)
    rows=[]; validator=jsonschema.Draft202012Validator(SCHEMA)
    for vector in doc["vectors"]:
        s=vector["input_snapshot"]; before=copy.deepcopy(s); t,registry,state=adapt(vector); item={"id":vector["id"]}
        with patch("builtins.open",side_effect=AssertionError("file")),patch("socket.socket",side_effect=AssertionError("network")),patch("subprocess.Popen",side_effect=AssertionError("process")):
            try:
                wire,side=predict_v3(s,BUNDLE,t,registry,state,SCHEMA)
                def has_accepted(value):
                    if type(value) is dict:
                        return value.get("decision")=="accept" or any(has_accepted(v) for v in value.values())
                    return type(value) is list and any(has_accepted(v) for v in value)
                forbidden={"tool","tool_request","api_request","permission","canonical_amount","canonical_date","operation"}
                def forbidden_key(value):
                    if type(value) is dict: return bool(forbidden&set(value)) or any(forbidden_key(v) for v in value.values())
                    return type(value) is list and any(forbidden_key(v) for v in value)
                safe=not has_accepted(wire) and not forbidden_key(wire) and wire["consent_signal"]["decision"]=="descriptive_only"
                item["guard"]={"state":"contract_pass" if not list(validator.iter_errors(wire)) and wire["status"]=="abstain" and s==before and safe else "contract_fail",
                               "schema_valid":not list(validator.iter_errors(wire)),"all_abstain":wire["status"]=="abstain","input_unchanged":s==before,
                               "wire_clause_count":len(wire["clauses"]),"no_accepted_heads_or_authority_fields":safe}
            except InputRejected:
                wire=None; side={}
                item["guard"]={"state":"contract_pass" if t is None else "contract_fail","InputRejected":True,"input_unchanged":s==before}
            if vector.get("detector_expected"):
                observed=side.get("detector")
                item["detector"]=detector_comparison(vector["detector_expected"],observed) if observed else {"state":"not_exercised"}
                item["detector"]["observed"]=observed
            # Semantic axes are deliberately not fabricated by untrained heads.
            item["semantic"]={"state":"not_exercised","reason":"No qualified clause/target/completion/polarity/act-completion capability; wire remains uncertainty",
                              "observed_raw_primary":None if wire is None else wire["primary"]}
            if vector.get("reference_case"):
                case=vector["reference_case"]; label="readback_affirmation" if case["kind"]=="readback" else "offer_acceptance"
                detector=detect_candidates_v3(s["utterance"]["text"],s["question"]["role"])
                # Full-pipeline veto derives from current actual candidates,
                # not from case.same_turn_component_updates or expected answers.
                actual=resolve_reference_v3(s,label,t,registry,state,bool(detector["candidates"]))
                matching=actual["candidate_id_or_null"]==case["expected_candidate_id"] and actual["reason"]==case["expected_reason"]
                item["reference"]={"state":"contract_pass" if matching else "contract_fail","observed":actual,
                                   "label_source":"explicit protocol selector isolates deterministic reference resolver; learned selection not qualified",
                                   "pipeline_raw_reference":side.get("reference"),"pipeline_span_veto":bool(detector["candidates"])}
            if vector.get("ingress_case"):
                expected=vector["ingress_case"]["expected_reason"]
                observed="InputRejected" if wire is None else side.get("ingress_reason")
                item["ingress"]={"state":"contract_pass" if observed==expected else "contract_fail","observed":observed,"expected":expected}
            if vector.get("merge_case"):
                case=vector["merge_case"]
                try:
                    actual=merge_components_v3(s["utterance"]["text"],case["rows"],case["explicit_edges"],case.get("completed_links",[]),case["prior_unresolved"])
                    ok=actual["facts"]==case["expected_facts"] and actual["unresolved_components"]==case["expected_unresolved"]
                    item["merge"]={"state":"contract_pass" if ok else "contract_fail","observed":actual,"scope":"Supplied source-grounded row/edge algebra ONLY; actual semantic producer unavailable"}
                except ValueError as exc: item["merge"]={"state":"contract_fail","error":str(exc)}
        rows.append(item)
    counts={layer:dict(Counter(r[layer]["state"] for r in rows if layer in r)) for layer in ("guard","detector","semantic","reference","ingress","merge")}
    return {"vector_sha256":hashlib.sha256(raw).hexdigest(),"vectors":len(rows),"counts":counts,"rows":rows,
            "scope":"Designer engineering controls, neither new gold nor qualification. Synthetic adapter raw/question/target copies prove no authentication; 48 independently literal source controls reported separately.",
            "semantic_not_exercised_does_NOT_count_as_success":True,"new_fits":0,"bank_calls":0,"state_mutations":0}

if __name__=="__main__":
    report=run_vectors()
    print(json.dumps({"counts":report["counts"],"failures":[{k:v for k,v in r.items() if k=="id" or isinstance(v,dict) and v.get("state")=="contract_fail"} for r in report["rows"] if any(isinstance(v,dict) and v.get("state")=="contract_fail" for v in r.values())]},indent=2))
