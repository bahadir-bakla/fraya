import unittest
import narrow_review_v4_1 as a
class ParentRoleTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.raw=a.load_allowed_inputs();v=a.validate_reviewed_inputs(cls.raw)
  cls.splits=[dict(group_id=k,split='train') for k in sorted(set(v['aliases'].values()))]
  cls.base=a.assess_admission(cls.raw,split_assignments=cls.splits)
 def auth(self,adjudication=True,reviewer=True):
  b=self.base
  x=dict(schema_version='parent_cpu_engineering_authorization.v4.1',issuer='parent',cpu_only=True,gpu_authorized=False,qualified=False,payment_authority=False,source_raw_sha256=a.PINNED_SHA256,definitions_sha256=b['definitions_sha256'],source_vectors_sha256=b['source_vectors_sha256'],candidate_vector_sha256=None,split_assignments_sha256=b['split_assignments_sha256'],historical_immutability_required=False,acknowledges_unknown_reviewer_a_history=True,heads=['primary'],reviewer_registry={'reviewer-a':dict(thread_id='01a128dd-0932-7313-9f0e-950885f79bb6',parent_verified_isolated_blind_source_review=reviewer,is_original_author=False),'reviewer-b':dict(thread_id='01a128e3-ee71-71e3-9486-8d637975599b',parent_verified_isolated_blind_source_review=True,is_original_author=False),'fresh-machine-adjudicator':dict(thread_id='01a128ec-2bb6-7601-94c8-cd9628280037',parent_verified_isolated_source_adjudication=adjudication,parent_verified_isolated_blind_source_review=False,is_original_author=False)})
  raw=a.encoded(x)
  return a.assess_admission(self.raw,authorization_raw=raw,trusted_authorization_sha256=a.sha(raw),split_assignments=self.splits)
 def test_two_blind_reviewers_and_source_adjudicator_can_admit_CPU(self):
  v=self.auth();self.assertTrue(v['admitted']);self.assertFalse(v['gpu_authorized']);self.assertFalse(v['qualified']);self.assertEqual(len(v['eligible_rows']['primary']),108)
 def test_adjudicator_role_proof_cannot_be_missing(self):
  self.assertFalse(self.auth(adjudication=False)['admitted'])
 def test_adjudication_cannot_replace_a_blind_reviewer(self):
  self.assertFalse(self.auth(reviewer=False)['admitted'])
if __name__=='__main__':unittest.main()

