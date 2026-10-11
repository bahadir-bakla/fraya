"""Pinned source-only V6 preparation. No supervision, admission or fitting.

Two explicitly authorized packet profiles are accepted as received. They do not
silently become the strict V5 author/provenance schema or trusted live ingress.
"""
import hashlib
import json
import re
import types
from collections import Counter
from pathlib import Path

from alignment_v5 import replay_surface_admission
from context_r4 import predict_r4
from context_v2 import BindingContext
from detector_r4 import detect_candidates_r4, DETECTOR_R4_VERSION
from primary_cpu_v5 import features as primary_features, VERSION as PRIMARY_FEATURE_VERSION
from reference_v3 import TrustedCallV3
from window_r4 import date_features_r4, FEATURE_R4_VERSION

ROOT = Path(__file__).resolve().parents[2]
VERSION = "source_only_runtime_preparation.v6.0"
PACKETS = {
    "research/customer-benchmark/semantic-v6-extension/label-free-train-packet.json":
        ("3992ab7f7f21bfc89c9e4a78fc00854cae286e3551cd2b956aa82b605a768bf4",72,"label_free_source_review_packet.v6"),
    "research/customer-benchmark/semantic-v6-peer-extension/blind-source-2f52b35f12d7.json":
        ("84dda0e5cda28c532bbbd2e73a7c4c2c6643ad2aefe16752a2ff979dfc8207cd",60,"blind_source_train_packet.peer.v1"),
}
BASELINES = {
    "integrations/learned-dialogue/runtime_frozen_r4.py":"def3b2bf1934f269424a069c66db6424bfb5a2a2e455e9e63a8001062854e246",
    "integrations/learned-dialogue/detector_r4.py":"1451f161bfb40fc1c2091e96b3802d9665f3ecfb04eed14c18fb3c14acc2a3c0",
    "integrations/learned-dialogue/window_r4.py":"ef1e8c75ba1a587467825cd77469e1de1fabd4080dfc32459b957d979e3cc8a4",
    "analysis/night-learned-dialogue.v5.next-data-interface.json":"c751fe65f228f1dc65014aca25f1459f67fdf9d1237a1c87f13e61645d74a1e4",
    "integrations/learned-dialogue/runtime_primary_contract_v5.py":"098521639294cd1281d4acf486dd95c48251d1d01323979c8371f770356362f2",
}


class SourceRejected(ValueError):
    pass


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode("utf-8")


def strict_json(raw):
    def pairs(values):
        d = {}
        for k,v in values:
            if k in d: raise SourceRejected("duplicate_json_key")
            d[k] = v
        return d
    def bad(_): raise SourceRejected("nonfinite_json_number")
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=bad)


def require(condition, reason):
    if not condition: raise SourceRejected(reason)


def pointer(value, path):
    require(type(path) is str and path.startswith("/"),"invalid_pointer")
    try:
        for piece in path[1:].split("/"):
            piece = piece.replace("~1","/").replace("~0","~")
            value = value[int(piece)] if isinstance(value,list) else value[piece]
        return value
    except (KeyError,IndexError,ValueError,TypeError):
        raise SourceRejected("unresolvable_pointer") from None


def span_binding(packet_path,packet_sha,index,text,a,b):
    require(type(a) is int and type(b) is int and 0<=a<b<=len(text),"span_coordinates")
    return {"source_packet":packet_path,"source_packet_raw_sha256":packet_sha,
            "raw_field_path":f"/records/{index}/input/utterance/text","offset_unit":"python_unicode_codepoints",
            "char_start":a,"char_end":b,"text":text[a:b],"utf8_byte_start":len(text[:a].encode("utf-8")),
            "utf8_byte_end":len(text[:b].encode("utf-8"))}


def check_span(span,packet):
    text = pointer(packet,span["raw_field_path"])
    a,b = span["char_start"],span["char_end"]
    require(type(text) is str and type(a) is int and type(b) is int and 0<=a<b<=len(text),"span_coordinates")
    require(span["offset_unit"]=="python_unicode_codepoints" and text[a:b]==span["text"],"span_exact_text")
    require(span["utf8_byte_start"]==len(text[:a].encode("utf-8")) and
            span["utf8_byte_end"]==len(text[:b].encode("utf-8")),"span_utf8")
    require(text.encode("utf-8")[span["utf8_byte_start"]:span["utf8_byte_end"]]==span["text"].encode("utf-8"),"span_utf8")


def validate_snapshot(s):
    required = {"schema_version","call_local_id","turn_id","state_revision","policy_hash","api_hash","utterance",
                "phase","question","targets","pending","spoken_offers","active_readback"}
    require(type(s) is dict and set(s)==required,"snapshot_keys")
    require(s["schema_version"]=="semantic_input.v1" and type(s["state_revision"]) is int and s["state_revision"]>=0,"snapshot_binding")
    for k in ("call_local_id","turn_id","phase"):
        require(type(s[k]) is str and bool(s[k]),"snapshot_string")
    require(len(s["turn_id"])<=128,"turn_id_limit")
    for k in ("policy_hash","api_hash"):
        require(type(s[k]) is str and re.fullmatch(r"[0-9a-f]{64}",s[k]) is not None,"hash_syntax")
    u = s["utterance"]
    require(set(u)=={"text","source","source_turn_id","complete_transport","offset_unit"},"utterance_keys")
    require(type(u["text"]) is str and 0<len(u["text"])<=4096 and u["source"]=="authored_fixture" and
            u["source_turn_id"]==s["turn_id"] and u["complete_transport"] is True and
            u["offset_unit"]=="python_unicode_codepoints","utterance_source_framing")
    q = s["question"]
    require(type(q) is dict and {"question_id","role","spoken_turn_id","target_indices","text"}<=set(q)
            and set(q)<={"question_id","role","spoken_turn_id","target_indices","text","security_field","spoken_offer_id"},"question_keys")
    require(all(type(q[k]) is str for k in ("question_id","role","spoken_turn_id","text")),"question_strings")
    require(type(s["targets"]) is list and type(s["pending"]) is list,"target_lists")
    known = [t["index"] for t in s["targets"]]
    require(all(type(i) is int and i>=0 for i in known) and len(known)==len(set(known)),"target_indices")
    require(type(q["target_indices"]) is list and all(type(i) is int for i in q["target_indices"])
            and len(set(q["target_indices"]))==len(q["target_indices"]) and set(q["target_indices"])<=set(known),"question_target_mapping")
    for target in s["targets"]:
        require(set(target)=={"index","type","label","product_id"} and
                all(type(target[k]) is str for k in ("type","label","product_id")),"target_shape")
    seen = set()
    for p in s["pending"]:
        require(set(p)=={"target_index","components","unresolved_components"} and p["target_index"] in known
                and p["target_index"] not in seen,"pending_target")
        seen.add(p["target_index"])
        require(set(p["components"])=={"amount","date"},"pending_components")
        for c in p["components"].values():
            require(set(c)=={"status","revision","value","evidence_refs"} and type(c["revision"]) is str
                    and c["status"] in {"absent","complete","unfinished","ambiguous"}
                    and type(c["evidence_refs"]) is list,"component_shape")
    require(s["spoken_offers"]==[] and s["active_readback"] is None,"new_reference_profile_requires_new_schema")


def load_sources(root=ROOT):
    results, all_ids = {}, set()
    for path,(pin,count,profile) in PACKETS.items():
        raw = (Path(root)/path).read_bytes()
        require(sha(raw)==pin,"packet_hash_mismatch:"+path)
        packet = strict_json(raw)
        require(set(packet)=={"collection_id","records","schema_version","split"} and
                packet["schema_version"]==profile and packet["split"]=="train" and
                len(packet["records"])==count,"packet_profile")
        for r in packet["records"]:
            require(set(r)=={"example_id","input"} and type(r["example_id"]) is str and r["example_id"] not in all_ids,"record_identity_or_labels")
            all_ids.add(r["example_id"])
            validate_snapshot(r["input"])
        results[path] = packet
    return results


def frozen_export_helpers(root=ROOT):
    for path,digest in BASELINES.items():
        require(sha((Path(root)/path).read_bytes())==digest,"frozen_baseline_changed:"+path)
    namespace = {}
    exec(compile((Path(root)/"integrations/learned-dialogue/runtime_frozen_r4.py").read_bytes(),"frozen-r4","exec"),namespace)
    helpers, seen = {}, set()
    def walk(f):
        if not isinstance(f,types.FunctionType) or id(f) in seen: return
        seen.add(id(f));helpers[f.__name__] = f
        for cell in f.__closure__ or ():
            try: walk(cell.cell_contents)
            except ValueError: pass
    walk(namespace["predict_context_r4_embedded"])
    primary_ns = {}
    exec(compile((Path(root)/"integrations/learned-dialogue/runtime_primary_contract_v5.py").read_bytes(),"frozen-v5","exec"),primary_ns)
    return namespace["predict_context_r4_embedded"],helpers,primary_ns["features"]


def replay_call(s, model_id):
    """Authored packet replay only. NOT independently authenticated current ingress."""
    context = BindingContext({k:s[k] for k in ("turn_id","state_revision","policy_hash","api_hash")},model_id)
    q = s["question"]
    identity = (q["question_id"],q["spoken_turn_id"],q["role"])
    mapping = tuple((t["index"],t["product_id"]) for t in s["targets"])
    # The ordinal is local replay metadata, not a verified speech timeline.
    t = TrustedCallV3(context,s["call_local_id"],s["utterance"]["source_turn_id"],s["state_revision"],
                      s["utterance"]["text"],True,identity,mapping)
    source = {"call_local_id":t.call_local_id,"source_event_id":t.source_event_id,"event_ordinal":t.event_ordinal,
              "text":t.text,"complete_transport":True,"question_identity":list(identity),
              "target_mapping":[list(x) for x in mapping]}
    return t,source


def prepare(sources, schema, model_id, exported, helpers, exported_primary):
    candidate_rows, feature_rows, summaries = [], [], {}
    for path,packet in sources.items():
        counts = Counter();policy = Counter();api = Counter();phase = Counter();role = Counter()
        for i,r in enumerate(packet["records"]):
            s,q = r["input"],r["input"]["question"]
            text = s["utterance"]["text"]
            admission = replay_surface_admission(s)
            sensitive = s["phase"]=="security" or q["role"]=="security" or q.get("security_field") is not None
            effective_role = "security" if sensitive else q["role"]
            detected = detect_candidates_r4(text,effective_role,s["targets"],q.get("security_field"),"en")
            exported_detected = helpers["detect_candidates_r4"](text,effective_role,s["targets"],q.get("security_field"),"en")
            require(detected==exported_detected,"detector_export_parity")
            counts["detector_native_export_rows"]+=1
            counts["rows"]+=1;counts["rows_with_DATE"]+=int(any(c["kind"]=="date" for c in detected["candidates"]))
            policy[s["policy_hash"]]+=1;api[s["api_hash"]]+=1;phase[s["phase"]]+=1;role[q["role"]]+=1
            input_sha,record_sha = sha(encoded(s)),sha(encoded(r))
            binding = {"example_id":r["example_id"],"source_packet":path,"source_packet_raw_sha256":PACKETS[path][0],
                       "source_record_path":f"/records/{i}","source_record_json_sha256":record_sha,"source_input_json_sha256":input_sha}
            proposed = []
            for c in detected["candidates"]:
                span = span_binding(path,PACKETS[path][0],i,text,c["start"],c["end"])
                check_span(span,packet)
                targets = q["target_indices"] if len(q["target_indices"])==1 else None
                proposed.append({"id":r["example_id"]+":r4:"+c["candidate_id"],"candidate":c,"source_span":span,
                                 "target_indices_hypothesis":targets,"target_binding_reviewed":False,
                                 "candidate_role_reviewed":False,"validity_mask":False,"completion_mask":False,
                                 "reference_mask":False,"normalization_mask":False})
                counts["raw_candidates:"+c["kind"]]+=1
                counts["syntax:"+c.get("syntax_status","not_DATE")]+=1
                if c["kind"]=="date":
                    replay = date_features_r4(s,c,admission)
                    unknown = date_features_r4(s,c,None)
                    require(replay==helpers["date_features_r4"](s,c,admission),"feature_export_parity")
                    require(unknown==helpers["date_features_r4"](s,c,None),"unknown_source_export_parity")
                    require(not unknown["eligible"],"unknown_source_mask")
                    counts["DATE_native_export_feature_pairs"]+=2
                    counts["DATE_replay_feature_eligible"]+=int(replay["eligible"])
                    counts["DATE_mask:"+(replay["reason"] or "replay_eligible_unreviewed")]+=1
                    feature_rows.append({**binding,"candidate_id":proposed[-1]["id"],"head":"date_completion",
                        "feature_version":FEATURE_R4_VERSION,"source_span":span,"replay_features":replay,
                        "unknown_live_source_features":unknown,"loss_mask":False,"label":None})
            counts["overflow_rows"]+=int(detected.get("status")=="overflow")
            p = primary_features(s)
            require(p==exported_primary(s),"primary_feature_export_parity")
            counts["primary_native_export_feature_rows"]+=1
            counts["primary_replay_feature_eligible"]+=int(p["eligible"])
            feature_rows.append({**binding,"head":"primary_is_payment_proposal","feature_version":PRIMARY_FEATURE_VERSION,
                                 "replay_features":p,"live_source_binding":"unqualified","loss_mask":False,"label":None})
            trusted,source = replay_call(s,model_id)
            native = predict_r4(s,trusted,{}, {},schema,None,None)
            embedded = exported(s,trusted.binding_context.binding(),source,{}, {},None,None)
            require(native==embedded,"wire_export_parity")
            wire,side = native
            require(wire["status"]=="abstain" and wire["primary"] is None,"wire_not_abstain")
            require(wire["consent_signal"]["candidate_readback_id"] is None,"reference_must_remain_null")
            counts["wire_native_export_rows"]+=1
            counts["wire_ingress_reason:"+str(side.get("ingress_reason","none"))]+=1
            candidate_rows.append({**binding,"detector_version":DETECTOR_R4_VERSION,"detector_status":detected["status"],
                                  "candidates":proposed,"nondate_candidates":detected.get("nondate_candidates",[]),
                                  "identifier_exclusions":detected.get("identifier_exclusions",[]),
                                  "absence_established":False,"reviewed_canonical_group":None,
                                  "runtime_output":wire,"runtime_diagnostics":side,
                                  "replay_binding_only":True,"live_ingress_authenticated":False})
        summaries[path] = {"counts":dict(counts),"policy_hash_counts":dict(policy),"api_hash_counts":dict(api),
                           "phase_counts":dict(phase),"question_role_counts":dict(role),
                           "strict_V5_collection_schema_conformance":False,
                           "missing_packet_fields_vs_V5":["author_id","license"],
                           "missing_record_fields_vs_V5":["declared_lineage_id","collection_axis","author_provenance"],
                           "hashes_and_descriptors_preserved":True}
    return candidate_rows,feature_rows,summaries


def alignment_contract_v6():
    """Unactivated interface: a new parent-reviewed adapter is required to join."""
    return {"schema_version":"future_alignment_request.v6","status":"no_alignment_before_parent_admission",
            "required_arguments":["separately_parent_reviewed_annotation_schema_raw_and_out_of_band_digest",
                 "two_original_source_reviews_and_adjudication_raw_with_parent_pins","source_packet_raw_pins",
                 "runtime_candidates_raw_and_pinned_vector_digest","runtime_features_raw_and_pinned_vector_digest",
                 "conservative_canonical_alias_map_raw_and_parent_pinned_digest","identifier_only_parent_split_declarations",
                 "NEW_actual_parent_admission_receipt_and_independently_supplied_trust_anchor"],
            "join_key":["source_packet_raw_sha256","source_record_json_sha256","example_id",
                        "raw_field_path","python_unicode_start","python_unicode_end","exact_text","exact_target_set"],
            "rules":["Candidate extraction frozen before supervision; no annotation-dependent features.",
                     "No nearest-boundary, target union, label rewrite or negative from unmatched detection.",
                     "Unknown/superseded target or role remains masked; reference/normalization require independent evidence.",
                     "Current packets contain no lineage metadata; no canonical independence or class-floor counts inferred.",
                     "Old V5 grant does not authorize V6; new supplement admission implementation and exact parent grant required.",
                     "All rows remain TRAIN; no new DEV or qualification access; all loss masks false until admission."]}


def stage_alignment_request_v6(*, parent_reviewed_schema_pin=None, prereview_pins=None,
                               pinned_candidate_vector=None, pinned_feature_vector=None,
                               conservative_canonical_map_pin=None, new_parent_admission_pin=None):
    """Versioned pin-only interface. Does not read or admit annotation contents.

    Pins identify bytes; neither a caller enum nor a receipt's self-hash proves
    parent issuance. A new independently reviewed admission executor is needed
    before the eventual exact join. No such executor is installed by V6 prep.
    """
    bindings = {"parent_reviewed_schema_pin":parent_reviewed_schema_pin,
                "prereview_pins":prereview_pins,"pinned_candidate_vector":pinned_candidate_vector,
                "pinned_feature_vector":pinned_feature_vector,
                "conservative_canonical_map_pin":conservative_canonical_map_pin,
                "new_parent_admission_pin":new_parent_admission_pin}
    return {"schema_version":"staged_alignment_request.v6","bindings":bindings,
            "missing_bindings":[k for k,v in bindings.items() if v is None],
            "annotation_contents_consumed":False,"admitted":False,"loss_masks_enabled":False,
            "qualified":False,"alignment_executor":"pending independently reviewed new parent admission",
            "join_contract":alignment_contract_v6()}
