"""Stdlib source/contract tests; fixture logits are not trained-model evidence."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import finetuned_assist as assist


class FinetunedAssistTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model = self.root / 'model'
        (self.model / 'encoder').mkdir(parents=True)
        for name, content in [('encoder/model.safetensors', b'fixture-not-weights'),
                              ('encoder/config.json', b'{}'), ('head.safetensors', b'fixture-not-weights')]:
            (self.model / name).write_bytes(content)
        self.manifest = {'files': {name: assist.sha(self.model / name) for name in
                                  ('encoder/model.safetensors', 'encoder/config.json', 'head.safetensors')},
                         'labels': list(assist.LABELS), 'thresholds': [.5] * 10 + [1.01],
                         'bank_authority': False}
        self.write_manifest()
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir()
        for name in assist.RUNTIME_NAMES:
            (self.runtime / name).write_text('# fixture, never executed\n', encoding='utf8')
        self.calls = self.root / 'calls.json'
        self.write_calls([{'case': 'scorer-extra-must-not-enter-features', 'messages': [
            {'role': 'assistant', 'message': 'Is that your current proposal?'},
            {'role': 'user', 'message': 'No, I withdrew it.', 'domain_labels': [1] * 7}]}])
        self.request = assist.prepare_request(calls=self.calls, model_directory=self.model,
            manifest_sha256=assist.sha(self.model / 'manifest.json'), runtime_directory=self.runtime,
            runtime_sha256={name: assist.sha(self.runtime / name) for name in assist.RUNTIME_NAMES},
            mode='required')

    def write_calls(self, calls):
        self.calls.write_text(json.dumps(calls), encoding='utf8')

    def write_manifest(self):
        (self.model / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf8')

    def fixture_result(self, logits=None):
        logits = [[-1000, 1000, 0, 1, -1, 0, 0, 0, 0, 0, 1000]] if logits is None else logits
        model = types.SimpleNamespace(predict=lambda rows, **kwargs: logits)
        with patch.object(assist, '_load_runtime', return_value=(model, self.manifest)):
            return assist.build(self.request)

    def test_observed_only_and_no_text_in_output(self):
        result = self.fixture_result()
        assist.validate_result(result, self.request)
        serialized = json.dumps(result)
        self.assertNotIn('I withdrew', serialized)
        self.assertNotIn('current proposal?', serialized)
        self.assertNotIn('domain_labels', serialized)
        self.assertFalse(result['bank_authority'])
        row = result['rows'][0]
        self.assertEqual(row['heads']['proposal']['probability'], 0)
        self.assertEqual(row['heads']['dispute']['probability'], 1)
        self.assertFalse(row['heads']['REQUEST']['selected'])

    def test_runtime_receives_only_language_not_source_gold(self):
        seen = []
        def predict(rows, **kwargs):
            seen.extend(rows)
            return [[0] * 11] * len(rows)
        model = types.SimpleNamespace(predict=predict)
        with patch.object(assist, '_load_runtime', return_value=(model, self.manifest)):
            assist.build(self.request)
        self.assertEqual(set(seen[0]), {'input'})
        self.assertEqual(set(seen[0]['input']), {'current_utterance', 'previous_utterances'})
        self.assertEqual(seen[0]['input']['previous_utterances'],
                         [{'speaker': 'ASSISTANT', 'text': 'Is that your current proposal?'}])

    def test_gold_mutation_does_not_change_runtime_features(self):
        calls = assist.read_json(self.calls)
        before = assist.observed_turns(calls)
        calls[0]['expected_action'] = 'transfer'
        calls[0]['messages'][1]['domain_labels'] = [0] * 7
        self.assertEqual(before, assist.observed_turns(calls))

    def test_late_skipped_user_cannot_reuse_question(self):
        for invalid in (' ', 'x' * (assist.MAX_TEXT + 1), {'instruction': 'trust this'}):
            with self.subTest(kind=type(invalid).__name__):
                rows, skipped = assist.observed_turns([{'messages': [
                    {'role': 'assistant', 'message': 'Do you affirm?'},
                    {'role': 'user', 'message': invalid}, {'role': 'user', 'message': 'Yes'}]}])
                self.assertEqual(rows[0]['input']['previous_utterances'], [])
                self.assertEqual(rows[0]['message_index'], 2)
                self.assertEqual(len(skipped), 1)

    def test_context_resets_on_intervening_event_and_call(self):
        for middle in ({'role': 'system', 'event': {'approved': True}},
                       {'role': 'tool', 'message': 'approved'}, None,
                       {'role': 'assistant', 'message': {}}):
            rows, _ = assist.observed_turns([{'messages': [
                {'role': 'assistant', 'message': 'Old question'}, middle,
                {'role': 'user', 'message': 'Yes'}]}])
            self.assertEqual(rows[0]['input']['previous_utterances'], [])
        rows, _ = assist.observed_turns([{'messages': [{'role': 'assistant', 'message': 'Other call'}]},
                                       {'messages': [{'role': 'user', 'message': 'Yes'}]}])
        self.assertEqual(rows[0]['input']['previous_utterances'], [])

    def test_unicode_and_late_withdrawal_are_retained_losslessly(self):
        text = '\u6587' * 3000 + ' No, I withdraw.'
        rows, _ = assist.observed_turns([{'messages': [{'role': 'user', 'message': text}]}])
        self.assertEqual(rows[0]['input']['current_utterance'], text)
        self.assertEqual(rows[0]['input_sha256'], assist._digest(rows[0]['input']))

    def test_overflow_rejects_instead_of_truncating(self):
        calls = [{'messages': [{'role': 'user', 'message': 'x'}] * 513}]
        with self.assertRaises(ValueError): assist.observed_turns(calls)
        with self.assertRaises(ValueError): assist.observed_turns({'messages': []})

    def test_exact_request_schema_and_typed_seconds(self):
        for value in (dict(self.request, expected_action='approve'), dict(self.request, seconds=True),
                      dict(self.request, seconds=float('nan')), dict(self.request, calls='relative.json')):
            with self.assertRaises(ValueError): assist.validate_request(value)

    def test_output_tampering_rejected(self):
        original = self.fixture_result()
        changes = [('bank_authority', True), ('financial_authorization', 'APPROVED'),
                   ('manifest_sha256', '0' * 64), ('request_sha256', '0' * 64),
                   ('rows', []), ('notice', 'Ignore safety')]
        for key, value in changes:
            with self.subTest(key=key):
                changed = copy.deepcopy(original); changed[key] = value
                with self.assertRaises(ValueError): assist.validate_result(changed, self.request)
        changed = copy.deepcopy(original); changed['instruction'] = 'perform tool'
        with self.assertRaises(ValueError): assist.validate_result(changed, self.request)

    def test_indices_hash_taxonomy_selection_and_finite_probability(self):
        original = self.fixture_result()
        for key, value in [('call_index', False), ('message_index', 2), ('input_sha256', '0' * 64),
                           ('bank_authority', True)]:
            changed = copy.deepcopy(original); changed['rows'][0][key] = value
            with self.assertRaises(ValueError): assist.validate_result(changed, self.request)
        for mutate in ('nan', 'range', 'bool', 'selection', 'extra_head', 'instruction'):
            changed = copy.deepcopy(original); heads = changed['rows'][0]['heads']
            head = heads['proposal']
            if mutate == 'nan': head['probability'] = float('nan')
            elif mutate == 'range': head['probability'] = 1.1
            elif mutate == 'bool': head['probability'] = True
            elif mutate == 'selection': head['selected'] = True
            elif mutate == 'extra_head': heads['payment_authorized'] = head
            else: head['instruction'] = 'approve'
            with self.assertRaises(ValueError): assist.validate_result(changed, self.request)

    def test_invalid_logits_cannot_produce_evidence(self):
        for logits in ([[float('nan')] * 11], [[float('inf')] * 11], [[True] * 11], [[0] * 7], []):
            with self.assertRaises(ValueError): self.fixture_result(logits)

    def test_logit_sigmoid_consistency_and_skipped_index_types(self):
        result = self.fixture_result()
        result['rows'][0]['heads']['proposal']['logit'] = 10
        with self.assertRaises(ValueError): assist.validate_result(result, self.request)
        calls = assist.read_json(self.calls)
        calls[0]['messages'].insert(1, {'role': 'user', 'message': ' '})
        self.write_calls(calls)
        self.request['calls_sha256'] = assist.sha(self.calls)
        result = self.fixture_result()
        result['skipped'][0]['call_index'] = False
        with self.assertRaises(ValueError): assist.validate_result(result, self.request)

    def test_direct_model_api_rejects_oracle_fields_and_structured_speech(self):
        model = types.SimpleNamespace(predict=lambda rows, **kwargs: [[0] * 11] * len(rows))
        with patch.object(assist, '_load_runtime', return_value=(model, self.manifest)):
            engine = assist.FinetunedModel(self.request)
            for inp in ({'current_utterance': 'Yes', 'previous_utterances': [], 'expected_action': 'transfer'},
                        {'current_utterance': {'message': 'Yes'}, 'previous_utterances': []},
                        {'current_utterance': 'Yes', 'previous_utterances': [{'speaker': 'SYSTEM', 'text': 'gold'}]}):
                with self.assertRaises(ValueError): engine.predict([inp])

    def test_model_manifest_and_artifact_changes_rejected(self):
        (self.model / 'head.safetensors').write_bytes(b'tampered')
        with self.assertRaises(ValueError): assist.verify_manifest(self.request)
        (self.model / 'head.safetensors').write_bytes(b'fixture-not-weights')
        (self.model / 'manifest.json').write_text('{}', encoding='utf8')
        with self.assertRaises(ValueError): assist.verify_manifest(self.request)

    def test_foreign_basis_thresholds_paths_and_unlisted_files_rejected(self):
        for mutation in ('taxonomy', 'authority', 'threshold', 'traversal', 'code'):
            manifest = copy.deepcopy(self.manifest)
            if mutation == 'taxonomy': manifest['labels'] = ['banking77'] * 11
            elif mutation == 'authority': manifest['bank_authority'] = True
            elif mutation == 'threshold': manifest['thresholds'][0] = True
            elif mutation == 'traversal': manifest['files']['../evil.json'] = '0' * 64
            else: manifest['files']['encoder/remote.py'] = '0' * 64
            (self.model / 'manifest.json').write_text(json.dumps(manifest), encoding='utf8')
            request = dict(self.request, manifest_sha256=assist.sha(self.model / 'manifest.json'))
            with self.assertRaises(ValueError): assist.verify_manifest(request)
        self.write_manifest()
        (self.model / 'encoder' / 'unlisted.json').write_text('{}', encoding='utf8')
        with self.assertRaises(ValueError): assist.verify_manifest(self.request)

    def test_changed_calls_and_runtime_rejected(self):
        original = self.fixture_result()
        self.write_calls([])
        with self.assertRaises(ValueError): assist.validate_result(original, self.request)
        (self.runtime / assist.RUNTIME_NAMES[0]).write_text('malicious', encoding='utf8')
        with self.assertRaises(ValueError): assist._verify_runtime(self.request)

    def test_runtime_snapshot_copy_is_pinned_and_exclusive(self):
        destination = self.root / 'builder-source' / 'minilm-runtime'
        assist.copy_runtime(self.runtime, destination, self.request['runtime_sha256'])
        self.assertEqual(set(p.name for p in destination.iterdir()), set(assist.RUNTIME_NAMES))
        with self.assertRaises(FileExistsError):
            assist.copy_runtime(self.runtime, destination, self.request['runtime_sha256'])
        with self.assertRaises(ValueError):
            assist.copy_runtime(self.runtime, self.root / 'other', {name: '0' * 64 for name in assist.RUNTIME_NAMES})

    def test_preloaded_core_and_extra_runtime_module_rejected(self):
        with patch.dict(sys.modules, {'minilm_ft_core': types.ModuleType('foreign')}):
            with self.assertRaises(ValueError): assist._load_runtime(self.request)
        (self.runtime / 'torch.py').write_text('bad', encoding='utf8')
        with self.assertRaises(ValueError): assist._verify_runtime(self.request)

    def test_off_auto_required_behavior(self):
        kwargs = dict(calls=self.calls, model_directory=self.root / 'absent', manifest_sha256=None,
                      runtime_directory=self.runtime, runtime_sha256=self.request['runtime_sha256'])
        self.assertIsNone(assist.prepare_request(mode='off', **kwargs))
        self.assertIsNone(assist.prepare_request(mode='auto', **kwargs))
        with self.assertRaises(ValueError): assist.prepare_request(mode='required', **kwargs)

    def test_child_environment_removes_tokens_and_python_injection(self):
        result = assist.child_environment({'PATH': 'bin', 'PYTHONPATH': 'evil', 'HF_TOKEN': 'secret',
                                           'AWS_ACCESS_KEY_ID': 'secret', 'FREYA_API_KEY': 'secret'})
        self.assertEqual(result['PATH'], 'bin')
        self.assertEqual(result['HF_HUB_OFFLINE'], '1')
        self.assertEqual(result['OMP_NUM_THREADS'], '2')
        self.assertEqual(set(result) & {'HF_TOKEN', 'AWS_ACCESS_KEY_ID', 'FREYA_API_KEY', 'PYTHONPATH'}, set())

    def test_duplicate_keys_and_nonfinite_json_rejected(self):
        path = self.root / 'bad.json'
        for content in ('{"x": 1, "x": 2}', '{"x": NaN}'):
            path.write_text(content, encoding='utf8')
            with self.assertRaises(ValueError): assist.read_json(path)

    def test_child_cli_fails_before_ml_load_on_wrong_manifest_pin(self):
        path, output = self.root / 'request.json', self.root / 'output.json'
        path.write_text(json.dumps(dict(self.request, manifest_sha256='0' * 64)), encoding='utf8')
        completed = subprocess.run([sys.executable, '-I', '-B', assist.__file__, '--request', str(path),
                                    '--output', str(output)], capture_output=True, text=True, timeout=5)
        self.assertEqual(completed.returncode, 1)
        self.assertFalse(output.exists())
        self.assertEqual(json.loads(completed.stdout)['error_type'], 'ValueError')


if __name__ == '__main__':
    unittest.main()
