"""Independent authored challenge contracts; no hosted calls in these tests."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import redteam_adapter as r


class AuthoredRedteamTests(unittest.TestCase):
    def test_each_authored_challenge_retains_bank_facts_and_distinct_actor_oracle(self):
        rows=r.catalog();r.validate_hosted(rows)
        self.assertEqual(len(rows),10)
        self.assertEqual(len({x['variant_id'] for x in rows}),10)
        for row in rows:
            original=r.b.PUBLIC[row['id']]
            for field in ('variables','identity','products','brief'):
                self.assertEqual(row[field],original[field])
            self.assertNotEqual(row['expected'],original['expected'])
            self.assertNotEqual(row['script'],original['script'])

    def test_unreviewed_behavior_or_expected_ledger_or_bank_changes_fail(self):
        for field,value in [('script','New instructions'),('expected',{}),('variables',{}),('checks',[]),('faults',[{'fail':2}])]:
            rows=r.catalog();rows[0][field]=value
            with self.assertRaises(ValueError):r.validate_hosted(rows)

    def test_third_party_actor_does_not_receive_known_security_answers(self):
        row=next(x for x in r.catalog() if x['third_party'])
        spec=r.persona_for(row)
        for value in row['identity'].values():self.assertNotIn(value,spec['prompt'])
        self.assertNotIn('expected',spec['prompt'])

    def test_no_automatic_confirmation_contradicts_tentative_consent(self):
        row=next(x for x in r.catalog() if x['variant_id'].endswith('tentative_consent'))
        spec=r.persona_for(row)
        self.assertNotIn('matches what you agreed, say "Yes, I confirm."',spec['prompt'])
        self.assertIn('Never says yes',spec['prompt'])
        self.assertIn('Never confirm when',spec['prompt'])

    def test_subset_validation_stays_source_bound_and_rejects_duplicates(self):
        rows=r.catalog();r.validate_hosted(rows[:2])
        with self.assertRaises(ValueError):r.validate_hosted([rows[0],deepcopy(rows[0])])
        with self.assertRaises(ValueError):r.validate_hosted([])

    def test_plan_and_summary_cannot_claim_an_official_public_score(self):
        rows=r.catalog()
        plan=r.runner.plan(rows,r,brief='B')
        self.assertEqual(plan['scope'],r.SCOPE)
        summary=r.runner.summarize(rows[:1],[],3,'incomplete')
        self.assertEqual(summary['scope'],r.SCOPE)
        self.assertFalse(summary['pass'])

    def test_freeze_checks_authored_pack_not_only_base_pack(self):
        with patch.object(r.b,'verify_pack',return_value={'verified':True}),patch('redteam_adapter.json.loads',return_value=[]):
            with self.assertRaises(ValueError):r.verify_pack()


if __name__=='__main__':unittest.main()
