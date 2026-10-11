"""One shared, versioned source-local extractor for tables/scorer/export."""
import re
from detector_r4 import DETECTOR_R4_VERSION,clause_ranges_r4

FEATURE_R4_VERSION="date_local_window.r4.2.cp48.feature384"
WINDOW_R4=48
FEATURE_CAP_R4=384

def date_features_r4(snapshot,candidate,source_admission):
    text=snapshot.get("utterance",{}).get("text")
    result={"feature_version":FEATURE_R4_VERSION,"features":{},"eligible":False,
            "reason":"source_unqualified","window_bounds":None,"normalization_mask":False,"reference_mask":False}
    if type(text) is not str or not source_admission or any(source_admission.get(k) is not True for k in ("verified_current_source","nonsecurity_value_free","framing_complete")):
        return result
    question=snapshot.get("question",{})
    if snapshot.get("phase")=="security" or question.get("role")=="security" or question.get("security_field") is not None or source_admission.get("has_unisolated_secret") is True:
        return dict(result,reason="secret_isolation_unqualified")
    if candidate.get("proposer_version")!=DETECTOR_R4_VERSION or candidate.get("kind")!="date":
        return dict(result,reason="detector_version_mismatch")
    a,b=candidate.get("start"),candidate.get("end")
    if type(a) is not int or type(b) is not int or not 0<=a<b<=len(text) or b-a>512:
        return dict(result,reason="invalid_span")
    clause=next((c for c in clause_ranges_r4(text) if c["start"]<=a<b<=c["end"]),None)
    if clause is None: return dict(result,reason="unsupported_cross_clause_dependency")
    left=max(clause["start"],a-WINDOW_R4); right=min(clause["end"],b+WINDOW_R4)
    bounds={"left":left,"candidate_start":a,"candidate_end":b,"right":right,"clause_start":clause["start"],"clause_end":clause["end"],
            "left_clipped":left>clause["start"],"right_clipped":right<clause["end"],
            "expression_tail":not text[b:clause["end"]].strip(" \t,.;!?'\"…"),
            "clause_tail":clause["end"]==len(text),"delivered_turn_tail":b==len(text),
            "dependency_incomplete":candidate.get("dependency_incomplete") is True}
    features={}
    def add_lex(prefix,surface):
        value=re.sub(r"\d+(?:st|nd|rd|th)?","<number>",surface.lower())
        words=re.findall(r"[a-z]+(?:['’][a-z]+)?|<number>|\.{3}|…|[-/:]",value)
        for word in words: features[prefix+"w:"+word]=1.
        for x,y in zip(words,words[1:]): features[prefix+"b:"+x+"_"+y]=1.
        normalized=" ".join(words)
        for size in (3,4):
            for i in range(min(max(0,len(normalized)-size+1),384)):
                features[prefix+"c"+str(size)+":"+normalized[i:i+size]]=1.
    add_lex("span:",text[a:b]); add_lex("left:",text[left:a]); add_lex("right:",text[b:right])
    for key,value in bounds.items():
        if type(value) is bool: features["boundary:"+key+"="+str(value)]=1.
    features["syntax:"+candidate.get("syntax_status","unsupported")]=1.
    features["context:reference_required="+str(candidate.get("reference_required") is True)]=1.
    if source_admission.get("question_role_verified") is True:
        role=snapshot.get("question",{}).get("role")
        if role in {"date","payment","callback","none"}: features["context:question="+role]=1.
        phase=snapshot.get("phase")
        if phase in {"payment","callback","readback","support","recipient"}: features["context:phase="+phase]=1.
    continuation=source_admission.get("continuation")
    continuation_ok=False
    if type(continuation) is dict:
        continuation_ok=all(type(continuation.get(k)) is str and continuation[k] for k in ("prior_source_event_id","component_token","current_component_token")) and continuation["component_token"]==continuation["current_component_token"] and continuation.get("source_relation_verified") is True
        features["context:linked_continuation="+str(continuation_ok)]=1.
    norm=sum(v*v for v in features.values())**.5 or 1.
    result.update(features={k:v/norm for k,v in features.items()},window_bounds=bounds,source_spans=[
        {"turn_id":snapshot["turn_id"],"start":left,"end":a,"role":"left_context"},
        {"turn_id":snapshot["turn_id"],"start":a,"end":b,"role":"actual_candidate"},
        {"turn_id":snapshot["turn_id"],"start":b,"end":right,"role":"right_context"}],
        eligible=True,reason=None,continuation_verified=continuation_ok)
    if bounds["left_clipped"] or bounds["right_clipped"]:
        result.update(eligible=False,reason="window_scope_clipped")
    if candidate.get("syntax_status")=="unsupported": result.update(eligible=False,reason="unsupported_dependency")
    if candidate.get("boundary_ambiguous"): result.update(eligible=False,reason="boundary_ambiguous")
    return result

def score_date_r4(snapshot,candidate,source_admission,bundle):
    extracted=date_features_r4(snapshot,candidate,source_admission)
    output={"feature_version":FEATURE_R4_VERSION,"raw_score":None,"completion_candidate":None,
            "decision":"abstain","qualified":False,"features_eligible":extracted["eligible"],"feature_diagnostics":extracted}
    if not bundle or bundle.get("feature_version")!=FEATURE_R4_VERSION or bundle.get("detector_version")!=DETECTOR_R4_VERSION:
        return dict(output,reason="untrained_head" if not bundle else "feature_version_mismatch")
    if not extracted["eligible"]: return dict(output,reason=extracted["reason"])
    # Future reviewed sparse head only; no v2 head accepted under new features.
    head=bundle.get("head")
    if not head: return dict(output,reason="untrained_head")
    vocabulary=bundle.get("vocabulary",[])
    if len(vocabulary)>FEATURE_CAP_R4 or set(head["weights"])!=set(vocabulary):
        return dict(output,reason="invalid_bundle")
    z=head["bias"]+sum(head["weights"][key]*extracted["features"].get(key,0.) for key in vocabulary)
    if type(z) not in (int,float) or not -float("inf")<z<float("inf"): return dict(output,reason="invalid_bundle")
    return dict(output,raw_score=z,completion_candidate="complete" if z>=0 else "unfinished",reason="uncalibrated")
