"""New R4 pure bound-neutral wire plus typed/window diagnostics; no refit."""
from context_v2 import neutral_v2,InputRejected
from reference_v3 import TrustedCallV3,validate_ingress_v3,resolve_reference_v3
from detector_r4 import detect_candidates_r4
from window_r4 import score_date_r4
from guard_v3 import wire_errors_v3

def predict_r4(snapshot,trusted,registry,state,schema,source_admission=None,date_bundle=None):
    if not isinstance(trusted,TrustedCallV3): raise InputRejected("Independent source binding required")
    try:
        reason=validate_ingress_v3(snapshot,trusted)
        wire=neutral_v2(trusted.binding_context,reason or "untrained_head")
        if reason: return wire,{"ingress_reason":reason,"qualified":False}
        security_context=snapshot["phase"]=="security" or snapshot["question"]["role"]=="security" or snapshot["question"].get("security_field") is not None
        detector=detect_candidates_r4(snapshot["utterance"]["text"],"security" if security_context else snapshot["question"]["role"],snapshot["targets"])
        if security_context:
            return wire,{"detector":detector,"date_scores":[],"surface_features_masked":True,"qualified":False,
                         "reference":{"candidate_id_or_null":None,"reason":"untrained_head"}}
        scores=[score_date_r4(snapshot,c,source_admission,date_bundle) for c in detector["candidates"] if c["kind"]=="date"]
        label={"readback":"readback_affirmation","offer":"offer_acceptance"}.get(snapshot["question"]["role"],"unknown")
        assessment=(source_admission or {}).get("scoped_terms_assessment")
        binding=trusted.binding_context.binding()
        assessment_qualified=type(assessment) is dict and assessment.get("qualified") is True and all(type(assessment.get(k)) is type(value) and assessment.get(k)==value for k,value in dict(binding,call_local_id=trusted.call_local_id,source_event_id=trusted.source_event_id).items())
        explicit_unchanged=assessment_qualified and assessment.get("has_new_terms") is False
        actual_terms_candidates=bool(detector["candidates"] or detector.get("nondate_candidates"))
        historical=resolve_reference_v3(snapshot,label,trusted,registry,state,False)
        reference=dict(historical)
        # Detector recall can never prove a whole delivered turn unchanged.
        # Unknown source-scoped assessment blocks current-reference eligibility.
        if not explicit_unchanged or actual_terms_candidates:
            reference.update(candidate_id_or_null=None,reason="unresolved_reference" if not explicit_unchanged else "stale_binding",
                             scoped_has_new_terms=False if explicit_unchanged else "unknown",
                             independent_scoped_assessment_qualified=assessment_qualified)
        # Unqualified semantic/consent producer never populates wire candidate ID,
        # even when a historical reference is identified independently.
        errors=wire_errors_v3(wire,snapshot,schema)
        return wire,{"detector":detector,"date_scores":scores,"reference":reference,"historical_reference":historical,
                     "wire_errors":errors,"scoped_has_new_terms":False if explicit_unchanged else "unknown",
                     "all_abstain":True,"qualified":False,"normalization":"not_implemented",
                     "primary_act_target_polarity_untrained":True}
    except (KeyError,TypeError,ValueError,AttributeError,IndexError,OverflowError):
        return neutral_v2(trusted.binding_context,"runtime_failure"),{"qualified":False,"runtime_failure":True}
