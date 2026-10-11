"""Unit fixtures only; no independent review/qualification annotations are authored."""
import copy
import unittest
from unittest.mock import patch

from context_v2 import feature_v2
from narrow_review_v3 import TASK, assess_reviews, plan_packet, sha
from narrow_train_v3 import binary_diagnostic, fit_grouped
from build_data import encoded
from test_v2 import fixture_snapshot


def unit_rows():
    return [{"id":"a", "group":"unit-a", "snapshot":fixture_snapshot("I propose paying a portion."), "y":1},
            {"id":"b", "group":"unit-b", "snapshot":fixture_snapshot("Who is calling?"), "y":0}]


class NarrowHeadUnitSmoke(unittest.TestCase):
    def test_missing_reviews_never_pass(self):
        self.assertFalse(assess_reviews({"records":[]}, None)["admitted"])

    def test_self_asserted_review_cannot_pass_without_parent_roster(self):
        packet={"task":TASK,"records":[{"example_id":"one","lineage_group_id":"one","input":fixture_snapshot()}]}
        reviews={"task":TASK,"packet_sha256":sha(encoded(packet)),"records":[{"example_id":"one","annotations":[{"reviewer_id":"self","label":"positive"},{"reviewer_id":"other","label":"positive"}],"adjudication":{"label":"positive","status":"adjudicated"}}]}
        result=assess_reviews(packet,reviews)
        self.assertFalse(result['admitted'])
        self.assertIn('parent_verified_reviewer_independence_missing',result['reasons'])
        self.assertIn('unverified_or_original_author_reviewer',result['reasons'])

    def test_group_descendant_duplication_does_not_change_objective(self):
        rows=unit_rows()
        one,loss1=fit_grouped(rows,epochs=30,max_features=64)
        duplicate=copy.deepcopy(rows[0]);duplicate['id']='a-copy'
        two,loss2=fit_grouped(rows+[duplicate],epochs=30,max_features=64)
        self.assertEqual(one['vocabulary'],two['vocabulary'])
        for key in one['head']['weights']:
            self.assertAlmostEqual(one['head']['weights'][key],two['head']['weights'][key],places=12)
        self.assertAlmostEqual(loss1[-1],loss2[-1],places=12)

    def test_training_row_serialization_order_is_not_speech_order(self):
        rows=unit_rows()
        one,_=fit_grouped(rows,epochs=10,max_features=64)
        two,_=fit_grouped(rows[::-1],epochs=10,max_features=64)
        self.assertEqual(one,two)

    def test_binary_sidecar_never_emits_negative_intent_or_permission(self):
        model,loss=fit_grouped(unit_rows(),epochs=40,max_features=64)
        self.assertLess(loss[-1],loss[0])
        with patch('builtins.open',side_effect=AssertionError('I/O')):
            result=binary_diagnostic(fixture_snapshot('Who is calling?'),model)
        self.assertEqual(result['decision'],'abstain')
        self.assertIsNone(result['calibrated_probability'])
        self.assertFalse(result['qualified'])
        self.assertNotIn('primary',result)
        self.assertNotIn('permission',result)

    def test_feature_row_permutation_preserves_nonconflicting_context(self):
        one=fixture_snapshot()
        one['question']['target_indices']=[0]
        one['targets'].append({'index':1,'type':'fictional_other'})
        one['pending'].append({'target_index':1,'components':{'amount':{'status':'unfinished'}}})
        two=copy.deepcopy(one)
        two['targets'].reverse();two['pending'].reverse()
        self.assertEqual(feature_v2(one),feature_v2(two))
        # Feature invariance only; no claim about consumer atomic state transitions.

    def test_review_packet_has_no_author_labels_or_predictions(self):
        records=[]
        for label in ('payment_proposal','other'):
            for i in range(20):
                records.append({'example_id':label+str(i),'lineage_group_id':label+str(i),'split':'train',
                                'input':fixture_snapshot(), 'labels':{'primary_intent':label,'mask':{'primary_intent':True}},
                                'annotation':{'rationale':'Do not copy this author rationale'}})
        packet,admin=plan_packet(records)
        self.assertEqual(len(packet['selected_lineage_groups']),40)
        self.assertEqual(admin['distinct_selected_groups'],40)
        self.assertTrue(all(set(row)=={'example_id','lineage_group_id','input'} for row in packet['records']))
        self.assertFalse(admin['annotation_gate_passed'])
        self.assertTrue(packet['optional_annotation_only_axes']['missing_axis_masked'])

    def test_development_is_never_selected_for_review_training(self):
        with self.assertRaises(ValueError):
            plan_packet([{'split':'development'}])


if __name__=='__main__':
    unittest.main()
