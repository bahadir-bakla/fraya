"""TRAIN-first independently authored engineering controls; no new gold."""
import copy
import unittest
from detector_r4 import date_expressions_r4,detect_candidates_r4,DETECTOR_R4_VERSION
from window_r4 import date_features_r4,score_date_r4,FEATURE_R4_VERSION
from alignment_r4 import align_date_r4
from context_r4 import predict_r4
from test_v3 import fixture,SCHEMA

ADMISSION_R4={"verified_current_source":True,"nonsecurity_value_free":True,"framing_complete":True,"question_role_verified":True}

def snapshot_r4(text,role="date"):
    return {"turn_id":"engineering-source","utterance":{"text":text},"phase":"payment","question":{"role":role}}

class GrammarR4Tests(unittest.TestCase):
    def only(self,text,surface,status="closed"):
        actual=date_expressions_r4(text,"date")["candidates"]
        self.assertEqual([(text[c["start"]:c["end"]],c["syntax_status"]) for c in actual],[(surface,status)])
    def test_ordinal_month(self): self.only("Pay on the twenty-third of October.","the twenty-third of October")
    def test_open_complement_no_punctuation(self): self.only("Pay on the twenty-third of","the twenty-third of","open")
    def test_numeric_day_month_year(self): self.only("Set 29 February 2027.","29 February 2027")
    def test_weekday_calendar(self): self.only("Set Monday, 29 February 2027.","Monday, 29 February 2027")
    def test_month_ordinal_year(self): self.only("Set March twenty-first, 2028.","March twenty-first, 2028")
    def test_range_closed(self): self.only("Choose from 2 March to 5 March.","from 2 March to 5 March")
    def test_range_open(self): self.only("Choose from 2 March to","from 2 March to","open")
    def test_alternative_open_determiner(self): self.only("Choose either March or the","either March or the","open")
    def test_business_day(self): self.only("Choose the fourth working day of April.","the fourth working day of April")
    def test_business_open(self): self.only("Choose the fourth working day of","the fourth working day of","open")
    def test_relative_vague(self): self.only("Next month works.","Next month")
    def test_relative_open(self): self.only("The week after","The week after","open")
    def test_nested_relative_whole_unsupported(self): self.only("Two days after the day before tomorrow.","Two days after the day before tomorrow","unsupported")
    def test_unrelated_tail_is_not_operand(self): self.only("Use the fourth of for the loan.","the fourth of","open")
    def test_unrelated_in_is_not_temporal_relation(self): self.only("Use the fourth of March in the loan calendar.","the fourth of March")
    def test_complete_date_unfinished_time(self): self.only("Thursday at...","Thursday")
    def test_quoted_date_is_not_unfinished(self): self.only("They said 'the fifth of June'; no.","the fifth of June")
    def test_negated_date_is_not_unfinished(self): self.only("Not the fifth of June.","the fifth of June")
    def test_conditional_date_is_not_unfinished(self): self.only("If the fifth of June works.","the fifth of June")
    def test_possessive_period(self): self.only("Next week's budget.","Next week's")
    def test_terminal_hesitation_is_ambiguous(self): self.only("Maybe March third...","March third","ambiguous")
    def test_midturn_hesitation_retains_complete(self): self.only("March third... that is my complete date.","March third")
    def test_clock_not_date(self): self.assertEqual(date_expressions_r4("At 17:45, please.","date")["candidates"],[])
    def test_none_role_open_expression_does_not_raise(self):
        self.assertEqual(date_expressions_r4("Friday or","none")["candidates"][0]["syntax_status"],"open")
    def test_deep_range_prefix_is_bounded(self):
        d=date_expressions_r4("from "*100+"Friday","date")
        self.assertTrue(d["candidates"])
    def test_identifiers_not_date(self): self.assertEqual(date_expressions_r4("Card ending 7384.","payment")["candidates"],[])
    def test_competing_identifier_numeric_date_masked(self):
        text="The account number 04/06 is recorded."
        d=detect_candidates_r4(text,"payment")
        self.assertTrue(d["identifier_exclusions"])
        self.assertTrue(d["candidates"][0]["boundary_ambiguous"])
        f=date_features_r4(snapshot_r4(text),d["candidates"][0],ADMISSION_R4)
        self.assertFalse(f["eligible"])
    def test_no_candidate_not_absence(self): self.assertFalse(date_expressions_r4("No temporal expression.","none")["absence_established"])
    def test_unknown_locale(self): self.assertEqual(date_expressions_r4("Friday.","date","xx")["status"],"unsupported_context")
    def test_overflow_no_slicing(self):
        d=date_expressions_r4("; ".join(["Friday"]*25),"date")
        self.assertEqual(d["status"],"overflow"); self.assertEqual(len(d["candidates"]),25)

class WindowR4Tests(unittest.TestCase):
    def case(self,text="Pay on the fifth of June."):
        s=snapshot_r4(text); c=date_expressions_r4(text,"date")["candidates"][0]
        return s,c
    def test_source_is_required(self):
        s,c=self.case(); self.assertFalse(date_features_r4(s,c,{})["eligible"])
    def test_unrelated_clause_not_feature(self):
        s,c=self.case("Friday; administrative confidentialmarker")
        f=date_features_r4(s,c,ADMISSION_R4)
        self.assertFalse(any("confidentialmarker" in key for key in f["features"]))
    def test_no_identifiers_hashes_or_pending_values(self):
        s,c=self.case(); s.update(call_local_id="secret-id",policy_hash="secret-hash",pending=[{"value":"secret-value"}])
        f=date_features_r4(s,c,ADMISSION_R4)
        self.assertFalse(any("secret" in key for key in f["features"]))
    def test_clipping_is_explicit_fail_closed(self):
        s,c=self.case("unrelated "*20+"Friday")
        f=date_features_r4(s,c,ADMISSION_R4)
        self.assertTrue(f["window_bounds"]["left_clipped"]); self.assertFalse(f["eligible"])
    def test_invalid_calendar_is_not_completion_negative(self):
        s,c=self.case("31 February 2027.")
        f=date_features_r4(s,c,ADMISSION_R4)
        self.assertTrue(f["eligible"]); self.assertFalse(f["normalization_mask"])
        self.assertEqual(c["syntax_status"],"closed")
    def test_wrong_feature_version_rejected(self):
        s,c=self.case()
        self.assertEqual(score_date_r4(s,c,ADMISSION_R4,{"feature_version":"old"})["reason"],"feature_version_mismatch")
    def test_new_untrained_head_never_calls_old_weights(self):
        s,c=self.case(); out=score_date_r4(s,c,ADMISSION_R4,None)
        self.assertIsNone(out["raw_score"]); self.assertEqual(out["decision"],"abstain")
    def test_continuation_token_is_only_flag(self):
        s,c=self.case(); admission=dict(ADMISSION_R4,continuation={"prior_source_event_id":"prior-private","component_token":"opaque-private","current_component_token":"opaque-private","source_relation_verified":True})
        f=date_features_r4(s,c,admission); self.assertTrue(f["continuation_verified"])
        self.assertFalse(any("private" in key for key in f["features"]))
    def test_continuation_missing_link_not_invented(self):
        s,c=self.case(); f=date_features_r4(s,c,dict(ADMISSION_R4,continuation={"component_token":"x"}))
        self.assertFalse(f["continuation_verified"])
    def test_security_mask(self):
        s,c=self.case(); s["question"]["role"]="security"
        self.assertFalse(date_features_r4(s,c,ADMISSION_R4)["eligible"])
    def test_security_phase_masks_despite_payment_role(self):
        s,c=self.case(); s["phase"]="security"; s["question"]["role"]="payment"
        self.assertFalse(date_features_r4(s,c,ADMISSION_R4)["eligible"])
    def test_security_field_masks_despite_date_role(self):
        s,c=self.case(); s["question"]["security_field"]="declared-field"
        self.assertFalse(date_features_r4(s,c,ADMISSION_R4)["eligible"])
    def test_cross_clause_candidate_is_masked(self):
        s,c=self.case("Friday; Monday")
        c=dict(c,start=0,end=14)
        self.assertEqual(date_features_r4(s,c,ADMISSION_R4)["reason"],"unsupported_cross_clause_dependency")
    def test_window_clipping_never_becomes_unfinished_tail(self):
        s,c=self.case("leftcontext "*20+"Friday"+" rightcontext"*20)
        f=date_features_r4(s,c,ADMISSION_R4)
        self.assertEqual(c["syntax_status"],"closed")
        self.assertTrue(f["window_bounds"]["left_clipped"]); self.assertTrue(f["window_bounds"]["right_clipped"])
        self.assertFalse(f["window_bounds"]["dependency_incomplete"])
        self.assertFalse(f["window_bounds"]["delivered_turn_tail"])
    def test_no_any_no_global_feature(self):
        s,c=self.case("Friday; no not never")
        f=date_features_r4(s,c,ADMISSION_R4)
        self.assertFalse(any("negation" in k or k.endswith("no") for k in f["features"]))

class AlignmentR4Tests(unittest.TestCase):
    def setup_case(self):
        s=snapshot_r4("Friday."); d=date_expressions_r4("Friday.","date")
        ann={"kind":"date","start":0,"end":6,"independently_adjudicated":True,"presence_mask":True,"valid_date":True,"completion_mask":True,"completion":"complete"}
        return s,d,ann
    def test_exact_reviewed_alignment(self):
        s,d,a=self.setup_case(); row=align_date_r4(s,d,[a],ADMISSION_R4)["rows"][0]
        self.assertTrue(row["completion_mask"]); self.assertFalse(row["normalization_mask"]); self.assertFalse(row["reference_mask"])
    def test_nearest_boundary_not_label(self):
        s,d,a=self.setup_case(); a["end"]=5; out=align_date_r4(s,d,[a],ADMISSION_R4)
        self.assertEqual(out["missed_source_annotation_indices"],[0]); self.assertFalse(out["rows"][0]["completion_mask"])
    def test_author_annotation_is_not_adjudication(self):
        s,d,a=self.setup_case(); a["independently_adjudicated"]=False
        self.assertFalse(align_date_r4(s,d,[a],ADMISSION_R4)["rows"][0]["validity_mask"])
    def test_ambiguous_label_not_forced_binary(self):
        s,d,a=self.setup_case(); a["completion"]="ambiguous"
        self.assertFalse(align_date_r4(s,d,[a],ADMISSION_R4)["rows"][0]["completion_mask"])
    def test_unmatched_not_false_negative_label(self):
        s,d,a=self.setup_case(); row=align_date_r4(s,d,[],ADMISSION_R4)["rows"][0]
        self.assertIsNone(row["validity_label"])
    def test_independent_absent_region_only_validity_negative(self):
        s,d,a=self.setup_case(); region={"kind":"date","start":0,"end":7,"independently_adjudicated":True,"date_absent":True}
        row=align_date_r4(s,d,[],ADMISSION_R4,[region])["rows"][0]
        self.assertTrue(row["validity_mask"]); self.assertFalse(row["validity_label"]); self.assertFalse(row["completion_mask"])
    def test_duplicate_boundary_disagreement_masks(self):
        s,d,a=self.setup_case(); b=dict(a,completion="unfinished")
        self.assertFalse(align_date_r4(s,d,[a,b],ADMISSION_R4)["rows"][0]["completion_mask"])
    def test_table_and_score_share_identical_features(self):
        s,d,a=self.setup_case()
        self.assertEqual(align_date_r4(s,d,[a],ADMISSION_R4)["rows"][0]["features"],score_date_r4(s,d["candidates"][0],ADMISSION_R4,None)["feature_diagnostics"])

class ReferenceAdmissionR4Tests(unittest.TestCase):
    def test_unknown_terms_cannot_emit_current_readback_candidate(self):
        s,t,r,p=fixture()
        wire,side=predict_r4(s,t,r,p,SCHEMA,ADMISSION_R4)
        self.assertIsNone(wire["consent_signal"]["candidate_readback_id"])
        self.assertIsNone(side["reference"]["candidate_id_or_null"])
        self.assertEqual(side["historical_reference"]["candidate_id_or_null"],"readback-A")
    def test_qualified_false_terms_can_resolve_sidecar_only(self):
        s,t,r,p=fixture()
        evidence=dict(t.binding_context.binding(),call_local_id=t.call_local_id,source_event_id=t.source_event_id,qualified=True,has_new_terms=False)
        wire,side=predict_r4(s,t,r,p,SCHEMA,dict(ADMISSION_R4,scoped_terms_assessment=evidence))
        self.assertEqual(side["reference"]["candidate_id_or_null"],"readback-A")
        self.assertIsNone(wire["consent_signal"]["candidate_readback_id"]); self.assertEqual(wire["status"],"abstain")
    def test_stale_assessment_cannot_resolve(self):
        s,t,r,p=fixture()
        evidence=dict(t.binding_context.binding(),call_local_id=t.call_local_id,source_event_id="old",qualified=True,has_new_terms=False)
        _,side=predict_r4(s,t,r,p,SCHEMA,dict(ADMISSION_R4,scoped_terms_assessment=evidence))
        self.assertIsNone(side["reference"]["candidate_id_or_null"])
    def test_boolean_revision_is_not_qualified_assessment(self):
        s,t,r,p=fixture()
        evidence=dict(t.binding_context.binding(),call_local_id=t.call_local_id,source_event_id=t.source_event_id,qualified=True,has_new_terms=False,state_revision=True)
        _,side=predict_r4(s,t,r,p,SCHEMA,dict(ADMISSION_R4,scoped_terms_assessment=evidence))
        self.assertIsNone(side["reference"]["candidate_id_or_null"])
    def test_security_phase_masks_runtime_surface(self):
        s,t,r,p=fixture(); s["phase"]="security"
        wire,side=predict_r4(s,t,r,p,SCHEMA,ADMISSION_R4)
        self.assertTrue(side["surface_features_masked"]); self.assertEqual(side["date_scores"],[])
    def test_security_field_masks_runtime_surface(self):
        s,t,r,p=fixture(); s["question"]["security_field"]="declared-field"
        _,side=predict_r4(s,t,r,p,SCHEMA,ADMISSION_R4)
        self.assertTrue(side["surface_features_masked"])

if __name__=="__main__": unittest.main()
