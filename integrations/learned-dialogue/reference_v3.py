"""Pure offline source/reference admission. No I/O, value normalization or state change.

Registry/pending are independently sourced deterministic wrapper arguments.
Constructing a TrustedCallV3 or passing two equal copies proves no authentication.
No such lossless/fresh Freya ingress is claimed by this prototype.
"""
import re
from context_v2 import BindingContext, InputRejected, neutral_v2, _check_snapshot


class TrustedCallV3:
    __slots__=("binding_context","call_local_id","source_event_id","event_ordinal","text","complete_transport","question_identity","target_mapping")
    def __init__(self,binding_context,call_local_id,source_event_id,event_ordinal,text,complete_transport,question_identity=None,target_mapping=None):
        if not isinstance(binding_context,BindingContext) or type(call_local_id) is not str or not call_local_id or source_event_id != binding_context.binding()["turn_id"] or type(event_ordinal) is not int or event_ordinal < 0 or type(text) is not str or complete_transport is not True:
            raise InputRejected("Independent complete current user-event context required")
        if question_identity is not None and (type(question_identity) is not tuple or len(question_identity)!=3 or any(type(v) is not str or not v for v in question_identity)):
            raise InputRejected("Independent question ID/speech ID/role tuple required")
        if target_mapping is not None and (type(target_mapping) is not tuple or any(type(v) is not tuple or len(v)!=2 or type(v[0]) is not int or type(v[1]) is not str or not v[1] for v in target_mapping)):
            raise InputRejected("Independent immutable index/target ID mapping required")
        if target_mapping is not None and (len({v[0] for v in target_mapping})!=len(target_mapping) or len({v[1] for v in target_mapping})!=len(target_mapping) or any(v[0]<0 for v in target_mapping)):
            raise InputRejected("Independent target map must be a nonnegative bijection")
        for key,value in zip(self.__slots__,(binding_context,call_local_id,source_event_id,event_ordinal,text,complete_transport,question_identity,target_mapping)):
            object.__setattr__(self,key,value)
    def __setattr__(self,key,value):
        raise InputRejected("Trusted current source fixture is immutable")


def validate_ingress_v3(snapshot, trusted):
    if not isinstance(trusted,TrustedCallV3):
        raise InputRejected("No independent trusted source context; no fabricated binding")
    reason=_check_snapshot(snapshot)
    if reason:
        return reason
    if snapshot["phase"] not in {"callback","payment","readback","recipient","security","support"} or snapshot["question"]["role"] not in {"amount","callback","date","none","offer","payment","readback","recipient","security","support"}:
        return "unknown_schema"
    if snapshot["call_local_id"] != trusted.call_local_id or {k:snapshot[k] for k in trusted.binding_context.binding()} != trusted.binding_context.binding():
        return "stale_binding"
    if snapshot["utterance"]["text"] != trusted.text or snapshot["utterance"]["source_turn_id"] != trusted.source_event_id:
        return "untrusted_text"
    if trusted.question_identity is not None and tuple(snapshot["question"].get(k) for k in ("question_id","spoken_turn_id","role")) != trusted.question_identity:
        return "stale_binding"
    targets=[t.get("index") for t in snapshot["targets"] if type(t) is dict]
    if len(targets) != len(snapshot["targets"]) or any(type(i) is not int or i < 0 for i in targets) or len(targets) != len(set(targets)):
        return "unknown_target"
    if any(type(i) is not int or i not in targets for i in snapshot["question"].get("target_indices",[])):
        return "unknown_target"
    if trusted.target_mapping is not None and set((t.get("index"),t.get("product_id")) for t in snapshot["targets"]) != set(trusted.target_mapping):
        return "unknown_target"
    return None


def _failed(kind,reason,checks=None):
    return {"candidate_id_or_null":None,"reference_kind":kind,"reason":reason,"dependency_checks":checks or [],"diagnosis_only":True}


def resolve_reference_v3(snapshot,label,trusted,registry,authoritative_state,new_terms=False):
    """Historical speech revision3/current4 can be fresh; component tokens decide.

    Opaque source event IDs are never sorted or parsed as counters. Registry entries
    are not constructed from the current snapshot. Values are never returned.
    """
    reason=validate_ingress_v3(snapshot,trusted)
    if reason: return _failed(None,reason)
    if trusted.question_identity is None or trusted.target_mapping is None:
        return _failed(None,"unresolved_reference",["independent_question_and_target_identity_unavailable"])
    role=snapshot["question"]["role"]
    if label == "offer_acceptance" and role == "offer":
        kind="offer"; reference_id=snapshot["question"].get("spoken_offer_id")
    elif label == "readback_affirmation" and role == "readback":
        kind="readback"; reference_id=(snapshot.get("active_readback") or {}).get("readback_id")
    else:
        return _failed(None,"unresolved_reference")
    if new_terms:
        return _failed(kind,"stale_binding",["same_turn_new_terms_blocks_prior_confirmation"])
    if type(reference_id) is not str or not 1 <= len(reference_id) <= 128:
        return _failed(kind,"unresolved_reference")
    try:
        if kind=="readback":
            raw=snapshot["active_readback"]
            if type(raw) is not dict or raw.get("valid") is not True or raw.get("completed_speech") is not True:
                return _failed(kind,"unresolved_reference")
        else:
            matches=[r for r in snapshot["spoken_offers"] if type(r) is dict and r.get("offer_id")==reference_id]
            if len(matches)!=1 or matches[0].get("superseded") is not False:
                return _failed(kind,"unresolved_reference")
            raw=matches[0]
        raw_revision=raw.get("state_revision")
        raw_speech=raw.get("spoken_turn_id")
        if type(raw_revision) is not int or raw_revision<0 or type(raw_speech) is not str or not raw_speech:
            return _failed(kind,"unresolved_reference",["raw_historical_source_anchor_missing"])
        events=registry["source_events"]; references=registry["references"]
        ids=[event["event_id"] for event in events]
        rids=[entry["reference_id"] for entry in references]
        if any(type(i) is not str or not 1<=len(i)<=128 for i in ids+rids):
            return _failed(kind,"unresolved_reference",["invalid_registry_id"])
        if len(ids) != len(set(ids)) or len(rids) != len(set(rids)):
            return _failed(kind,"unresolved_reference",["duplicate_registry_id"])
        current=next(event for event in events if event["event_id"]==trusted.source_event_id)
        if current["call_local_id"] != trusted.call_local_id or current["role"] != "user" or type(current["ordinal"]) is not int or current["ordinal"] != trusted.event_ordinal or current["completed"] is not True:
            return _failed(kind,"stale_binding")
        entry=next(entry for entry in references if entry["reference_id"]==reference_id)
        speech=next(event for event in events if event["event_id"]==entry["spoken_event_id"])
        revision=entry["created_state_revision"]
        if type(revision) is not int or revision < 0 or revision > snapshot["state_revision"]:
            return _failed(kind,"stale_binding",["explicit_historical_revision_required"])
        if raw_revision!=revision or raw_speech!=entry["spoken_event_id"] or entry["call_local_id"] != trusted.call_local_id or speech["call_local_id"] != trusted.call_local_id:
            return _failed(kind,"stale_binding")
        if entry["kind"] != kind or entry["question_id"] != snapshot["question"].get("question_id"):
            return _failed(kind,"unresolved_reference")
        if speech["role"] != "assistant" or type(speech["ordinal"]) is not int or not speech["ordinal"] < trusted.event_ordinal or speech["completed"] is not True or entry["completed_speech"] is not True or entry["superseded_or_invalidated"] is not False:
            return _failed(kind,"stale_binding")
        if snapshot["question"].get("spoken_turn_id") != entry["spoken_event_id"] or any(entry[k] != snapshot[k] for k in ("policy_hash","api_hash")):
            return _failed(kind,"stale_binding")
        targets=entry["target_ids"]
        if not targets or len(targets) != len(set(targets)) or any(t not in authoritative_state["targets"] for t in targets):
            return _failed(kind,"unknown_target")
        expected_indices={authoritative_state["targets"][t]["target_index"] for t in targets}
        independent_indices={tid:index for index,tid in trusted.target_mapping}
        if any(type(authoritative_state["targets"][tid]["target_index"]) is not int or authoritative_state["targets"][tid]["target_index"]!=independent_indices.get(tid) for tid in targets):
            return _failed(kind,"unknown_target",["state_target_map_conflicts_with_independent_identity"])
        raw_indices=raw.get("target_indices")
        if type(raw_indices) is not list or any(type(i) is not int for i in raw_indices) or len(raw_indices)!=len(set(raw_indices)):
            return _failed(kind,"unknown_target",["raw_target_indices_invalid"])
        if expected_indices != set(snapshot["question"].get("target_indices",[])) or expected_indices!=set(raw.get("target_indices",[])):
            return _failed(kind,"unknown_target")
        dependencies=entry["dependency_component_tokens"]
        specific=entry["base_component_tokens" if kind=="offer" else "readback_component_tokens"]
        terms=entry["immutable_terms" if kind=="offer" else "exact_spoken_terms"]
        if dependencies != specific or set(dependencies) != set(targets) or set(terms) != set(targets):
            return _failed(kind,"unresolved_reference",["dependency_set_missing"])
        if kind=="readback":
            raw_tokens=raw.get("component_revisions")
            expected_raw={str(authoritative_state["targets"][t]["target_index"]):dict(dependencies[t]) for t in targets}
            if type(raw_tokens) is not dict or raw_tokens!=expected_raw:
                return _failed(kind,"unresolved_reference",["raw_readback_dependency_set_mismatch"])
        checks=[]
        for target in targets:
            state=authoritative_state["targets"][target]
            if kind=="offer" and state.get("current_offer_id") != reference_id:
                return _failed(kind,"stale_binding",["offer_is_not_current_target_offer"])
            if type(entry["target_disposition_epochs"][target]) is not str or not entry["target_disposition_epochs"][target] or entry["target_disposition_epochs"][target] != state["disposition_epoch"]:
                return _failed(kind,"stale_binding")
            tokens=dependencies[target]
            if not tokens or set(tokens) != set(terms[target]):
                return _failed(kind,"unresolved_reference",["term_component_tokens_missing"])
            for component,token in tokens.items():
                current_token=state["components"][component]["revision"]
                if type(token) is not str or not token or type(current_token) is not str or not current_token:
                    return _failed(kind,"unresolved_reference",checks+[target+":"+component+":invalid_token_type"])
                if token != current_token:
                    return _failed(kind,"stale_binding",checks+[target+":"+component+":changed_or_missing_token"])
                checks.append(target+":"+component+":matched")
        if kind=="readback" and (entry["active_readback_id"] != reference_id or authoritative_state.get("active_readback_id") != reference_id):
            return _failed(kind,"stale_binding")
        return {"candidate_id_or_null":reference_id,"reference_kind":kind,"reason":None,"dependency_checks":checks,"diagnosis_only":True}
    except (KeyError,TypeError,ValueError,StopIteration,AttributeError):
        return _failed(kind,"unresolved_reference")


def check_deferred_refusal_v3(event,state,registry):
    """Typed opaque revisions, target epoch and exact offer/event identity only."""
    try:
        target=state["targets"][event["target_id"]]
        if type(event["disposition_epoch"]) is not str or not event["disposition_epoch"] or event["disposition_epoch"] != target["disposition_epoch"]:
            return {"matches_current_target":False,"reason":"stale_binding","diagnosis_only":True}
        events=[e for e in registry["source_events"] if e["event_id"]==event["source_event_id"]]
        offers=[r for r in registry["references"] if r["reference_id"]==event["offer_id"] and r["kind"]=="offer"]
        if len(events)!=1 or len(offers)!=1 or event["offer_id"] != target.get("current_offer_id") or events[0]["role"] != "user" or events[0]["call_local_id"] != offers[0]["call_local_id"]:
            return {"matches_current_target":False,"reason":"unresolved_reference","diagnosis_only":True}
        tokens=event["component_tokens"]
        valid=bool(tokens) and all(type(token) is str and token and type(target["components"][name]["revision"]) is str and token==target["components"][name]["revision"] for name,token in tokens.items())
        return {"matches_current_target":valid,"reason":None if valid else "stale_binding","diagnosis_only":True}
    except (KeyError,TypeError,ValueError):
        return {"matches_current_target":False,"reason":"unresolved_reference","diagnosis_only":True}
