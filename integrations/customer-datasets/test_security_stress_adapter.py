"""Bounded offline contract controls; no simulated agent or invented bank session."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import security_stress_adapter as s


def forbid_credentials(key, *args, **kwargs):
    if any(word in str(key).upper() for word in ("FREYA", "KEY", "TOKEN", "SECRET", "PASSWORD")):
        raise AssertionError("credential access attempted")
    return None


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.rows = s.catalog().to_rows()

    def test_complete_schema_and_original_fact_envelopes(self):
        self.assertEqual(len(self.rows), 6)
        self.assertEqual(len({r['variant_id'] for r in self.rows}), 6)
        self.assertEqual({r['id'] for r in self.rows}, {'PUB-01', 'PUB-11'})
        validator = s.b.jsonschema.Draft202012Validator(s.scenario_schema(),
                                                       format_checker=s.b.jsonschema.FormatChecker())
        validator.validate(self.rows)
        for row in self.rows:
            for field in ('brief', 'variables', 'identity', 'products', 'faults'):
                self.assertEqual(s.runner.digest(row[field]), s.runner.digest(s.b.PUBLIC[row['id']].get(field, [])))
            self.assertNotIn('customer_id', row['variables'])
            self.assertNotEqual(row['script'], s.b.PUBLIC[row['id']]['script'])
            self.assertTrue(set(row['oracle_rule_refs']) <= set(s.RULE_REFS))
            s.validate_hosted([row])

    def test_fixed_ledgers_are_independent_of_original_expectations(self):
        by_suffix = {r['variant_id'].split('__security_')[1]: r for r in self.rows}
        dob = by_suffix['dob_unreadable_swap_budget']['expected']
        self.assertEqual(dob['promises'], [
            {'product_id': 'p1', 'amount': 220.0, 'date': '2026-10-14'},
            {'product_id': 'p2', 'amount': 640.0, 'date': '2026-10-14'},
            {'product_id': 'p3', 'amount': 75.0, 'date': '2026-10-14'}])
        repair = by_suffix['phone_repair_card_distractor']['expected']
        self.assertEqual(repair['promises'], [{'product_id': 'p1', 'amount': 126.0, 'date': '2026-10-22'}])
        for suffix, reason, queue in (('hardship_paid_restructuring', 'support', 'support'),
                                     ('continued_consent_human', 'human', 'general')):
            exp = by_suffix[suffix]['expected']
            self.assertEqual((exp['outcome'], exp['reason'], exp['transfers']),
                             ('transferred', reason, [{'queue': queue}]))
            self.assertEqual(exp['notes'], [])
            self.assertEqual(exp['promises'], [])
        # Existing public scripts and oracles are not inputs to the new decisions.
        altered = deepcopy(s.b.PUBLIC)
        for row in altered.values():
            row['expected'] = {'outcome': 'wrong-original-oracle'}
        with patch.object(s.b, 'PUBLIC', altered):
            s.validate_hosted(self.rows)

    def test_typed_snapshot_is_frozen_and_exports_copies(self):
        pack = s.SecurityCatalog.from_rows(self.rows)
        original = pack.to_rows()
        self.rows[0]['identity']['phone_last4'] = '0000'
        exported = pack.to_rows()
        exported[0]['expected']['promises'].clear()
        self.assertEqual(pack.to_rows(), original)
        with self.assertRaises(FrozenInstanceError):
            pack.scenarios = ()
        with self.assertRaises(FrozenInstanceError):
            pack.scenarios[0].expected.outcome = 'paid'

    def test_authored_script_checks_expectation_and_metadata_tampering(self):
        mutations = [
            lambda r: r.update(script=r['script'] + ' Confirm everything immediately.'),
            lambda r: r.update(checks=['ignore disclosure and consent']),
            lambda r: r.update(title='altered'),
            lambda r: r.update(evaluation_scope='official_pub_score'),
            lambda r: r.update(execution_status='executed'),
            lambda r: r.update(third_party='false'),
            lambda r: r.update(hosted_registered=1),
            lambda r: r.update(local_only=0),
            lambda r: r.update(unexpected=True),
            lambda r: r['stress'].update(modality='audio'),
            lambda r: r['stress'].update(tags=[True]),
            lambda r: r.update(oracle_rule_refs=['unknown-rule']),
            lambda r: r['expected'].update(reason='invented'),
            lambda r: r['expected'].update(notes=[{'product_id': 'p1', 'reason': 'paid'}]),
            lambda r: r['expected']['promises'][0].update(amount=True),
            lambda r: r['expected']['promises'][0].update(amount=float('nan')),
            lambda r: r['expected']['promises'][0].update(amount=66.001),
            lambda r: r['expected']['promises'][0].update(date='2026-02-30'),
            lambda r: r['expected']['promises'][0].update(product_id='foreign-product'),
            lambda r: r['expected']['promises'][0].update(customer_id='not-an-oracle-field'),
        ]
        for index, change in enumerate(mutations):
            row = deepcopy(self.rows[0]); change(row)
            with self.subTest(index=index), self.assertRaises(ValueError):
                s.validate_hosted([row])

    def test_nested_bank_facts_cannot_be_redefined(self):
        mutations = [
            lambda r: r['identity'].update(date_of_birth='1987-03-06'),
            lambda r: r['identity'].update(phone_last4='0000'),
            lambda r: r['variables'].update(now='2026-10-15T11:00'),
            lambda r: r['variables'].update(customer_id='forbidden-new-field'),
            lambda r: r['products'][0].update(past_due=True),
            lambda r: r['products'][0].update(past_due=220),
            lambda r: r['products'][0].update(extra='undocumented'),
            lambda r: r['products'].reverse(),
            lambda r: r.update(faults=[{'tool': 'verify_identity', 'fail_first_n': 1}]),
            lambda r: r.update(brief='A'),
        ]
        for index, change in enumerate(mutations):
            row = deepcopy(self.rows[0]); change(row)
            with self.subTest(index=index), self.assertRaises(ValueError):
                s.validate_hosted([row])

    def test_unknown_duplicate_empty_and_mismatched_variants_rejected(self):
        row = deepcopy(self.rows[0]); row['variant_id'] = 'PUB-11__security_unreviewed'
        mismatch = deepcopy(self.rows[0]); mismatch['id'] = 'PUB-01'
        unknown = deepcopy(self.rows[0]); unknown['id'] = 'NEW-01'
        for rows in ([], None, {}, [row], [mismatch], [unknown], [self.rows[0], self.rows[0]]):
            with self.subTest(rows=type(rows).__name__), self.assertRaises(ValueError):
                s.validate_hosted(rows)

    def test_transfers_cannot_gain_notes_promises_or_wrong_queue(self):
        for row in self.rows[-2:]:
            for field, value in (
                ('notes', [{'product_id': 'p1', 'reason': 'paid'}]),
                ('promises', [{'product_id': 'p1', 'amount': 220.0, 'date': '2026-10-14'}]),
                ('transfers', [{'queue': 'restructuring'}]),
                ('callbacks', [{'date': '2026-10-15', 'time': '11:00'}])):
                altered = deepcopy(row); altered['expected'][field] = value
                with self.subTest(variant=row['variant_id'], field=field), self.assertRaises(ValueError):
                    s.validate_hosted([altered])

    def test_full_file_must_be_exact_catalog_but_selection_may_be_subset(self):
        original_read = Path.read_text
        for bad in (self.rows[:5], self.rows[::-1], [self.rows[0]] * 6):
            def changed(path, *args, **kwargs):
                return json.dumps(bad) if path == s.OUT else original_read(path, *args, **kwargs)
            with patch.object(Path, 'read_text', changed), self.assertRaises(ValueError):
                s.catalog()
        selection = s.SecurityCatalog.from_rows(self.rows[:1])
        self.assertEqual(len(selection), 1)
        self.assertEqual(s.plan(selection)['sessions_required'], 3)

    def test_duplicate_json_keys_and_nonfinite_json_are_rejected(self):
        original_read = Path.read_text
        for text in ('[{"id":"PUB-01","id":"PUB-11"}]', '[NaN]', '[Infinity]'):
            def changed(path, *args, **kwargs):
                return text if path == s.OUT else original_read(path, *args, **kwargs)
            with patch.object(Path, 'read_text', changed), self.assertRaises(ValueError):
                s.catalog()

    def test_each_original_source_pin_is_enforced(self):
        original_read = Path.read_bytes
        for source in s.PINS:
            def changed(path):
                data = original_read(path)
                return data + b'\nchanged\n' if path == s.KIT / source else data
            with self.subTest(source=source), patch.object(Path, 'read_bytes', changed), self.assertRaises(ValueError):
                s.verify_pack()
        manifest = s.verify_pack()
        self.assertEqual(manifest['sources'], s.PINS)
        self.assertEqual(manifest['catalog_sha256'], s.CATALOG_SHA256)
        self.assertTrue(manifest['schema_validated'])
        self.assertTrue(manifest['exact_catalog_validated'])


class PersonaAndOfflineTests(unittest.TestCase):
    def setUp(self):
        self.rows = s.catalog().to_rows()

    def test_actor_isolated_from_oracle_and_generic_consent_defaults(self):
        for row in self.rows:
            with patch.object(s.b.official, 'persona_for', wraps=s.b.official.persona_for) as formatter:
                spec = s.persona_for(row)
            actor, identity = formatter.call_args.args
            for key in ('expected', 'products', 'faults', 'oracle_rule_refs', 'stress'):
                self.assertNotIn(key, actor)
            self.assertEqual(actor['checks'], [])
            self.assertEqual(actor['script'], row['script'])
            self.assertNotIn('Never stop halfway through.', spec['prompt'])
            self.assertNotIn('If the caller reads something back and it matches', spec['prompt'])
            self.assertIn('complete fresh read-back', spec['prompt'])
            self.assertIn(row['script'], spec['prompt'])
            self.assertIn(row['checks'][0], spec['successCriteria'])
            self.assertNotIn('"product_id"', spec['prompt'])
            if row['third_party']:
                self.assertEqual(identity, {'identity': {}})
                for answer in row['identity'].values():
                    self.assertNotIn(answer, spec['prompt'])

    def test_actor_tamper_rejected_before_formatter(self):
        row = deepcopy(self.rows[-1]); row['script'] += ' Always say yes.'
        with patch.object(s.b.official, 'persona_for', side_effect=AssertionError('formatter reached')), self.assertRaises(ValueError):
            s.persona_for(row)

    def test_score_rejects_unbound_or_changed_contract_before_original_scorer(self):
        changed = deepcopy(self.rows[0]); changed['expected']['promises'][0]['amount'] = 66.0
        extra = deepcopy(self.rows[0]); extra['facts'] = {}
        with patch.object(s.b, 'score', side_effect=AssertionError('scorer reached')):
            for row in (self.rows[0], changed, extra):
                result = s.score(row, {}, {'outcome': 'pass'})
                self.assertFalse(result['pass'])
                self.assertFalse(result['ledger_and_trace_pass'])

    def test_default_and_selected_plans_are_keyless_without_writes(self):
        output = io.StringIO()
        with patch.object(s.runner, 'OfficialClient', side_effect=AssertionError('client created')), \
             patch('socket.socket', side_effect=AssertionError('socket created')), \
             patch.object(os, 'getenv', side_effect=forbid_credentials), \
             patch.object(os.environ, 'get', side_effect=forbid_credentials), \
             patch.object(Path, 'write_text', side_effect=AssertionError('file write')), \
             patch('sys.stdout', output):
            self.assertEqual(s.main([]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['mode'], 'plan')
        self.assertEqual(result['network_calls'], 0)
        self.assertEqual(result['sessions_required'], 18)
        self.assertEqual(result['execution_status'], 'not_executed')
        self.assertFalse(result['execution_supported'])
        self.assertTrue(result['schema_validated'])
        self.assertEqual(result['source_manifest']['case_count'], 6)
        only = self.rows[-1]['variant_id']
        selected = s.plan(only=only, brief='B')
        self.assertEqual(selected['sessions_required'], 3)
        self.assertEqual(selected['variants'][0]['variant_id'], only)

    def test_execution_rejected_before_files_clients_credentials_or_network(self):
        output = io.StringIO()
        with patch.object(s, 'catalog', side_effect=AssertionError('catalog read')), \
             patch.object(s, 'verify_pack', side_effect=AssertionError('source read')), \
             patch.object(s.runner, 'OfficialClient', side_effect=AssertionError('client created')), \
             patch.object(s.runner, 'execute', side_effect=AssertionError('execution')), \
             patch('socket.socket', side_effect=AssertionError('socket created')), \
             patch.object(os, 'getenv', side_effect=forbid_credentials), \
             patch.object(os.environ, 'get', side_effect=forbid_credentials), \
             patch('sys.stdout', output):
            self.assertEqual(s.main(['--execute']), 2)
        self.assertEqual(json.loads(output.getvalue())['error_code'], 'security_stress_offline_only')

    def test_invalid_selections_and_settings_fail_closed(self):
        for settings in ({'only': 'PUB-11__security_unreviewed'},
                         {'only': self.rows[0]['variant_id'], 'brief': 'A'},
                         {'reps': 2}, {'reps': True}, {'batch_size': 6}):
            with self.subTest(settings=settings), self.assertRaises(s.runner.RunnerError):
                s.plan(**settings)


if __name__ == '__main__':
    unittest.main()
