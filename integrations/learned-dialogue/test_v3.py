"""Independent source/state fixture controls; no annotation or qualification gold."""
import copy
import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from context_v2 import BindingContext,InputRejected
from context_v3 import predict_v3
from reference_v3 import TrustedCallV3,validate_ingress_v3,resolve_reference_v3,check_deferred_refusal_v3
from detector_v3 import detect_candidates_v3,align_candidates_v3
from guard_v3 import wire_errors_v3,schema_errors_v3

HERE=Path(__file__).resolve().parent
MODEL_BLOB=(HERE/"model_v2_final.json").read_bytes()
BUNDLE={"model_id":hashlib.sha256(MODEL_BLOB).hexdigest(),"model":json.loads(MODEL_BLOB)}
SCHEMA=json.loads((HERE/"contract_v2.json").read_text())["schema"]


def fixture(turn_id="u"):
    # Authoritative event/state literals are authored independently of snapshot.
    context=BindingContext({"turn_id":turn_id,"state_revision":4,"policy_hash":"a"*64,"api_hash":"b"*64},BUNDLE["model_id"])
    trusted=TrustedCallV3(context,"independent-call",turn_id,8,"Yes.",True,("question-A","spoken-independent","readback"),((0,"target-A"),(1,"target-B")))
    state={"active_readback_id":"readback-A","targets":{"target-A":{"target_index":0,"disposition_epoch":"epoch-A","current_offer_id":"offer-A","components":{"amount":{"revision":"amount-opaque","status":"validated"},"date":{"revision":"date-opaque","status":"validated"}}},
                                                          "target-B":{"target_index":1,"disposition_epoch":"epoch-B","components":{"amount":{"revision":"sibling-opaque","status":"missing"}}}}}
    registry={"source_events":[{"event_id":"spoken-independent","call_local_id":"independent-call","role":"assistant","ordinal":7,"completed":True},
                               {"event_id":turn_id,"call_local_id":"independent-call","role":"user","ordinal":8,"completed":True}],
              "references":[{"call_local_id":"independent-call","reference_id":"readback-A","kind":"readback","created_state_revision":3,
                             "spoken_event_id":"spoken-independent","question_id":"question-A","completed_speech":True,"policy_hash":"a"*64,"api_hash":"b"*64,
                             "target_ids":["target-A"],"dependency_component_tokens":{"target-A":{"amount":"amount-opaque","date":"date-opaque"}},
                             "readback_component_tokens":{"target-A":{"amount":"amount-opaque","date":"date-opaque"}},
                             "exact_spoken_terms":{"target-A":{"amount":"fictional-term","date":"fictional-term"}},
                             "target_disposition_epochs":{"target-A":"epoch-A"},"superseded_or_invalidated":False,"active_readback_id":"readback-A"}]}
    snapshot={"schema_version":"semantic_input.v1","call_local_id":"independent-call","turn_id":turn_id,"state_revision":4,"policy_hash":"a"*64,"api_hash":"b"*64,
              "utterance":{"text":"Yes.","source":"authored_fixture","source_turn_id":turn_id,"complete_transport":True,"offset_unit":"python_unicode_codepoints"},
              "phase":"readback","question":{"role":"readback","question_id":"question-A","spoken_turn_id":"spoken-independent","target_indices":[0]},
              "targets":[{"index":0,"product_id":"target-A","type":"credit_card"},{"index":1,"product_id":"target-B","type":"loan"}],
              "pending":[],"spoken_offers":[],"active_readback":{"readback_id":"readback-A","state_revision":3,"completed_speech":True,
              "valid":True,"spoken_turn_id":"spoken-independent","target_indices":[0],"component_revisions":{"0":{"amount":"amount-opaque","date":"date-opaque"}}}}
    return snapshot,trusted,registry,state


class ReferenceTests(unittest.TestCase):
    def test_raw_boolean_target_is_not_integer_identity(self):
        args=list(fixture()); args[0]["active_readback"]["target_indices"]=[False]
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_independent_state_target_map_conflict_blocks(self):
        args=list(fixture()); args[3]["targets"]["target-A"]["target_index"]=False
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_duplicate_trusted_target_mapping_rejected(self):
        s,t,r,p=fixture()
        with self.assertRaises(InputRejected):
            TrustedCallV3(t.binding_context,t.call_local_id,t.source_event_id,8,t.text,True,
                          t.question_identity,((0,"target-A"),(0,"target-B")))
    def test_raw_anchor_missing_revision_blocks(self):
        args=list(fixture()); del args[0]["active_readback"]["state_revision"]
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_raw_anchor_changed_speech_blocks(self):
        args=list(fixture()); args[0]["active_readback"]["spoken_turn_id"]="wrong"
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_raw_readback_missing_dependency_blocks(self):
        args=list(fixture()); del args[0]["active_readback"]["component_revisions"]["0"]["date"]
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_raw_readback_uncompleted_blocks(self):
        args=list(fixture()); args[0]["active_readback"]["completed_speech"]=False
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_target_mapping_payload_mutation_blocks(self):
        args=list(fixture()); args[0]["targets"][0]["product_id"]="other-target"
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_empty_speech_event_is_not_completed_reference(self):
        args=list(fixture()); args[2]["source_events"][0]["event_id"]=""
        args[2]["references"][0]["spoken_event_id"]=""
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_question_identity_mutation_is_rejected(self):
        args=list(fixture()); args[0]["question"]["question_id"]="payload-only-new-question"
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def resolve(self,args,label="readback_affirmation",new_terms=False):
        s,t,r,p=args; return resolve_reference_v3(s,label,t,r,p,new_terms)
    def test_earlier_completed_revision_is_valid(self):
        self.assertEqual(self.resolve(fixture())["candidate_id_or_null"],"readback-A")
    def test_changed_same_value_token_is_stale(self):
        args=list(fixture()); args[3]["targets"]["target-A"]["components"]["amount"]["revision"]="amount-new"
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_unrelated_sibling_change_keeps_local_reference(self):
        args=list(fixture()); args[3]["targets"]["target-B"]["components"]["amount"]["revision"]="new-sibling"
        self.assertEqual(self.resolve(args)["candidate_id_or_null"],"readback-A")
    def test_missing_revision_never_defaults_zero(self):
        args=list(fixture()); del args[2]["references"][0]["created_state_revision"]
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_bool_revision_rejected(self):
        args=list(fixture()); args[2]["references"][0]["created_state_revision"]=True
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_future_revision(self):
        args=list(fixture()); args[2]["references"][0]["created_state_revision"]=5
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_uncompleted_speech(self):
        args=list(fixture()); args[2]["source_events"][0]["completed"]=False
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_speech_after_user(self):
        args=list(fixture()); args[2]["source_events"][0]["ordinal"]=9
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_duplicate_event_id(self):
        args=list(fixture()); args[2]["source_events"].append(copy.deepcopy(args[2]["source_events"][0]))
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_cross_call(self):
        args=list(fixture()); args[2]["references"][0]["call_local_id"]="other-call"
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_policy_mismatch(self):
        args=list(fixture()); args[2]["references"][0]["policy_hash"]="c"*64
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_payload_only_text_mutation(self):
        args=list(fixture()); args[0]["utterance"]["text"]="Yes, actually tomorrow."
        self.assertEqual(validate_ingress_v3(args[0],args[1]),"untrusted_text")
    def test_unavailable_source_wrapper(self):
        with self.assertRaises(InputRejected): validate_ingress_v3({},None)
    def test_same_turn_new_terms(self):
        self.assertIsNone(self.resolve(fixture(),new_terms=True)["candidate_id_or_null"])
    def test_offer_not_readback_pointer(self):
        args=list(fixture()); args[0]["question"]["spoken_offer_id"]="readback-A"
        args[0]["active_readback"]=None
        self.assertIsNone(self.resolve(args)["candidate_id_or_null"])
    def test_offer_base_tokens_do_not_require_old_and_new_terms_equal(self):
        args=list(fixture()); s,t,r,p=args
        s["question"].update(role="offer",spoken_offer_id="offer-A")
        t=TrustedCallV3(t.binding_context,"independent-call","u",8,"Yes.",True,("question-A","spoken-independent","offer"),((0,"target-A"),(1,"target-B")))
        args[1]=t
        entry=r["references"][0]; entry.update(reference_id="offer-A",kind="offer",base_component_tokens=entry["dependency_component_tokens"],immutable_terms={"target-A":{"amount":"adjusted-fictional-amount","date":"adjusted-fictional-date"}})
        s["spoken_offers"]=[{"offer_id":"offer-A","spoken_turn_id":"spoken-independent","state_revision":3,"superseded":False,"target_indices":[0]}]
        self.assertEqual(self.resolve(args,"offer_acceptance")["candidate_id_or_null"],"offer-A")
    def test_no_lexical_turn_id_order(self):
        args=list(fixture("000-current")); args[2]["source_events"][0]["event_id"]="zzz-prior"
        args[2]["references"][0]["spoken_event_id"]="zzz-prior"; args[0]["question"]["spoken_turn_id"]="zzz-prior"
        args[0]["active_readback"]["spoken_turn_id"]="zzz-prior"
        t=args[1]; args[1]=TrustedCallV3(t.binding_context,"independent-call","000-current",8,"Yes.",True,("question-A","zzz-prior","readback"),((0,"target-A"),(1,"target-B")))
        self.assertEqual(self.resolve(args)["candidate_id_or_null"],"readback-A")
    def test_opaque_refusal_token_and_epoch(self):
        s,t,r,p=fixture(); r["references"][0].update(kind="offer",reference_id="offer-A")
        event={"target_id":"target-A","disposition_epoch":"epoch-A","offer_id":"offer-A","source_event_id":"u","component_tokens":{"amount":"amount-opaque"}}
        self.assertTrue(check_deferred_refusal_v3(event,p,r)["matches_current_target"])
        event["component_tokens"]["amount"]=1
        self.assertFalse(check_deferred_refusal_v3(event,p,r)["matches_current_target"])
        event["component_tokens"]["amount"]="amount-opaque"; p["targets"]["target-A"]["disposition_epoch"]="new-voluntary-proposal"
        self.assertFalse(check_deferred_refusal_v3(event,p,r)["matches_current_target"])


class DetectorTests(unittest.TestCase):
    def spans(self,text,kind):
        return [text[c["start"]:c["end"]] for c in detect_candidates_v3(text)["candidates"] if c["kind"]==kind]
    def test_card_suffix_not_amount(self): self.assertEqual(self.spans("The card ending 4628.","amount"),[])
    def test_real_four_digit_amount_and_identifier(self): self.assertEqual(self.spans("I can pay 4628 for card ending 4628.","amount"),["4628"])
    def test_time_not_amount(self): self.assertEqual(self.spans("At 12:30 pm.","amount"),[])
    def test_amount_plus_time(self): self.assertEqual(self.spans("I can pay 1200 at 12:30 pm.","amount"),["1200"])
    def test_date_numerals_not_money(self): self.assertEqual(self.spans("October 16, 2026.","amount"),[])
    def test_complete_vague_date(self):
        d=detect_candidates_v3("I can pay next week."); c=next(c for c in d["candidates"] if c["kind"]=="date")
        self.assertEqual(c["completion_hint"],"complete_expression_unparsed")
    def test_unfinished_date(self): self.assertEqual(self.spans("I can pay on...","date"),["on..."])
    def test_unrelated_tail_preserves_date(self):
        d=detect_candidates_v3("Friday, but the time is..."); self.assertEqual(next(c for c in d["candidates"] if c["kind"]=="date")["clause_id_or_unknown"],"c0")
    def test_negation_not_global_veto(self): self.assertEqual(self.spans("Do not call me. I can pay 137.","amount"),["137"])
    def test_multiple_corrections_retained(self): self.assertEqual(self.spans("I can pay 137; actually pay 245.","amount"),["137","245"])
    def test_security_without_descriptor_no_whole_turn(self):
        d=detect_candidates_v3("four two; why are you calling?","security"); self.assertEqual(d["candidates"],[]); self.assertTrue(d["surface_features_masked"])
    def test_security_exact_field_only(self):
        d=detect_candidates_v3("four two; why are you calling?","security",security_fields=[{"start":0,"end":8,"source_bound":True}])
        self.assertEqual((d["candidates"][0]["start"],d["candidates"][0]["end"]),(0,8))
    def test_unknown_language_unsupported(self): self.assertEqual(detect_candidates_v3("cuma","none",locale="tr")["status"],"unsupported_context")
    def test_no_candidate_not_absence(self): self.assertFalse(detect_candidates_v3("something unfamiliar")["absence_established"])
    def test_overflow_keeps_full_count(self):
        d=detect_candidates_v3(" ".join("pay "+str(i) for i in range(25))); self.assertEqual(d["status"],"overflow"); self.assertEqual(d["candidate_count"],25)
    def test_exact_alignment_not_nearest(self):
        d=detect_candidates_v3("pay 137"); a=align_candidates_v3(d,[{"kind":"amount","start":3,"end":7,"presence_mask":True,"completion_mask":True,"completion":"complete"}])
        self.assertEqual(a["missed_reviewed_component_indices"],[0]); self.assertFalse(a["rows"][0]["completion_mask"])
    def test_absence_negatives_need_review(self):
        d=detect_candidates_v3("pay 137"); self.assertFalse(align_candidates_v3(d,[])["rows"][0]["validity_mask"])
        self.assertFalse(align_candidates_v3(d,[],{"amount":True})["rows"][0]["validity_label"])


class RuntimeTests(unittest.TestCase):
    def test_qualifier_overflow_reports_full_coverage(self):
        s,t,r,p=fixture(); text=" ".join(["maybe"]*25)
        s["utterance"]["text"]=text
        t=TrustedCallV3(t.binding_context,t.call_local_id,t.source_event_id,8,text,True,t.question_identity,t.target_mapping)
        wire,side=predict_v3(s,BUNDLE,t,r,p,SCHEMA)
        self.assertEqual(wire["status"],"abstain"); self.assertTrue(side["overflow"])
        self.assertEqual(side["qualifier_count"],25); self.assertEqual(len(side["qualifier_coverage"]),25)
    def test_mixed_security_descriptor_masks_global_heads(self):
        s,t,r,p=fixture(); s["question"]["role"]="payment"
        t=TrustedCallV3(t.binding_context,t.call_local_id,t.source_event_id,8,t.text,True,
                        ("question-A","spoken-independent","payment"),t.target_mapping)
        wire,side=predict_v3(s,BUNDLE,t,r,p,SCHEMA,security_fields=[{"start":0,"end":3,"source_bound":True}])
        self.assertIsNone(wire["primary"]); self.assertTrue(side["surface_features_masked"])
    def test_no_actual_date_fit_without_review(self):
        from candidate_v3 import fit_date_candidates_v3
        with self.assertRaises(ValueError): fit_date_candidates_v3([], {})
    def test_no_candidate_table_fallback_to_author_labels(self):
        from candidate_v3 import prepare_reviewed_candidate_table_v3
        s,t,r,p=fixture()
        source=[{"example_id":"fixture","split":"train","lineage_group_id":"root","input":s}]
        table,audits=prepare_reviewed_candidate_table_v3(source,{},{"root":"root"})
        self.assertEqual(table,[]); self.assertIn("missing",audits[0]["reason"])
    def test_local_candidate_right_context_excludes_unrelated_clause(self):
        from candidate_v3 import local_candidate_features_v3
        s,t,r,p=fixture(); s["utterance"]["text"]="pay Friday, but security code is secretword"
        candidate={"kind":"date","name":"date","start":4,"end":10}
        features=local_candidate_features_v3(s,candidate)
        self.assertFalse(any("secretword" in key for key in features))
    def test_long_turn_ids_valid_wire(self):
        for length in (1,125,126,128):
            s,t,r,p=fixture("u"*length); wire,diag=predict_v3(s,BUNDLE,t,r,p,SCHEMA)
            self.assertEqual(wire["status"],"abstain"); self.assertEqual(wire["clauses"][0]["clause_id"],"c0")
            self.assertEqual(wire_errors_v3(wire,s,SCHEMA),[])
    def test_no_candidate_components_omitted(self):
        s,t,r,p=fixture(); wire,diag=predict_v3(s,BUNDLE,t,r,p,SCHEMA)
        self.assertEqual(wire["clauses"][0]["components"],[]); self.assertEqual(wire["clauses"][0]["amount_scope"],"unresolved")
    def test_malformed_snapshot_neutral_bound(self):
        s,t,r,p=fixture(); wire,diag=predict_v3({},BUNDLE,t,r,p,SCHEMA)
        self.assertEqual(wire["binding"],t.binding_context.binding()); self.assertIsNone(wire["primary"])
    def test_nonfinite_model_neutral(self):
        s,t,r,p=fixture(); bad=copy.deepcopy(BUNDLE); bad["model"]["heads"]["primary"]["bias"][0]=float("nan")
        wire,diag=predict_v3(s,bad,t,r,p,SCHEMA); self.assertIsNone(wire["primary"])
    def test_pure_no_side_effects(self):
        s,t,r,p=fixture()
        with patch("builtins.open",side_effect=AssertionError("I/O")),patch("socket.socket",side_effect=AssertionError("socket")),patch("subprocess.Popen",side_effect=AssertionError("process")):
            wire,diag=predict_v3(s,BUNDLE,t,r,p,SCHEMA); self.assertEqual(wire["status"],"abstain")
    def test_unknown_phase_neutral(self):
        s,t,r,p=fixture(); s["phase"]="made-up"; wire,diag=predict_v3(s,BUNDLE,t,r,p,SCHEMA)
        self.assertEqual(wire["abstentions"][0]["reason"],"unknown_schema")
    def test_guard_rejects_nan_and_duplicate_components(self):
        s,t,r,p=fixture(); wire,diag=predict_v3(s,BUNDLE,t,r,p,SCHEMA); wire["primary"]["score"]=float("nan")
        self.assertTrue(wire_errors_v3(wire,s,SCHEMA))
    def test_no_context_reference_paths_disabled(self):
        s,t,r,p=fixture(); wire,diag=predict_v3(s,BUNDLE,t,r,p,SCHEMA,include_context=False)
        self.assertTrue(diag["reference"]["context_disabled"])


if __name__=="__main__": unittest.main(verbosity=2)
