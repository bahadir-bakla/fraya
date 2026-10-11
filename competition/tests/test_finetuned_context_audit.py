"""Context-audit contract tests. Synthetic heads are not model evidence.

All inference in this module is mocked; no released model is loaded or run.
"""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import finetuned_assist as assist
import finetuned_context_audit as audit


THRESHOLDS = [.5, .5, .5, 1.01, 1.01, .99, .8, .5, .7, .5, .6]


def heads(logits=None):
    logits = [-4.] * 11 if logits is None else logits
    return {label: {'logit': value, 'probability': assist._sigmoid(value),
                    'selected': assist._sigmoid(value) >= threshold}
            for label, value, threshold in zip(assist.LABELS, logits, THRESHOLDS)}


class FakeEngine:
    """Record frozen-model calls and return synthetic logits, never ML."""
    def __init__(self, *, no_context_failure=None, no_context_logits=None):
        self.calls = []
        self.no_context_failure = no_context_failure
        self.no_context_logits = no_context_logits

    def predict(self, rows, **kwargs):
        self.calls.append((copy.deepcopy(rows), dict(kwargs)))
        if kwargs['no_context']:
            if self.no_context_failure is not None:
                raise self.no_context_failure
            if self.no_context_logits is not None:
                return self.no_context_logits
        return [[-4.] * 11 for _ in rows]


class HeadStateTests(unittest.TestCase):
    def test_threshold_equality_and_all_agreement_states(self):
        negative = heads()['proposal']
        positive = heads([0.] * 11)['proposal']
        cases = [(positive, positive, .5, 'AGREED_SELECTED_PROPOSAL'),
                 (negative, negative, .5, 'AGREED_NOT_SELECTED'),
                 (positive, negative, .5, 'UNRESOLVED'),
                 (negative, positive, .5, 'UNRESOLVED')]
        for full, no_context, threshold, expected in cases:
            with self.subTest(expected=expected, selected=full['selected']):
                self.assertEqual(audit.head_state(full, no_context, threshold), expected)

    def test_disabled_heads_remain_disabled_despite_raw_probability_flip(self):
        for label in ('current_affirm', 'current_withdraw'):
            with self.subTest(label=label):
                low, high = heads([-1000.] * 11)[label], heads([1000.] * 11)[label]
                self.assertEqual(audit.head_state(low, high, 1.01), 'DISABLED')
                self.assertEqual(audit.head_state(high, low, 1.01), 'DISABLED')

    def test_missing_second_arm_cannot_be_agreement(self):
        self.assertEqual(audit.head_state(heads()['proposal'], None, .5), 'UNAVAILABLE')
        self.assertEqual(audit.head_state(heads()['current_affirm'], None, 1.01), 'DISABLED')


class ContextAuditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.model = self.root / 'model'
        (self.model / 'encoder').mkdir(parents=True)
        for name, content in (('head.safetensors', b'unit-test-not-weights'),
                              ('encoder/model.safetensors', b'unit-test-not-weights'),
                              ('encoder/config.json', b'{}')):
            (self.model / name).write_bytes(content)
        (self.model / 'architecture.json').write_text(json.dumps(audit.ARCHITECTURE), encoding='utf8')
        self.manifest = {'files': {name: assist.sha(self.model / name) for name in
                                  ('head.safetensors', 'encoder/model.safetensors',
                                   'encoder/config.json', 'architecture.json')},
                         'labels': list(assist.LABELS), 'thresholds': list(THRESHOLDS),
                         'bank_authority': False}
        (self.model / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf8')
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir()
        for name in assist.RUNTIME_NAMES:
            (self.runtime / name).write_text('# inert unit-test fixture; never executed\n', encoding='utf8')
        self.calls = self.root / 'calls.json'
        self.calls.write_text(json.dumps([
            {'expected_action': 'must-never-be-a-feature', 'messages': [
                {'role': 'user', 'message': 'I agree to Monday.'},
                {'role': 'assistant', 'message': 'Still Monday?'},
                {'role': 'user', 'message': 'I withdraw that yes.', 'labels': [1] * 7},
                {'role': 'tool', 'message': 'receipt'},
                {'role': 'user', 'message': 'After the tool.'},
                {'role': 'assistant', 'message': 'Discard this question?'},
                {'role': 'user', 'message': ' '},
                {'role': 'user', 'message': 'After the blank.'},
                {'role': 'assistant', 'message': 'Another question?'},
                {'role': 'user', 'message': 'Late correction.'}]},
            {'messages': [{'role': 'user', 'message': 'New call.'}]}]), encoding='utf8')
        self.request = assist.prepare_request(
            calls=self.calls, model_directory=self.model,
            manifest_sha256=assist.sha(self.model / 'manifest.json'),
            runtime_directory=self.runtime,
            runtime_sha256={name: assist.sha(self.runtime / name) for name in assist.RUNTIME_NAMES},
            seconds=60, mode='required')
        self.enterContext(patch.object(audit, 'V2_PIN_MANIFEST', self.request['manifest_sha256']))
        self.enterContext(patch.object(audit, 'V2_PIN_RUNTIME', copy.deepcopy(self.request['runtime_sha256'])))
        self.enterContext(patch.object(audit, 'V2_PIN_ARCHITECTURE', self.manifest['files']['architecture.json']))
        self.enterContext(patch.object(assist, '_load_runtime',
                                      side_effect=AssertionError('Real ML load forbidden in unit tests')))

    def make_audit(self, full_logits=None, no_context_logits=None):
        observations, skipped = assist._source(self.request)
        full_heads = [heads(full_logits) for _ in observations]
        full = {'schema': assist.SCHEMA, 'bank_authority': False,
                'financial_authorization': 'UNKNOWN',
                'source_sha256': self.request['calls_sha256'],
                'manifest_sha256': self.request['manifest_sha256'],
                'runtime_sha256': copy.deepcopy(self.request['runtime_sha256']),
                'request_sha256': assist._digest(self.request),
                'labels': list(assist.LABELS), 'thresholds': list(THRESHOLDS),
                'rows': [{key: row[key] for key in
                          ('call_index', 'message_index', 'input_sha256')} |
                         {'heads': prediction, 'bank_authority': False,
                          'financial_authorization': 'UNKNOWN'}
                         for row, prediction in zip(observations, full_heads)],
                'skipped': skipped, 'notice': assist.NOTICE}
        assist.validate_result(full, self.request)
        other = [heads(no_context_logits) if row['input']['previous_utterances']
                 else None for row in observations]
        envelope = audit.assemble_audit(self.request, full, observations, skipped, other)
        return full, envelope, observations, skipped, other

    def write_calls(self, calls):
        self.calls.write_text(json.dumps(calls), encoding='utf8')
        self.request['calls_sha256'] = assist.sha(self.calls)

    def reject(self, full, envelope, path, value):
        changed = copy.deepcopy(envelope)
        target = changed
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        with self.assertRaises(ValueError):
            audit.validate_audit(changed, self.request, full)

    def test_available_envelope_preserves_full_and_binds_effective_inputs(self):
        full, envelope, observations, _, _ = self.make_audit()
        before = copy.deepcopy(full)
        audit.validate_audit(envelope, self.request, full)
        self.assertEqual(full, before)
        self.assertEqual(envelope['status'], 'AVAILABLE')
        self.assertEqual(envelope['base_full_evidence_sha256'], assist._digest(full))
        self.assertFalse(envelope['bank_authority'])
        self.assertEqual(envelope['financial_authorization'], 'UNKNOWN')
        self.assertEqual(envelope['thresholds'], THRESHOLDS)
        for row, observed, original in zip(envelope['rows'], observations, full['rows']):
            self.assertEqual(row['full_heads'], original['heads'])
            self.assertEqual(row['original_input_sha256'], observed['input_sha256'])
            if observed['input']['previous_utterances']:
                effective = {'current_utterance': observed['input']['current_utterance'],
                             'previous_utterances': []}
                self.assertEqual(row['effective_no_context_input_sha256'], assist._digest(effective))
            else:
                self.assertEqual(row['status'], 'NOT_APPLICABLE')
                self.assertIsNone(row['no_context_heads'])
                self.assertIsNone(row['effective_no_context_input_sha256'])
        serialized = json.dumps(envelope)
        self.assertNotIn('Still Monday?', serialized)
        self.assertNotIn('expected_action', serialized)

    def test_aux_flip_keeps_domain_heads_and_disabled_states(self):
        full_logits, other_logits = [-4.] * 11, [-4.] * 11
        full_logits[0] = other_logits[0] = 4.
        other_logits[7] = 4.
        other_logits[3] = other_logits[4] = 1000.
        full, envelope, _, _, _ = self.make_audit(full_logits, other_logits)
        row = next(row for row in envelope['rows'] if row['prior_present'])
        self.assertEqual(row['status'], 'UNRESOLVED')
        self.assertFalse(row['domain_disagreement'])
        self.assertTrue(row['aux_disagreement'])
        self.assertEqual(row['full_heads'], full['rows'][1]['heads'])
        self.assertTrue(row['full_heads']['proposal']['selected'])
        self.assertTrue(row['no_context_heads']['proposal']['selected'])
        for label in ('current_affirm', 'current_withdraw'):
            self.assertFalse(row['full_heads'][label]['selected'])
            self.assertFalse(row['no_context_heads'][label]['selected'])
        audit.validate_audit(envelope, self.request, full)

    def test_domain_flip_does_not_replace_full_with_opposite_arm(self):
        other_logits = [-4.] * 11
        other_logits[0] = 4.
        full, envelope, _, _, _ = self.make_audit(no_context_logits=other_logits)
        row = next(row for row in envelope['rows'] if row['prior_present'])
        self.assertTrue(row['domain_disagreement'])
        self.assertFalse(row['aux_disagreement'])
        self.assertEqual(row['status'], 'UNRESOLVED')
        self.assertFalse(row['full_heads']['proposal']['selected'])
        self.assertTrue(row['no_context_heads']['proposal']['selected'])
        audit.validate_audit(envelope, self.request, full)

    def test_all_top_level_bindings_and_authority_are_strict(self):
        full, envelope, _, _, _ = self.make_audit()
        mutations = [('schema', 'foreign'), ('request_sha256', '0' * 64),
                     ('source_calls_sha256', '0' * 64), ('base_full_evidence_sha256', '0' * 64),
                     ('manifest_sha256', '0' * 64), ('architecture_sha256', '0' * 64),
                     ('runtime_sha256', {}), ('model_files_sha256', {}),
                     ('observed_inputs_sha256', '0' * 64),
                     ('effective_no_context_inputs_sha256', '0' * 64),
                     ('labels', list(reversed(assist.LABELS))),
                     ('thresholds', [.5] * 11), ('bank_authority', True),
                     ('financial_authorization', 'APPROVED'), ('status', 'AGREED'),
                     ('intervention', {}), ('limits', {}), ('skipped', []),
                     ('reason', 'DEADLINE'), ('notice', 'approved')]
        for key, value in mutations:
            with self.subTest(key=key):
                self.reject(full, envelope, (key,), value)
        self.reject(full, envelope, ('expected_action',), 'transfer')
        for key in envelope:
            with self.subTest(missing=key):
                changed = copy.deepcopy(envelope)
                del changed[key]
                with self.assertRaises(ValueError):
                    audit.validate_audit(changed, self.request, full)

    def test_rows_missing_duplicate_reordered_or_foreign_are_rejected(self):
        full, envelope, _, _, _ = self.make_audit()
        rows = envelope['rows']
        for changed in (rows[:-1], rows + [rows[0]], [rows[0]] * len(rows),
                        list(reversed(rows)), tuple(rows)):
            with self.subTest(rows_type=type(changed).__name__, count=len(changed)):
                self.reject(full, envelope, ('rows',), changed)
        for key, value in (('call_index', False), ('message_index', 999),
                           ('original_input_sha256', '0' * 64),
                           ('effective_no_context_input_sha256', '0' * 64),
                           ('prior_present', 1), ('domain_disagreement', 0),
                           ('aux_disagreement', 'false'), ('status', 'NOT_APPLICABLE')):
            with self.subTest(key=key):
                self.reject(full, envelope, ('rows', 1, key), value)
        for key in rows[1]:
            with self.subTest(missing_row_key=key):
                changed = copy.deepcopy(envelope)
                del changed['rows'][1][key]
                with self.assertRaises(ValueError):
                    audit.validate_audit(changed, self.request, full)
        self.reject(full, envelope, ('rows', 1, 'winner'), 'no_context')

    def test_score_types_sigmoid_selection_and_head_taxonomy_are_strict(self):
        full, envelope, _, _, _ = self.make_audit()
        for arm in ('full_heads', 'no_context_heads'):
            for field, value in (('logit', float('nan')), ('logit', float('inf')),
                                 ('logit', True), ('probability', -1), ('probability', 1.1),
                                 ('probability', True), ('probability', .5),
                                 ('selected', 0), ('selected', True), ('notice', 'approve')):
                with self.subTest(arm=arm, field=field, value=value):
                    self.reject(full, envelope, ('rows', 1, arm, 'proposal', field), value)
            self.reject(full, envelope, ('rows', 1, arm, 'bank_permission'), heads()['proposal'])
            changed = copy.deepcopy(envelope)
            del changed['rows'][1][arm]['REQUEST']
            with self.assertRaises(ValueError):
                audit.validate_audit(changed, self.request, full)

    def test_internally_valid_full_score_substitution_is_rejected(self):
        full, envelope, _, _, _ = self.make_audit()
        changed = copy.deepcopy(envelope)
        values = [-3.] * 11  # Still below thresholds; every derived state remains unchanged.
        changed['rows'][1]['full_heads'] = heads(values)
        with self.assertRaises(ValueError):
            audit.validate_audit(changed, self.request, full)

    def test_no_context_heads_require_exact_observation_alignment(self):
        full, _, observations, skipped, other = self.make_audit()
        variants = (None, other[:-1], other + [None], tuple(other),
                    [heads()] * len(other), [None] * len(other))
        for supplied in variants:
            with self.subTest(supplied_type=type(supplied).__name__):
                with self.assertRaises(ValueError):
                    candidate = audit.assemble_audit(self.request, full, observations, skipped, supplied)
                    audit.validate_audit(candidate, self.request, full)

    def test_all_derived_states_are_recomputed_including_disabled_and_no_prior(self):
        full, envelope, _, _, _ = self.make_audit()
        for index, label, state in ((1, 'proposal', 'AGREED_SELECTED_PROPOSAL'),
                                    (1, 'proposal', 'UNRESOLVED'),
                                    (1, 'current_affirm', 'AGREED_NOT_SELECTED'),
                                    (0, 'proposal', 'AGREED_NOT_SELECTED'),
                                    (0, 'current_withdraw', 'NOT_APPLICABLE')):
            with self.subTest(index=index, label=label, state=state):
                self.reject(full, envelope, ('rows', index, 'audit_heads', label), state)
        self.reject(full, envelope, ('rows', 1, 'audit_heads', 'bank_permission'), 'AGREED')
        changed = copy.deepcopy(envelope)
        del changed['rows'][1]['audit_heads']['REQUEST']
        with self.assertRaises(ValueError):
            audit.validate_audit(changed, self.request, full)
        self.reject(full, envelope, ('rows', 0, 'no_context_heads'), heads())
        self.reject(full, envelope, ('rows', 0, 'effective_no_context_input_sha256'), '0' * 64)

    def test_nested_limits_intervention_runtime_and_skips_have_strict_types(self):
        full, envelope, _, _, _ = self.make_audit()
        paths = [(('limits', 'cpu_threads'), True),
                 (('limits', 'shared_child_seconds'), 61),
                 (('limits', 'parent_hard_wall_required'), 1),
                 (('limits', 'max_prior_turns'), 1),
                 (('intervention', 'retain_current_and_tail'), False),
                 (('intervention', 'no_label_access'), 1),
                 (('runtime_sha256', assist.RUNTIME_NAMES[0]), '0' * 64),
                 (('model_files_sha256', 'head.safetensors'), '0' * 64),
                 (('skipped', 0, 'call_index'), False),
                 (('skipped', 0, 'message_index'), 99),
                 (('skipped', 0, 'reason'), 'malformed'),
                 (('thresholds', 0), True), (('thresholds', 3), .5)]
        for path, value in paths:
            with self.subTest(path=path):
                self.reject(full, envelope, path, value)

    def test_unavailable_has_no_partial_heads_and_requires_known_reason(self):
        full, _, observations, skipped, other = self.make_audit()
        for reason in ('DEADLINE', 'NO_CONTEXT_FAILED'):
            with self.subTest(reason=reason):
                envelope = audit.assemble_audit(self.request, full, observations, skipped,
                                                None, status='UNAVAILABLE', reason=reason)
                audit.validate_audit(envelope, self.request, full)
                for row in envelope['rows']:
                    self.assertIsNone(row['no_context_heads'])
                    self.assertFalse(row['domain_disagreement'])
                    self.assertFalse(row['aux_disagreement'])
                    for label, threshold in zip(assist.LABELS, THRESHOLDS):
                        expected = 'DISABLED' if threshold > 1 else (
                            'UNAVAILABLE' if row['prior_present'] else 'NOT_APPLICABLE')
                        self.assertEqual(row['audit_heads'][label], expected)
                self.reject(full, envelope, ('rows', 1, 'no_context_heads'), other[1])
                self.reject(full, envelope, ('rows', 1, 'status'), 'AGREED')
        for reason in (None, 'timeout', '', True, 1):
            with self.subTest(invalid_reason=reason):
                with self.assertRaises(ValueError):
                    audit.assemble_audit(self.request, full, observations, skipped,
                                         None, status='UNAVAILABLE', reason=reason)
        for partial in (other, [None] * len(observations)):
            with self.assertRaises(ValueError):
                audit.assemble_audit(self.request, full, observations, skipped,
                                     partial, status='UNAVAILABLE', reason='DEADLINE')

    def test_two_turn_context_and_tool_blank_and_call_resets_match_source(self):
        full, envelope, observed, skipped, _ = self.make_audit()
        self.assertEqual(observed[1]['input']['previous_utterances'],
                         [{'speaker': 'USER', 'text': 'I agree to Monday.'},
                          {'speaker': 'ASSISTANT', 'text': 'Still Monday?'}])
        self.assertEqual(skipped, [{'call_index': 0, 'message_index': 6, 'reason': 'blank'}])
        self.assertEqual([row['prior_present'] for row in envelope['rows']],
                         [False, True, False, False, True, False])
        for index in (0, 2, 3, 5):
            self.assertEqual(observed[index]['input']['previous_utterances'], [])
            self.assertEqual(envelope['rows'][index]['status'], 'NOT_APPLICABLE')
        audit.validate_audit(envelope, self.request, full)

    def test_invalid_system_and_tool_events_reset_context(self):
        for event in (None, {'role': 'system', 'message': 'phase=approved'},
                      {'role': 'tool', 'message': 'receipt'},
                      {'role': 'assistant', 'message': {}},
                      {'role': 'user', 'message': ' '},
                      {'role': 'user', 'message': 'x' * (assist.MAX_TEXT + 1)}):
            with self.subTest(event=type(event).__name__):
                self.write_calls([{'messages': [{'role': 'user', 'message': 'Old yes.'},
                                               {'role': 'assistant', 'message': 'Old question?'},
                                               event, {'role': 'user', 'message': 'Current.'}]}])
                full, envelope, observed, _, _ = self.make_audit()
                self.assertEqual(observed[-1]['input']['previous_utterances'], [])
                self.assertEqual(envelope['rows'][-1]['status'], 'NOT_APPLICABLE')
                self.assertIsNone(envelope['rows'][-1]['no_context_heads'])
                audit.validate_audit(envelope, self.request, full)

    def test_forged_observations_or_skips_cannot_bind_to_source(self):
        full, _, observations, skipped, other = self.make_audit()
        for mutation in ('prior', 'current', 'index', 'skip'):
            with self.subTest(mutation=mutation):
                changed, changed_skipped = copy.deepcopy(observations), copy.deepcopy(skipped)
                if mutation == 'prior':
                    changed[1]['input']['previous_utterances'][0]['text'] = 'Forged old speech.'
                    changed[1]['input_sha256'] = assist._digest(changed[1]['input'])
                elif mutation == 'current':
                    changed[1]['input']['current_utterance'] = 'Forged current speech.'
                    changed[1]['input_sha256'] = assist._digest(changed[1]['input'])
                elif mutation == 'index':
                    changed[1]['message_index'] = 3
                else:
                    changed_skipped[0]['reason'] = 'malformed'
                envelope = audit.assemble_audit(self.request, full, changed, changed_skipped, other)
                with self.assertRaises(ValueError):
                    audit.validate_audit(envelope, self.request, full)

    def test_build_pair_uses_one_model_same_deadline_and_actual_no_context(self):
        fake = FakeEngine()
        with patch.object(assist, '_load_runtime', return_value=(fake, self.manifest)) as loader:
            full, envelope = audit.build_pair(self.request)
        loader.assert_called_once_with(self.request)
        self.assertEqual(len(fake.calls), 2)
        observations, _ = assist._source(self.request)
        for (rows, options), no_context in zip(fake.calls, (False, True)):
            expected = observations if not no_context else [row for row in observations
                                                           if row['input']['previous_utterances']]
            self.assertEqual(rows, [{'input': row['input']} for row in expected])
            self.assertEqual(options['no_context'], no_context)
            self.assertIs(options['no_tail'], False)
            self.assertEqual(options['batch_size'], 16)
            for row in rows:
                self.assertEqual(set(row), {'input'})
                self.assertEqual(set(row['input']), {'current_utterance', 'previous_utterances'})
        self.assertEqual(fake.calls[0][1]['deadline'], fake.calls[1][1]['deadline'])
        assist.validate_result(full, self.request)
        audit.validate_audit(envelope, self.request, full)

    def test_existing_full_is_preserved_and_only_no_context_is_inferred(self):
        full, _, observations, _, _ = self.make_audit()
        before = copy.deepcopy(full)
        fake = FakeEngine()
        with patch.object(assist, '_load_runtime', return_value=(fake, self.manifest)) as loader:
            envelope = audit.audit_existing(self.request, full)
        loader.assert_called_once_with(self.request)
        self.assertEqual(full, before)
        self.assertEqual(len(fake.calls), 1)
        self.assertTrue(fake.calls[0][1]['no_context'])
        self.assertFalse(fake.calls[0][1]['no_tail'])
        self.assertEqual(fake.calls[0][0], [{'input': row['input']} for row in observations
                                          if row['input']['previous_utterances']])
        audit.validate_audit(envelope, self.request, full)

    def test_no_prior_existing_audit_loads_no_model(self):
        self.write_calls([{'messages': [{'role': 'user', 'message': 'Independent.'}]}])
        full, _, _, _, _ = self.make_audit()
        with patch.object(assist, '_load_runtime') as loader:
            envelope = audit.audit_existing(self.request, full)
        loader.assert_not_called()
        self.assertEqual(envelope['status'], 'AVAILABLE')
        self.assertEqual(envelope['rows'][0]['status'], 'NOT_APPLICABLE')
        self.assertIsNone(envelope['rows'][0]['no_context_heads'])

    def test_second_arm_failure_discards_all_partial_rows_and_keeps_full(self):
        for error in (TimeoutError('fixture'), RuntimeError('fixture'),
                      OSError('fixture'), ValueError('fixture')):
            with self.subTest(error=type(error).__name__):
                fake = FakeEngine(no_context_failure=error)
                with patch.object(assist, '_load_runtime', return_value=(fake, self.manifest)):
                    full, envelope = audit.build_pair(self.request)
                self.assertEqual(envelope['status'], 'UNAVAILABLE')
                self.assertEqual(envelope['reason'],
                                 'DEADLINE' if isinstance(error, TimeoutError) else 'NO_CONTEXT_FAILED')
                self.assertTrue(all(row['no_context_heads'] is None for row in envelope['rows']))
                assist.validate_result(full, self.request)
                audit.validate_audit(envelope, self.request, full)

    def test_deadline_after_completed_full_makes_audit_unavailable(self):
        now = [0.]
        fake = FakeEngine()
        validate = assist.validate_result

        def finish_full(result, request):
            validated = validate(result, request)
            now[0] = 60.
            return validated

        with patch.object(audit.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(assist, '_load_runtime', return_value=(fake, self.manifest)), \
                patch.object(assist, 'validate_result', side_effect=finish_full):
            full, envelope = audit.build_pair(self.request)
        self.assertEqual(len(fake.calls), 1)
        self.assertFalse(fake.calls[0][1]['no_context'])
        self.assertEqual(fake.calls[0][1]['deadline'], 60.)
        self.assertEqual(envelope['status'], 'UNAVAILABLE')
        self.assertEqual(envelope['reason'], 'DEADLINE')
        self.assertTrue(all(row['no_context_heads'] is None for row in envelope['rows']))
        audit.validate_audit(envelope, self.request, full)


    def test_actual_source_model_architecture_and_runtime_tampering_is_rejected(self):
        full, envelope, _, _, _ = self.make_audit()
        files = [self.calls, self.model / 'manifest.json', self.model / 'architecture.json',
                 self.model / 'head.safetensors', self.model / 'encoder/config.json',
                 self.model / 'encoder/model.safetensors']
        files += [self.runtime / name for name in assist.RUNTIME_NAMES]
        for path in files:
            with self.subTest(file=path.name):
                original = path.read_bytes()
                try:
                    path.write_bytes(b'tampered-unit-test-source')
                    with self.assertRaises(ValueError):
                        audit.validate_audit(envelope, self.request, full)
                finally:
                    path.write_bytes(original)
        for key, value in (('manifest_sha256', '0' * 64), ('seconds', 61),
                           ('runtime_sha256', {name: '0' * 64 for name in assist.RUNTIME_NAMES})):
            with self.subTest(request_field=key):
                with self.assertRaises(ValueError):
                    audit.verify_v2(dict(self.request, **{key: value}))

    def test_startup_uses_same_budget_and_cannot_infer_after_expiration(self):
        now = [0.]
        fake = FakeEngine()

        def load(request):
            now[0] = 60.
            return fake, self.manifest

        with patch.object(audit.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(assist, '_load_runtime', side_effect=load) as loader:
            with self.assertRaises(TimeoutError):
                audit.build_pair(self.request)
        loader.assert_called_once()
        self.assertEqual(fake.calls, [])

    def test_postvalidation_expiration_discards_completed_second_arm(self):
        now = [0.]
        fake = FakeEngine()
        validate = audit.validate_audit

        def finish_validation(envelope, request, full):
            result = validate(envelope, request, full)
            now[0] = 60.
            return result

        with patch.object(audit.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(assist, '_load_runtime', return_value=(fake, self.manifest)), \
                patch.object(audit, 'validate_audit', side_effect=finish_validation):
            full, envelope = audit.build_pair(self.request)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(envelope['status'], 'UNAVAILABLE')
        self.assertEqual(envelope['reason'], 'DEADLINE')
        self.assertTrue(all(row['no_context_heads'] is None for row in envelope['rows']))
        validate(envelope, self.request, full)

    def test_incomplete_actual_second_arm_never_yields_partial_agreement(self):
        fake = FakeEngine(no_context_logits=[[-4.] * 11])
        with patch.object(assist, '_load_runtime', return_value=(fake, self.manifest)):
            full, envelope = audit.build_pair(self.request)
        self.assertEqual(envelope['status'], 'UNAVAILABLE')
        self.assertEqual(envelope['reason'], 'NO_CONTEXT_FAILED')
        self.assertTrue(all(row['no_context_heads'] is None for row in envelope['rows']))
        audit.validate_audit(envelope, self.request, full)

    def test_sources_changed_during_no_context_are_rechecked(self):
        for path in (self.calls, self.runtime / assist.RUNTIME_NAMES[0],
                     self.model / 'head.safetensors'):
            with self.subTest(file=path.name):
                original = path.read_bytes()
                fake = FakeEngine()
                predict = fake.predict

                def mutate_after_inference(rows, **kwargs):
                    output = predict(rows, **kwargs)
                    if kwargs['no_context']:
                        path.write_bytes(b'changed-during-inference')
                    return output

                fake.predict = mutate_after_inference
                try:
                    with patch.object(assist, '_load_runtime', return_value=(fake, self.manifest)):
                        with self.assertRaises(ValueError):
                            audit.build_pair(self.request)
                    self.assertEqual(len(fake.calls), 2)
                finally:
                    path.write_bytes(original)

    def test_cli_rechecks_request_and_existing_full_files_before_output(self):
        full, envelope, _, _, _ = self.make_audit()
        request_file, full_file = self.root / 'request.json', self.root / 'existing-full.json'
        output = self.root / 'audit.json'
        argv = ['finetuned_context_audit.py', '--request', str(request_file),
                '--full-evidence', str(full_file), '--audit-output', str(output)]
        for target in (request_file, full_file):
            with self.subTest(changed_source=target.name):
                request_file.write_text(json.dumps(self.request), encoding='utf8')
                full_file.write_text(json.dumps(full), encoding='utf8')

                def change_source(request, existing):
                    self.assertEqual(request, self.request)
                    self.assertEqual(existing, full)
                    target.write_text('{}', encoding='utf8')
                    return full, envelope

                with patch.object(sys, 'argv', argv), patch.object(audit, '_run', side_effect=change_source):
                    with self.assertRaises(ValueError):
                        audit.main()
                self.assertFalse(output.exists())
                self.assertFalse(output.with_name(output.name + '.pending').exists())


if __name__ == '__main__':
    unittest.main()
