"""New shadow wrapper: pure proposal wire plus separate source/candidate diagnostics.

Frozen v2 learned weights reused as exposed diagnostics; no fit/qualification.
Candidate-validity, clause identity, target, correction and consent remain masks.
"""
from context_v2 import (InputRejected, neutral_v2, feature_v2, distribution_v2,
                        binary_score_v2, qualifiers_v2, ProposalOverflow)
from reference_v3 import TrustedCallV3, validate_ingress_v3, resolve_reference_v3
from detector_v3 import detect_candidates_v3
from guard_v3 import wire_errors_v3
import re


def qualifiers_with_coverage_v3(snapshot):
    patterns={"correction":r"\b(?:actually|I meant|I mean|no wait|revise|correct)\b",
              "negation":r"\b(?:not|never|cannot|can't|don't|won't|no)\b",
              "qualifier":r"\b(?:if|maybe|perhaps|provided|but)\b"}
    spans=[]
    for role,pattern in patterns.items():
        for m in re.finditer(pattern,snapshot["utterance"]["text"],re.I):
            spans.append(_span_v3(snapshot,m.start(),m.end(),role))
    return sorted(spans,key=lambda s:(s["start"],s["end"]))


def _decision_v3(score,reason="untrained_head"):
    return {"score":score,"calibrated_probability":None,"calibration_id":None,"decision":"abstain","abstain_reason":reason}


def _span_v3(snapshot,start,end,role):
    return {"turn_id":snapshot["turn_id"],"start":start,"end":end,"role":role}


def predict_v3(snapshot,bundle,trusted,registry,state,schema,include_context=True,security_fields=None):
    if not isinstance(trusted,TrustedCallV3): raise InputRejected("Independent source wrapper required")
    try:
        reason=validate_ingress_v3(snapshot,trusted)
        if reason: return neutral_v2(trusted.binding_context,reason),{"ingress_reason":reason,"qualified":False}
        if bundle.get("model_id")!=trusted.binding_context.model_id:
            return neutral_v2(trusted.binding_context,"stale_binding"),{"ingress_reason":"stale_binding","qualified":False}
        model=bundle["model"]
        if model.get("format") != "context-sparse-diagnostic-v2":
            return neutral_v2(trusted.binding_context,"unknown_schema"),{"qualified":False}
        text=snapshot["utterance"]["text"]
        detector=detect_candidates_v3(text,snapshot["question"]["role"] if include_context else "none",snapshot["targets"],security_fields)
        if snapshot["question"]["role"]=="security" or security_fields is not None:
            detector=detect_candidates_v3(text,"security",snapshot["targets"],security_fields)
            return neutral_v2(trusted.binding_context,"untrained_head"),{"detector":detector,"surface_features_masked":True,"qualified":False}
        if detector["status"]=="overflow":
            return neutral_v2(trusted.binding_context,"size_limit"),{"detector":detector,"qualified":False}
        qualifiers=qualifiers_with_coverage_v3(snapshot)
        if len(qualifiers)>16:
            return neutral_v2(trusted.binding_context,"size_limit"),{"detector":detector,"qualifier_count":len(qualifiers),
                        "qualifier_coverage":qualifiers,"overflow":True,"qualified":False}
        vector=feature_v2(snapshot,include_context=include_context)
        scores=distribution_v2(model["heads"]["primary"],vector)
        label=max(scores,key=lambda key:(scores[key],key))
        primary=dict(_decision_v3(scores[label],"uncalibrated"),label=label,evidence=[_span_v3(snapshot,0,len(text),"intent")])
        secondary=[]
        for name,head in sorted(model["secondary"].items()):
            score=binary_score_v2(head,vector)
            if score>=.5 and name not in {label,"unknown"}: secondary.append(dict(_decision_v3(score,"uncalibrated"),label=name,evidence=primary["evidence"]))
        raw_components=[]
        for candidate in detector["candidates"]:
            # Actual detector span supplies these features. Local right-context
            # is reported but frozen v2 has no trained right-context features.
            features=feature_v2(snapshot,candidate,include_context)
            completion=distribution_v2(model["heads"]["component_completion"],features)
            polarity=distribution_v2(model["heads"]["component_polarity"],features)
            raw_components.append({"candidate":candidate,"completion_scores":completion,"polarity_scores":polarity,
                                   "local_right_context_supported_by_head":False,"candidate_validity_head_trained":False})
        clauses=[]
        for local in detector["clauses"]:
            components=[]
            for name in ("amount","date","time","security_answer","recipient","allocation"):
                rows=[c for c in detector["candidates"] if c["kind"]==name and c["clause_id_or_unknown"]==local["clause_id"]]
                if not rows: continue
                # Missing hypotheses omitted. Competing hypotheses keep all
                # original spans; validity/scope heads unavailable => uncertainty.
                components.append({"name":name,"completion":"ambiguous","polarity":"unknown",
                                   "evidence":[_span_v3(snapshot,r["start"],r["end"],"value") for r in rows],
                                   "reference":None,"confidence":_decision_v3(0.)})
            unknown=dict(_decision_v3(0.),label="unknown",evidence=[_span_v3(snapshot,local["start"],local["end"],"intent")])
            clauses.append({"clause_id":local["clause_id"],"intent":unknown,"scope":"unresolved","target_refs":[],
                            "collective_id":None,"amount_scope":"unresolved","components":components,
                            "qualifiers":[q for q in qualifiers if local["start"]<=q["start"] and q["end"]<=local["end"]],"offer_reference":None})
        new_terms=bool(detector["candidates"] or any(q["role"]=="correction" for q in qualifiers))
        reference=resolve_reference_v3(snapshot,label,trusted,registry,state,new_terms) if include_context else {"candidate_id_or_null":None,"reason":"unresolved_reference","reference_kind":None,"context_disabled":True}
        proposal=neutral_v2(trusted.binding_context,"uncalibrated")
        proposal.update(primary=primary,secondary=secondary,clauses=clauses)
        if reference["reference_kind"]=="readback": proposal["consent_signal"]["candidate_readback_id"]=reference["candidate_id_or_null"]
        proposal["consent_signal"]["has_new_terms"]=True if new_terms else "unknown"
        errors=wire_errors_v3(proposal,snapshot,schema)
        if errors: proposal=neutral_v2(trusted.binding_context,"runtime_failure")
        return proposal,{"detector":detector,"component_scores_on_actual_candidates":raw_components,"reference":reference,"wire_errors":errors,
                         "trained_weights":"frozen exposed v2; no refit","all_candidate_validity_and_scope_masks_unqualified":True,"qualified":False}
    except (KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError,ProposalOverflow):
        return neutral_v2(trusted.binding_context,"runtime_failure"),{"runtime_failure":True,"qualified":False}
