"""Independent Codex audit. Local source/CPU checks only; never launches Modal.

Writes only analysis/minilm-ft-final-review.tests.json. Run with python -B.
Tests use real source functions, AST-extracted loss, real local tokenizer, and
in-memory budget state. No base/frozen weights or credential files are opened.
"""
import ast
import collections
import contextlib
import copy
import hashlib
import importlib.util
import json
import pathlib
import sys
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parent
CORE_PATH = ROOT / 'integrations/learned-dialogue/minilm_ft_core.py'
PACKET = ROOT / 'research/customer-benchmark/minilm-finetune-v1'
DETAILS = {}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


core = module('independent_minilm_core', CORE_PATH)
launch = module('independent_minilm_launch', CORE_PATH.with_name('minilm_ft_launch.py'))


def row(group='fixture', split='TRAIN'):
    return {'id': group, 'group': group, 'split': split, 'source': 'synthetic',
            'input': {'current_utterance': 'I withdraw my earlier approval.',
                      'previous_utterances': [{'speaker': 'ASSISTANT', 'text': 'You earlier approved the debit.'}]},
            'domain_labels': [0, 0, 0, 0, 1, 0, 0], 'domain_mask': [True] * 7,
            'aux_labels': [0] * 4, 'aux_mask': [False] * 4}


def source_assignment(name):
    tree = ast.parse(CORE_PATH.read_text(encoding='utf8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'train_arm')
    return next(n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))


def run_assignments(names, scope):
    nodes = [source_assignment(n) for n in names]
    code = compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(CORE_PATH), 'exec')
    exec(code, scope)
    return scope


class Witness(unittest.TestCase):
    def test_01_observed_features_and_complete_token_tail(self):
        import torch
        from transformers import AutoTokenizer
        original = row()
        changed = copy.deepcopy(original)
        for key in ['id', 'group', 'split', 'source']:
            changed[key] = 'GOLD_SENTINEL_NEVER_ENCODE'
        changed['domain_labels'] = [1] * 7
        changed['aux_labels'] = [1] * 4
        changed['domain_mask'] = [False] * 7
        changed['aux_mask'] = [True] * 4
        changed['input']['gold_frames'] = {'oracle': 'GOLD_SENTINEL_NEVER_ENCODE'}
        self.assertEqual(core.observed_text(original), core.observed_text(changed))
        self.assertNotIn('GOLD_SENTINEL', core.observed_text(changed))
        tokenizer_dir = ROOT / 'local-runs/minilm-finetune-v1/pilot/models/finetuned/encoder'
        tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir), local_files_only=True,
                                                  trust_remote_code=False, token=False)
        text = 'hello ' * 900 + ' zxqvultimate withdraw approval now'
        full = tokenizer(text, add_special_tokens=False)['input_ids']
        windows = tokenizer([text], padding=True, truncation=True, max_length=256,
                            stride=32, return_overflowing_tokens=True)
        pieces = []
        for i, (ids, mask) in enumerate(zip(windows['input_ids'], windows['attention_mask'])):
            content = [v for v, active in zip(ids, mask) if active][1:-1]
            pieces.extend(content if i == 0 else content[32:])
        self.assertEqual(full, pieces, 'Observed late correction was lost by tokenization')

        class Encoder(torch.nn.Module):
            def forward(self, input_ids, attention_mask, **kwargs):
                self.ids = input_ids.detach().clone()
                self.mask = attention_mask.detach().clone()
                states = torch.nn.functional.one_hot(input_ids % 384, 384).float()
                states = states + (~attention_mask.bool()).unsqueeze(-1) * 1000000
                self.states = states
                return type('Output', (), {'last_hidden_state': states})()

        model = object.__new__(core.Model)
        model.torch = torch
        model.device = 'cpu'
        model.tokenizer = tokenizer
        model.encoder = Encoder()
        actual = model.encode([text, 'brief input'])
        batch = tokenizer([text, 'brief input'], return_tensors='pt', padding=True,
                          truncation=True, max_length=256, stride=32, return_overflowing_tokens=True)
        expected = []
        for sample in range(2):
            means = []
            for i in range(len(batch['input_ids'])):
                if int(batch['overflow_to_sample_mapping'][i]) == sample:
                    active = model.encoder.mask[i].bool()
                    means.append(model.encoder.states[i][active].mean(0))
            expected.append(torch.nn.functional.normalize(torch.stack(means).mean(0), dim=0))
        torch.testing.assert_close(actual, torch.stack(expected))
        DETAILS['observations'] = {'metadata_invariant': True, 'token_count': len(full),
                                   'windows': len(windows['input_ids']), 'tail_preserved': True,
                                   'padding_excluded': True, 'weights_loaded': False}

    def test_02_head_boundaries_mask_gradients_and_empty_supervision(self):
        import torch
        failures = []
        invalid = row()
        invalid['domain_labels'] = [0] * 6
        invalid['aux_labels'] = [0] * 5
        invalid['domain_mask'] = [True] * 6
        invalid['aux_mask'] = [False] * 5
        try:
            core.targets(invalid)
            failures.append('6 domain + 5 aux accepted and silently remapped to 7 + 4 heads')
        except ValueError:
            pass
        logits = torch.zeros((2, 11), requires_grad=True)
        mask = torch.zeros((2, 11)); mask[:, 0] = 1
        y = torch.zeros((2, 11)); y[0, 0] = 1
        scope = {'torch': torch, 'logits': logits, 'y': y, 'mask': mask,
                 'posweight': torch.ones(11), 'headweight': torch.tensor([1] * 7 + [.25] * 4)}
        run_assignments(['elements', 'known', 'valid', 'loss'], scope)
        scope['loss'].backward()
        self.assertLess(float(logits.grad[0, 0]), 0)
        self.assertGreater(float(logits.grad[1, 0]), 0)
        self.assertEqual(int(torch.count_nonzero(logits.grad[:, 1:])), 0)

        class Tiny:
            def __init__(self, directory, device, trainable):
                self.encoder = torch.nn.Linear(1, 1, bias=False)
                self.head = torch.nn.Linear(1, 11)
                self.encoder.requires_grad_(trainable)
                with torch.no_grad(): self.encoder.weight.fill_(1)
            def encode(self, texts): return self.encoder(torch.ones((len(texts), 1)))
        tree = ast.parse(CORE_PATH.read_text(encoding='utf8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'train_arm')
        boundary = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'out' for t in n.targets))
        fn.body = fn.body[:boundary] + [ast.parse('return {"changed": changed, "delta": delta, "steps": steps}').body[0]]
        namespace = dict(core.__dict__); namespace['Model'] = Tiny
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(CORE_PATH), 'exec'), namespace)
        unknown = row(); unknown['domain_mask'] = [False] * 7; unknown['aux_mask'] = [False] * 4
        empty_rejected = False; delta = 0.0; moved = False
        with mock.patch.object(torch.cuda, 'is_available', return_value=False):
            try:
                outcome = namespace['train_arm']([unknown, unknown], [], 'unused', 'unused', True, epochs=1, batch_size=2)
                moved = outcome['changed'] > 0; delta = outcome['delta']
            except (ValueError, AssertionError):
                empty_rejected = True
        if moved: failures.append('All-unknown zero-loss batch changes encoder through AdamW weight decay')
        DETAILS['loss'] = {'unknown_logit_gradient_zero': True, 'known_gradient_signs_correct': True,
                           'all_unknown_encoder_changed': moved, 'all_unknown_fit_rejected': empty_rejected,
                           'encoder_delta': delta,
                           'failures': failures}
        self.assertEqual(failures, [])

    def test_03_train_cal_split_admission(self):
        calls = []
        def fit(rows, cal, encoder, out, trainable, *args, **kwargs):
            calls.append({'train_split': rows[0]['split'], 'cal_split': cal[0]['split']})
            return {'spy_only': True}
        with mock.patch.object(core, 'read_rows', side_effect=[[row('same')], [row('same', 'CAL')]]), \
             mock.patch.object(core, 'train_arm', side_effect=fit):
            with self.assertRaises(ValueError): core.train_both('unused-train', 'unused-cal', 'unused-encoder', 'unused-output')
        failures = []
        for bad_train, bad_cal in [(row('train', 'EVAL'), row('cal', 'CAL')),
                                  (row('train', 'TRAIN'), row('cal', 'EVAL'))]:
            with mock.patch.object(core, 'read_rows', side_effect=[[bad_train], [bad_cal]]), \
                 mock.patch.object(core, 'train_arm', side_effect=fit):
                try:
                    core.train_both('unused-train', 'unused-cal', 'unused-encoder', 'unused-output')
                    failures.append('Accepted TRAIN=' + bad_train['split'] + '/CAL=' + bad_cal['split'])
                except ValueError:
                    pass
        DETAILS['admission'] = {'group_overlap_rejected': True, 'spy_fit_calls': calls, 'failures': failures}
        self.assertEqual(failures, [])

    def test_04_written_packet_schema_source_masks_and_split_eligibility(self):
        manifest = json.loads((PACKET / 'manifest.json').read_text(encoding='utf8'))
        sources = json.loads((PACKET / 'sources.json').read_text(encoding='utf8'))
        ancestry = {r['group']: r for r in core.read_rows(PACKET / 'ancestry.jsonl')}
        groups = {}; roots = {}; ids = set(); signatures = {}; errors = []
        counts = collections.Counter(); kinds = collections.Counter(); all_unknown = collections.Counter()
        long_context = collections.Counter(); collision_rows = collections.Counter(); conflicts = collections.Counter()
        conflict_heads = collections.Counter(); conflict_sources = collections.Counter()
        allowed = {'id', 'group', 'split', 'source', 'input', 'domain_labels', 'domain_mask', 'aux_labels', 'aux_mask'}
        for output in manifest['outputs']:
            if output['split'] == 'EVAL': continue
            path = ROOT / output['path']; expected_split = output['split']; n = 0
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), output['sha256'])
            with path.open(encoding='utf8') as stream:
                for line in stream:
                    if not line.strip(): continue
                    r = json.loads(line); n += 1; counts[expected_split] += 1
                    if set(r) != allowed or set(r['input']) != {'current_utterance', 'previous_utterances'}:
                        errors.append('feature/schema allowlist:' + r['id'])
                    if len(r['domain_labels']) != 7 or len(r['domain_mask']) != 7 or len(r['aux_labels']) != 4 or len(r['aux_mask']) != 4:
                        errors.append('head dimensions:' + r['id'])
                    core.targets(r); text = core.observed_text(r)
                    if r['split'] != expected_split: errors.append('wrong split:' + r['id'])
                    if r['id'] in ids: errors.append('duplicate id:' + r['id'])
                    ids.add(r['id'])
                    prior = groups.setdefault(r['group'], expected_split)
                    if prior != expected_split: errors.append('group crosses split:' + r['group'])
                    a = ancestry.get(r['group'])
                    if not a or a['split'] != expected_split: errors.append('ancestry mismatch:' + r['group'])
                    source = sources.get(r['source'])
                    if not source: errors.append('unregistered source:' + r['id']); continue
                    kind = a['kind']; kinds[expected_split + ':' + kind] += 1
                    if r['source'].startswith('sgd:') and any(r['domain_mask']): errors.append('SGD domain known:' + r['id'])
                    if source.get('publisher_partition') == 'TEST': errors.append('publisher TEST:' + r['id'])
                    if not any(r['domain_mask'] + r['aux_mask']): all_unknown[expected_split] += 1
                    if len(r['input']['previous_utterances']) > 2: long_context[expected_split] += 1
                    for turn in r['input']['previous_utterances']:
                        if set(turn) != {'speaker', 'text'} or turn['speaker'] not in ['USER', 'ASSISTANT', 'SYSTEM']:
                            errors.append('turn schema:' + r['id'])
                    if expected_split != 'TRAIN' and r['source'].startswith('tau-'): errors.append('Tau recipe outside TRAIN:' + r['id'])
                    for root_key in ['template_root', 'dialogue_roots', 'scenario_roots', 'source_document_roots']:
                        raw = a.get(root_key, [])
                        raw = [raw] if isinstance(raw, str) else raw
                        for root in raw:
                            key = ('sgd' if kind == 'sgd_aux' else 'synthetic', root_key, root)
                            old = roots.setdefault(key, expected_split)
                            if old != expected_split: errors.append('ancestry root crosses:' + str(key))
                    digest = hashlib.sha256(text.encode()).digest()
                    y, m = core.targets(r)
                    old = signatures.setdefault(digest, {})
                    for prior_split, (prior_mask, prior_y) in old.items():
                        overlap = [j for j in range(11) if m[j] and prior_mask[j]]
                        if overlap and prior_split != expected_split:
                            collision_rows[prior_split + '/' + expected_split] += 1
                            if any(j < 7 for j in overlap): errors.append('eligible domain text collision:' + r['id'])
                        different = [j for j in range(11) if m[j] and prior_mask[j] and y[j] != prior_y[j]]
                        if different:
                            conflicts[prior_split + '/' + expected_split] += 1
                            conflict_heads.update((core.DOMAIN + core.AUX)[j] for j in different)
                            conflict_sources.update([r['source'].split(':')[0]])
                    if expected_split not in old:
                        old[expected_split] = (m, y)
                    else:
                        pm, py = old[expected_split]
                        old[expected_split] = ([pm[j] or m[j] for j in range(11)], [py[j] if pm[j] else y[j] for j in range(11)])
            self.assertEqual(n, output['rows'])
        DETAILS['packet'] = {'counts': dict(counts), 'kind_counts': dict(kinds), 'all_unknown_rows': dict(all_unknown),
                             'history_over_two_turns': dict(long_context), 'eligible_same_input_cross_split_rows': dict(collision_rows),
                             'same_input_conflicting_known_label_rows': dict(conflicts),
                             'conflicting_heads': dict(conflict_heads), 'conflicting_later_source_kinds': dict(conflict_sources), 'errors': errors[:30],
                             'error_count': len(errors), 'eval_use': 'EVAL file never opened; TRAIN/CAL only'}
        self.assertEqual(errors, [])

    def test_05_shared_budget_and_cloud_payload_containment(self):
        state = {'actual_task_cost_usd': 0, 'accounted_upper_cost_usd': 0, 'reservations': [], 'invocations': []}
        class Ledger:
            def read_text(self, **kwargs): return json.dumps(state)
        @contextlib.contextmanager
        def nolock(): yield
        def write(path, data): state.clear(); state.update(copy.deepcopy(data))
        with mock.patch.object(launch, 'LEDGER', Ledger()), mock.patch.object(launch, 'lock', nolock), mock.patch.object(launch, 'atomic', write):
            launch.reserve('test-a', 10)
            with self.assertRaises(ValueError): launch.reserve('test-b', 10)
            launch.update('test-a', 'finished', settle=True)
            self.assertEqual(state['accounted_upper_cost_usd'], 10)
            state['actual_task_cost_usd'] = 20
            with self.assertRaises(ValueError): launch.reserve('test-cap', 10)
        modal_src = CORE_PATH.with_name('minilm_ft_modal.py').read_text(encoding='utf8')
        launch_src = CORE_PATH.with_name('minilm_ft_launch.py').read_text(encoding='utf8')
        tree = ast.parse(modal_src)
        function = next(n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == 'function')
        kwargs = {k.arg: k.value for k in function.keywords}
        for key, expected in [('gpu', 'H100'), ('retries', 0), ('max_containers', 1), ('min_containers', 0),
                              ('single_use_containers', True), ('include_source', False)]:
            self.assertEqual(ast.literal_eval(kwargs[key]), expected)
        self.assertFalse(ast.literal_eval(kwargs['block_network']) if 'block_network' in kwargs else False)
        self.assertEqual(ast.literal_eval(kwargs['secrets']), [])
        self.assertEqual(ast.literal_eval(kwargs['volumes']), {})
        self.assertNotIn('eval.jsonl', modal_src)
        self.assertNotIn('add_local_dir', modal_src)
        guard_pos = launch_src.find('guardian=subprocess.Popen')
        app_pos = launch_src.find('with app.run():')
        late = app_pos >= 0 and guard_pos > app_pos
        DETAILS['containment'] = {'budget_isolated_in_memory': True, 'aggregate_35_rejected': True,
                                  'second_live_job_rejected': True, 'one_H100': True, 'zero_retries': True,
                                  'payload_only_train_cal_encoder_reviewed_sources': True, 'result_upload_network_available': True, 'holdout_uploaded': False,
                                  'guardian_starts_after_app_run': late,
                                  'rate_bound': 'Fixed USD10 reservation has no resource-rate algebra in source; do not treat as verified provider invoice.'}
        self.assertFalse(late, 'Guardian not armed while app.run performs image build/startup; parent patch pending')


    def test_06_actual_CPU_encoder_update_inference_and_abstention(self):
        import torch
        import numpy as np
        torch.set_num_threads(2)
        pilot = ROOT / 'local-runs/minilm-finetune-v1/pilot/models/finetuned'
        tree = ast.parse(CORE_PATH.read_text(encoding='utf8'))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'train_arm')
        boundary = next(i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == 'out' for t in n.targets))
        fn.body = fn.body[:boundary] + [ast.parse('return {"changed": changed, "delta": delta, "steps": steps, "seen": len(seen), "curve": curve}').body[0]]
        namespace = dict(core.__dict__)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(CORE_PATH), 'exec'), namespace)
        samples = [row('a'), row('b'), row('c')]
        for r in samples:
            r['domain_mask'] = [False] * 7
            r['aux_labels'] = [1, 0, 0, 0]; r['aux_mask'] = [True] * 4
        outcomes = {}
        with mock.patch.object(torch.cuda, 'is_available', return_value=False):
            for name, trainable in [('frozen', False), ('finetuned', True)]:
                outcomes[name] = namespace['train_arm'](samples, [], pilot / 'encoder', 'unused', trainable,
                                                        epochs=2, batch_size=2, deadline=time.monotonic() + 120)
        self.assertEqual(outcomes['frozen']['changed'], 0)
        self.assertGreater(outcomes['finetuned']['changed'], 0)
        for outcome in outcomes.values():
            self.assertEqual(outcome['steps'], 4)
            self.assertEqual(outcome['seen'], 3)
            self.assertEqual(len(outcome['curve']), 2)
        with mock.patch.dict(sys.modules, {'minilm_ft_core': core}):
            evaluation = module('independent_final_eval', CORE_PATH.with_name('minilm_ft_eval.py'))
        model, manifest = evaluation.load_model(pilot, 'cpu')
        self.assertEqual(next(model.encoder.parameters()).dtype, torch.float32)
        self.assertEqual(model.head.weight.dtype, torch.float32)
        logits = model.predict([{'input': row()['input']}], batch_size=1)
        self.assertEqual(logits.shape, (1, 11)); self.assertTrue(np.isfinite(logits).all())
        assist = module('independent_final_assist', ROOT / 'competition/finetuned_assist.py')
        request = {'schema': assist.SCHEMA, 'calls': str(ROOT / 'new.py'),
                   'calls_sha256': assist.sha(ROOT / 'new.py'), 'model_directory': str(pilot),
                   'manifest_sha256': assist.sha(pilot / 'manifest.json'),
                   'runtime_directory': str(CORE_PATH.parent),
                   'runtime_sha256': {n: assist.sha(CORE_PATH.parent / n) for n in assist.RUNTIME_NAMES}, 'seconds': 60}
        verified = assist.verify_manifest(request)
        self.assertEqual(manifest, verified)
        tampered = dict(request, manifest_sha256='0' * 64)
        with self.assertRaises(ValueError): assist.verify_manifest(tampered)
        engine = object.__new__(assist.FinetunedModel)
        engine.model = model; engine.manifest = manifest; engine.deadline = time.monotonic() + 60
        proposals = engine.predict([row()['input']])
        self.assertEqual(len(proposals), 1)
        self.assertTrue(all(not h['selected'] for h in proposals[0].values()))
        invalid = dict(row()['input'], domain_labels=[1] * 7)
        with self.assertRaises(ValueError): engine.predict([invalid])
        engine.model = type('Extreme', (), {'predict': lambda self, *a, **k: [[1000] * 11]})()
        engine.manifest = dict(manifest, thresholds=[1.01] * 11)
        self.assertTrue(all(not h['selected'] for h in engine.predict([row()['input']])[0].values()))
        observed, skipped = assist.observed_turns([{'expected_action': 'GOLD_SENTINEL', 'messages': [
            {'role': 'assistant', 'message': 'Do you keep your earlier permission?'},
            {'role': 'tool', 'message': 'GOLD_SENTINEL'},
            {'role': 'user', 'message': 'No, I withdraw.', 'domain_labels': [1] * 7}]}])
        self.assertEqual(observed[0]['input']['previous_utterances'], [])
        self.assertNotIn('GOLD_SENTINEL', json.dumps(observed))
        DETAILS['actual_CPU'] = {'model_source': 'existing new finetuned pilot, no original/frozen weights',
                                'export': False, 'synthetic_rows': 3, 'epochs': 2, 'batch_size': 2,
                                'domain_masks': 'all false', 'aux_masks': 'all true', 'outcomes': outcomes,
                                'encoder_dtype': str(next(model.encoder.parameters()).dtype),
                                'head_dtype': str(model.head.weight.dtype), 'finite_logits_shape': list(logits.shape),
                                'manifest_pin_verified': True, 'tampered_manifest_pin_rejected': True,
                                'disabled_heads_abstain_even_logit_1000': True,
                                'adapter_rejects_gold_input': True, 'accuracy_validation': False}

    def test_07_evaluation_rejects_non_EVAL_split_without_reading_holdout(self):
        import numpy as np
        import torch
        with mock.patch.dict(sys.modules, {'minilm_ft_core': core}):
            evaluation = module('independent_final_eval_admission', CORE_PATH.with_name('minilm_ft_eval.py'))
        synthetic = row('synthetic-not-heldout', 'TRAIN'); synthetic['source'] = 'new-authored'
        fake = type('Fake', (), {'predict': lambda self, rows, *a, **k: np.zeros((len(rows), 11), dtype='float32')})()
        rejected = False
        with mock.patch.object(sys, 'argv', ['eval', '--models', str(ROOT / 'synthetic-models'),
                                           '--eval', str(ROOT / 'synthetic-not-EVAL.jsonl'),
                                           '--output', str(ROOT / 'analysis/minilm-ft-final-review.synthetic.json')]), \
             mock.patch.object(evaluation, 'read_rows', return_value=[synthetic]), \
             mock.patch.object(evaluation, 'load_model', return_value=(fake, {'thresholds': [.5] * 11})), \
             mock.patch.object(pathlib.Path, 'exists', return_value=False), \
             mock.patch.object(pathlib.Path, 'read_bytes', return_value=b'synthetic-fixture-never-heldout'), \
             mock.patch.object(pathlib.Path, 'write_text') as written, \
             mock.patch.object(np, 'savez_compressed'), \
             mock.patch.object(torch.cuda, 'is_available', return_value=False), \
             mock.patch('builtins.print'):
            try: evaluation.main()
            except ValueError: rejected = True
            produced = json.loads(written.call_args.args[0]) if written.called else None
        DETAILS['eval_admission'] = {'EVAL_text_opened': False, 'synthetic_input_split': 'TRAIN',
                                     'rejected': rejected, 'wrote_heldout_report_in_memory': produced is not None,
                                     'reported_scope': produced['scope'] if produced else None,
                                     'cloud_calls': 0, 'real_output_files': 0}
        self.assertTrue(rejected, 'Evaluation accepts TRAIN-tagged rows and reports heldout metrics; require split=EVAL before prediction')

    def test_08_actual_H100_exports_counts_pins_and_CPU_load(self):
        import torch
        import numpy as np
        torch.set_num_threads(2)
        root = ROOT / 'local-runs/minilm-finetune-v1/h100-run3/models'
        records = {}
        for name in ['frozen', 'finetuned']:
            directory = root / name
            report = json.loads((directory / 'training.json').read_text(encoding='utf8'))
            manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf8'))
            for filename, expected in manifest['files'].items():
                self.assertEqual(hashlib.sha256((directory / filename).read_bytes()).hexdigest(), expected)
            for key, expected in [('TRAIN_rows', 156341), ('CAL_rows', 16416), ('epochs', 2),
                                   ('optimizer_steps', 2444), ('unique_TRAIN_rows_seen', 156341),
                                   ('all_train_rows_seen', True), ('bank_authority', False)]:
                self.assertEqual(report[key], expected)
            self.assertEqual(report['financial_permission'], 'UNKNOWN')
            self.assertEqual(report['encoder_changed_tensors'], 0 if name == 'frozen' else 101)
            self.assertEqual(len(manifest['thresholds']), 11)
            self.assertTrue(all(type(x) in (int, float) and 0 <= x <= 1.01 for x in manifest['thresholds']))
            keys = ['TRAIN_rows', 'CAL_rows', 'epochs', 'optimizer_steps', 'unique_TRAIN_rows_seen',
                    'all_train_rows_seen', 'encoder_changed_tensors', 'encoder_delta_L2',
                    'encoder_requires_grad_count', 'device', 'GPU', 'bank_authority', 'financial_permission']
            records[name] = {'training': {k: report[k] for k in keys},
                             'manifest_sha256': hashlib.sha256((directory / 'manifest.json').read_bytes()).hexdigest(),
                             'encoder_sha256': manifest['files']['encoder/model.safetensors'],
                             'head_sha256': manifest['files']['head.safetensors'],
                             'verified_file_count': len(manifest['files'])}
        with mock.patch.dict(sys.modules, {'minilm_ft_core': core}):
            evaluation = module('independent_final_actual_export', CORE_PATH.with_name('minilm_ft_eval.py'))
        model, manifest = evaluation.load_model(root / 'finetuned', device='cpu')
        self.assertEqual(next(model.encoder.parameters()).dtype, torch.float32)
        self.assertEqual(model.head.weight.dtype, torch.float32)
        logits = model.predict([{'input': row()['input']}], batch_size=1)
        self.assertEqual(logits.shape, (1, 11)); self.assertTrue(np.isfinite(logits).all())
        DETAILS['actual_H100_exports'] = {'records': records, 'CPU_finite_logits_shape': list(logits.shape),
                                         'CPU_encoder_dtype': 'torch.float32', 'CPU_head_dtype': 'torch.float32',
                                         'EVAL_text_opened': False, 'EVAL_metrics_read': False,
                                         'accuracy_validation': False, 'model_files_modified': False,
                                         'provider_stop': 'User reports stopped/tasks0; no provider calls by auditor'}


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs); self.records = []
    def addSuccess(self, test): super().addSuccess(test); self.records.append({'test': test.id(), 'status': 'PASS'})
    def addFailure(self, test, err): super().addFailure(test, err); self.records.append({'test': test.id(), 'status': 'FAIL', 'reason': str(err[1])})
    def addError(self, test, err): super().addError(test, err); self.records.append({'test': test.id(), 'status': 'ERROR', 'reason': str(err[1])})


if __name__ == '__main__':
    started = time.monotonic()
    fingerprints = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [CORE_PATH,
                    CORE_PATH.with_name('minilm_ft_modal.py'), CORE_PATH.with_name('minilm_ft_launch.py'), CORE_PATH.with_name('minilm_ft_guard.py'), CORE_PATH.with_name('minilm_ft_eval.py'), ROOT / 'competition/finetuned_assist.py']}
    result = unittest.TextTestRunner(verbosity=2, resultclass=RecordingResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(Witness))
    after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [CORE_PATH,
             CORE_PATH.with_name('minilm_ft_modal.py'), CORE_PATH.with_name('minilm_ft_launch.py'), CORE_PATH.with_name('minilm_ft_guard.py'), CORE_PATH.with_name('minilm_ft_eval.py'), ROOT / 'competition/finetuned_assist.py']}
    report = {'audit_agent': 'Codex', 'native_Opus_available': False, 'seconds': time.monotonic() - started,
              'source_sha256_before': fingerprints, 'source_sha256_after': after,
              'concurrent_source_change': fingerprints != after, 'tests_run': result.testsRun,
              'tests': result.records, 'details': DETAILS, 'cloud_calls': 0, 'cloud_cost': 0,
              'accuracy_validation': False, 'bank_authority': False}
    path = ROOT / 'analysis/minilm-ft-final-review.tests.json'
    path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'report': str(path), 'tests_run': result.testsRun, 'failures': len(result.failures),
                      'errors': len(result.errors), 'seconds': report['seconds'], 'details': DETAILS}, indent=2))
    sys.exit(0 if result.wasSuccessful() else 1)
