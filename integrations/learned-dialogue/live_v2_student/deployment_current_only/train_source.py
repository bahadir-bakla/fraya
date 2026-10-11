"""Bounded local TRAIN-only distillation of the frozen V2 teacher.

Reads only the four pinned TRAIN/CAL files. The exported portable STUDENT is
distinct from full V2 and has no bank authority. CAL never supplies gradients.
"""
import argparse
import hashlib
import importlib.util
import json
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEACHER_PIN = '7eca3b016b47ec20f1b1fd9e207c71a0c72ece9bf91f4e2c28ecd411dcb59189'
SEED = 20261011
LABELS = ['proposal', 'dispute', 'correction', 'current_affirm',
          'current_withdraw', 'uncertain', 'reported_third_party',
          'AFFIRM', 'NEGATE', 'INFORM', 'REQUEST']
MIN_THRESHOLDS = [.5, .5, .5, 1.01, 1.01, .99, .8, .5, .7, .5, .6]


def sha(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               allow_nan=False) + '\n', encoding='utf8')


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def check_deadline(deadline, phase):
    if time.monotonic() >= deadline:
        raise TimeoutError('Bounded student deadline: ' + phase)


def verified_sources(teacher_training):
    expected = teacher_training['input_sha256']
    packets = ['minilm-finetune-v1', 'minilm-finetune-v2-data']
    sources = []
    for packet in packets:
        directory = ROOT / 'research/customer-benchmark' / packet
        freeze = json.loads((directory / 'freeze.json').read_text(encoding='utf8'))
        frozen = {x['path']: x for x in freeze['files']}
        for split in ['train', 'cal']:
            path = directory / (split + '.jsonl')
            relative = path.relative_to(ROOT).as_posix()
            pin = frozen[relative]
            # Require agreement with the exact frozen teacher's training receipt.
            recorded = next(v for k, v in expected.items()
                            if k.replace('\\', '/').endswith(relative))
            actual = sha(path)
            if actual != pin['sha256'] or actual != recorded:
                raise ValueError('Source pin mismatch: ' + relative)
            if path.stat().st_size != pin['bytes']:
                raise ValueError('Source byte mismatch: ' + relative)
            sources.append({'path': relative, 'sha256': actual,
                            'bytes': pin['bytes'], 'split': split.upper(),
                            'packet': packet, 'freeze_sha256': sha(directory / 'freeze.json')})
    return sources


def sample_sources(sources, core, deadline, train_limit, cal_limit):
    # Sampling strata use existing source/mask provenance, never target values.
    # v2/domain/aux quotas retain informative domain rows alongside SGD acts.
    limits = {'TRAIN': [train_limit // 2, train_limit // 3,
                        train_limit - train_limit // 2 - train_limit // 3],
              'CAL': [min(384, cal_limit // 3), min(344, cal_limit // 3),
                      cal_limit - min(384, cal_limit // 3) - min(344, cal_limit // 3)]}
    buckets = {split: [[], [], []] for split in limits}
    counts = {split: [0, 0, 0] for split in limits}
    rngs = {split: [random.Random(SEED + (0 if split == 'TRAIN' else 100) + j)
                   for j in range(3)] for split in limits}
    groups = {'TRAIN': set(), 'CAL': set()}
    total = {'TRAIN': 0, 'CAL': 0}
    for source in sources:
        split = source['split']
        with open(ROOT / source['path'], encoding='utf8') as stream:
            for line_number, line in enumerate(stream, 1):
                if line_number % 1024 == 0:
                    check_deadline(deadline, 'source admission')
                if not line.strip():
                    continue
                row = json.loads(line)
                if row['split'] != split:
                    raise ValueError('Split admission mismatch')
                core.targets(row)
                core.observed_parts(row)
                groups[split].add(row['group'])
                total[split] += 1
                j = (0 if source['packet'].endswith('v2-data') else
                     1 if any(row['domain_mask']) else 2)
                counts[split][j] += 1
                bucket = buckets[split][j]
                limit = limits[split][j]
                if len(bucket) < limit:
                    destination = len(bucket)
                else:
                    destination = rngs[split][j].randrange(counts[split][j])
                if destination < limit:
                    item = {'row': row, 'source_path': source['path'],
                            'source_sha256': source['sha256'], 'line': line_number,
                            'row_sha256': hashlib.sha256(line.encode('utf8')).hexdigest()}
                    if destination == len(bucket):
                        bucket.append(item)
                    else:
                        bucket[destination] = item
    if groups['TRAIN'] & groups['CAL']:
        raise ValueError('Full frozen TRAIN/CAL group collision')
    sampled = {s: [x for bucket in buckets[s] for x in bucket] for s in buckets}
    for s, items in sampled.items():
        random.Random(SEED + (10 if s == 'TRAIN' else 20)).shuffle(items)
        if len({x['row']['id'] for x in items}) != len(items):
            raise ValueError('Duplicate sampled IDs')
    return sampled, {'full_source_rows': total, 'stratum_rows': counts,
                     'sample_limits': limits, 'full_group_counts': {s: len(g) for s, g in groups.items()},
                     'TRAIN_CAL_group_intersection': 0,
                     'selection': 'seeded reservoir per v2/legacy-domain/legacy-aux; no label-value selection',
                     'seed': SEED}


def index_item(item):
    row = item['row']
    return {k: item[k] for k in ['source_path', 'source_sha256', 'line', 'row_sha256']} | {
        'id': row['id'], 'group': row['group'], 'split': row['split'], 'source': row['source'],
        'domain_labels': row['domain_labels'], 'domain_mask': row['domain_mask'],
        'aux_labels': row['aux_labels'], 'aux_mask': row['aux_mask'],
        'observed_sha256': hashlib.sha256(json.dumps(row['input'], sort_keys=True,
                                                    ensure_ascii=False).encode('utf8')).hexdigest()}


def metric(prob, rows, thresholds):
    import numpy as np
    y = np.asarray([r['domain_labels'] + r['aux_labels'] for r in rows], dtype=bool)
    mask = np.asarray([r['domain_mask'] + r['aux_mask'] for r in rows], dtype=bool)
    pred = prob >= np.asarray(thresholds)
    heads = {}
    macro = []
    enabled = [j for j in range(7) if thresholds[j] <= 1]
    for j, name in enumerate(LABELS):
        k = mask[:, j]
        tp = int((pred[:, j] & y[:, j] & k).sum())
        fp = int((pred[:, j] & ~y[:, j] & k).sum())
        fn = int((~pred[:, j] & y[:, j] & k).sum())
        f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
        heads[name] = {'known': int(k.sum()), 'positive': int((y[:, j] & k).sum()),
                       'TP': tp, 'FP': fp, 'FN': fn,
                       'precision': tp / (tp + fp) if tp + fp else None,
                       'recall': tp / (tp + fn) if tp + fn else None, 'F1': f1,
                       'coverage': (tp + fp) / int(k.sum()) if k.sum() else None}
        if j < 7 and f1 is not None:
            macro.append(f1)
    active_macro = [heads[LABELS[j]]['F1'] for j in enabled
                    if heads[LABELS[j]]['F1'] is not None]
    selectable_macro = [heads[LABELS[j]]['F1'] for j in [0, 1, 2, 5, 6]
                        if heads[LABELS[j]]['F1'] is not None]
    has_known = mask[:, :7].any(1)
    all_known = mask[:, :7].all(1)
    correct = ((pred[:, :7] == y[:, :7]) | ~mask[:, :7]).all(1)
    active_mask = mask[:, enabled]
    active_covered = (pred[:, enabled] & active_mask).any(1) if enabled else np.zeros(len(rows), dtype=bool)
    p = np.clip(prob, 1e-7, 1 - 1e-7)
    return {'rows': len(rows), 'heads': heads,
            'domain_macro_F1': sum(macro) / len(macro) if macro else None,
            'enabled_domain_macro_F1': sum(active_macro) / len(active_macro) if active_macro else None,
            'selectable_domain_macro_F1': sum(selectable_macro) / len(selectable_macro) if selectable_macro else None,
            'joint_masked_domain_exact': float(correct[has_known].mean()) if has_known.any() else None,
            'joint_fully_known_domain_exact': float(correct[all_known].mean()) if all_known.any() else None,
            'joint_fully_known_rows': int(all_known.sum()),
            'proposal_row_coverage': float(active_covered.mean()),
            'masked_BCE': float(((-y.astype(float) * np.log(p) - (~y).astype(float) * np.log(1 - p)) * mask).sum() / max(1, mask.sum())),
            'masked_Brier': float((((prob - y) ** 2) * mask).sum() / max(1, mask.sum()))}


def fit(features, rows, teacher_logits, variant, deadline, epochs):
    import numpy as np
    import torch
    torch.manual_seed(SEED)
    x = torch.tensor(features, dtype=torch.float32)
    y = torch.tensor([r['domain_labels'] + r['aux_labels'] for r in rows], dtype=torch.float32)
    mask = torch.tensor([r['domain_mask'] + r['aux_mask'] for r in rows], dtype=torch.float32)
    teacher = torch.tensor(teacher_logits, dtype=torch.float32)
    head = torch.nn.Linear(768, 11)
    optimizer = torch.optim.AdamW(head.parameters(), lr=.04, weight_decay=.01)
    known = mask.sum(0).clamp(min=1)
    eligible = (mask.sum(0) > 0).float()
    def reduce(elements):
        means = (elements * mask).sum(0) / known
        return (means[:7].sum() / eligible[:7].sum().clamp(min=1)
                + .25 * means[7:].sum() / eligible[7:].sum().clamp(min=1))
    losses = []
    for epoch in range(epochs):
        check_deadline(deadline, 'fit ' + variant)
        optimizer.zero_grad(set_to_none=True)
        logits = head(x)
        hard = reduce(torch.nn.functional.binary_cross_entropy_with_logits(logits, y, reduction='none'))
        # Actual frozen teacher logits, temperature=2, original masks unchanged.
        soft = 4 * reduce(torch.nn.functional.binary_cross_entropy_with_logits(
            logits / 2, torch.sigmoid(teacher / 2), reduction='none'))
        loss = hard if variant == 'hard' else soft if variant == 'soft' else .5 * hard + .5 * soft
        if not torch.isfinite(loss):
            raise ValueError('Nonfinite fit')
        loss.backward()
        optimizer.step()
        losses.append(float(loss.detach()))
    return head.weight.detach().numpy(), head.bias.detach().numpy(), {
        'variant': variant, 'epochs_completed': epochs, 'rows_seen': len(rows),
        'first_loss': losses[0], 'last_loss': losses[-1], 'temperature': 2,
        'hard_fraction': 1 if variant == 'hard' else 0 if variant == 'soft' else .5,
        'soft_fraction': 0 if variant == 'hard' else 1 if variant == 'soft' else .5,
        'mask_policy': 'Original 7 domain and 4 auxiliary masks; never changed',
        'objective': 'mean known-head domain BCE + .25 mean known-head auxiliary BCE'}


def export(weight, bias, teacher_thresholds):
    import numpy as np
    scales = np.maximum(np.abs(weight).max(1) / 127, 1e-9)
    quantized = np.clip(np.rint(weight / scales[:, None]), -127, 127).astype('int8')
    return {'schema': 'live_v2_student.v1', 'model_kind': 'STUDENT_LINEAR_FNV768_INT8',
            'teacher_manifest_sha256': TEACHER_PIN, 'feature_dim': 768,
            'labels': LABELS, 'thresholds': list(teacher_thresholds),
            'logit_cutoffs': [float(np.log(v / (1 - v))) if v < 1 else 1000000.0 for v in teacher_thresholds],
            'quant_logit_margins': [0.0] * 11,
            'disabled_heads': ['current_affirm', 'current_withdraw'],
            'quantization': 'int8_per_head', 'weights': quantized.tolist(),
            'scales': [float(v) for v in scales], 'bias': [float(v) for v in bias],
            'bank_authority': False, 'financial_authorization': 'UNKNOWN',
            'context_mode': 'observed_prior',
            'mode': 'diagnostic_shadow', 'feature_version': 'ord_fnv32_words_bigrams_char3_global_tail512_prior_256x3.v1'}


def verify_runtime(runtime, path, model, cal):
    import ast
    source = path.read_text(encoding='utf8')
    tree = ast.parse(source)
    imports = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    if set(imports) != {'json', 're'} or any(isinstance(n, ast.ImportFrom) for n in ast.walk(tree)):
        raise ValueError('Runtime import closure')
    if '{{' in source or '}}' in source or '__main__' in source:
        raise ValueError('Runtime compiler marker closure')
    banned = {'open', 'exec', 'eval', '__import__', 'compile', 'hash'}
    if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in banned for n in ast.walk(tree)):
        raise ValueError('Forbidden runtime call')
    current = cal[0]['input']['current_utterance']
    previous = cal[0]['input']['previous_utterances']
    count = 0
    for speech, prior in [(None, []), ('', []), (' ', []), ('x' * 16385, []), (current, None), (current, [{}]),
                          (current, [{'speaker': 'USER', 'text': 1}]), (current, [{'speaker': 'POLICY', 'text': current}]),
                          (current, [{'speaker': 'USER', 'text': current}] * 3)]:
        r = runtime.student_predict(speech, prior, model)
        if r != {'status': 'INVALID', 'scores': [0.0] * 11, 'labels': [], 'bank_authority': False, 'financial_authorization': 'UNKNOWN'}:
            raise ValueError('Malformed input fallback')
        count += 1
    for key, value in [('scales', float('nan')), ('bias', float('inf')), ('thresholds', float('nan')),
                       ('quant_logit_margins', -1), ('logit_cutoffs', float('inf'))]:
        bad = json.loads(json.dumps(model)); bad[key][0] = value
        if runtime.student_predict(current, previous, bad)['status'] != 'INVALID':
            raise ValueError('Malformed finite model fallback')
        count += 1
    for key, value in [('bank_authority', True), ('financial_authorization', 'AUTHORIZED'),
                       ('context_mode', 'unobserved'), ('feature_dim', True), ('weights', [[True] * 768] * 11)]:
        bad = dict(model); bad[key] = value
        if runtime.student_predict(current, previous, bad)['status'] != 'INVALID':
            raise ValueError('Malformed model type/authority fallback')
        count += 1
    for row in cal:
        inp = row['input']; before = runtime.student_predict(inp['current_utterance'], inp['previous_utterances'], model)
        user_only = [t for t in inp['previous_utterances'] if t['speaker'] == 'USER']
        if before != runtime.student_predict(inp['current_utterance'], user_only, model) or before != runtime.student_predict(inp['current_utterance'], [], model):
            raise ValueError('Current-only broker projection parity')
    return {'imports': imports, 'source_status_finiteness_helper_audit': 'PASS',
            'malformed_type_length_finite_checks': count, 'projection_invariance_CAL_rows': len(cal),
            'new_semantic_probes': 0, 'platform_execution': False}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--seconds', type=int, default=780)
    p.add_argument('--train-rows', type=int, default=6000)
    p.add_argument('--cal-rows', type=int, default=1024)
    p.add_argument('--epochs', type=int, default=120)
    p.add_argument('--output', default=str(HERE / 'live_v2_student'))
    a = p.parse_args()
    if not 1 <= a.seconds <= 900 or not 1 <= a.train_rows <= 6000 or not 1 <= a.cal_rows <= 1024 or not 1 <= a.epochs <= 200:
        raise ValueError('Bounded arguments required')
    started = time.monotonic()
    deadline = started + a.seconds
    out = Path(a.output).resolve()
    if (out != HERE / 'live_v2_student' and out.parent != HERE / 'live_v2_student') or out.exists():
        raise ValueError('New owned output directory required; no overwrite')
    out.mkdir()
    report = {'status': 'RUNNING', 'seed': SEED, 'bank_authority': False,
              'financial_authorization': 'UNKNOWN', 'EVAL_read': False,
              'cloud_launches': 0, 'model_kind': 'STUDENT_LINEAR_FNV768_INT8'}
    try:
        import numpy as np
        import torch
        from safetensors.torch import load_file
        torch.set_num_threads(4)
        teacher_dir = HERE / 'minilm_ft_v2/model'
        if sha(teacher_dir / 'manifest.json') != TEACHER_PIN:
            raise ValueError('Teacher manifest pin mismatch')
        manifest = json.loads((teacher_dir / 'manifest.json').read_text(encoding='utf8'))
        if manifest['labels'] != LABELS or manifest['bank_authority'] is not False or manifest['thresholds'] != MIN_THRESHOLDS:
            raise ValueError('Frozen teacher schema mismatch')
        for name, pin in manifest['files'].items():
            if sha(teacher_dir / name) != pin:
                raise ValueError('Teacher artifact pin mismatch: ' + name)
        training = json.loads((teacher_dir / 'training.json').read_text(encoding='utf8'))
        core_path = HERE / 'minilm_ft_v2/runtime/minilm_ft_core.py'
        core_pin = next(v for k, v in training['source_sha256'].items()
                        if k.replace('\\', '/') == 'minilm_ft_v2/runtime/minilm_ft_core.py')
        if sha(core_path) != core_pin:
            raise ValueError('Authentic teacher runtime pin mismatch')
        core = module(core_path, 'student_frozen_teacher_core')
        runtime_path = HERE / 'live_v2_student_runtime.py'
        runtime = module(runtime_path, 'portable_student_runtime')
        sources = verified_sources(training)
        sample, admission = sample_sources(sources, core, deadline, a.train_rows, a.cal_rows)
        train = [x['row'] for x in sample['TRAIN']]
        cal = [x['row'] for x in sample['CAL']]
        write(out / 'source_manifest.json', {'teacher_manifest_sha256': TEACHER_PIN,
               'teacher_files_verified': manifest['files'], 'teacher_runtime_sha256': core_pin,
               'sources': sources, 'admission': admission})
        write(out / 'train_index.json', [index_item(x) for x in sample['TRAIN']])
        write(out / 'cal_index.json', [index_item(x) for x in sample['CAL']])
        report.update(admission=admission, TRAIN_rows=len(train), CAL_rows=len(cal),
                      TRAIN_groups=len({r['group'] for r in train}), CAL_groups=len({r['group'] for r in cal}),
                      masks={s: {'known': np.asarray([core.targets(r)[1] for r in rows]).sum(0).tolist(),
                                 'positive': (np.asarray([core.targets(r)[0] for r in rows]) *
                                              np.asarray([core.targets(r)[1] for r in rows])).sum(0).tolist()}
                             for s, rows in [('TRAIN', train), ('CAL', cal)]})
        write(out / 'training_receipt.json', report)
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        teacher = core.Model(teacher_dir / 'encoder', device=device, trainable=False)
        teacher.head.load_state_dict(load_file(str(teacher_dir / 'head.safetensors'), device=device))
        report['local_device'] = torch.cuda.get_device_name(0) if device == 'cuda' else 'cpu'
        phase = time.monotonic()
        train_logits = teacher.predict(train, batch_size=16, deadline=deadline)
        if not np.isfinite(train_logits).all():
            raise ValueError('Nonfinite authentic teacher logits')
        np.save(out / 'teacher_train_logits.npy', train_logits, allow_pickle=False)
        write(out / 'teacher_train_logits_receipt.json', {
            'teacher_manifest_sha256': TEACHER_PIN, 'runtime_sha256': core_pin,
            'logits_sha256': sha(out / 'teacher_train_logits.npy'),
            'index_sha256': sha(out / 'train_index.json'), 'rows': len(train),
            'shape': list(train_logits.shape), 'dtype': str(train_logits.dtype),
            'inference': 'Authentic Model.predict; encoder1152 global+tail+prior; local inference_mode BF16 CUDA',
            'seconds': time.monotonic() - phase, 'distillation_split': 'TRAIN_ONLY'})
        cal_logits = teacher.predict(cal, batch_size=16, deadline=deadline)
        cal_no_context = teacher.predict(cal, batch_size=16, no_context=True, deadline=deadline)
        # Same genuine frozen V2 parameters, observed current-only projection.
        train_no_context_logits = teacher.predict(train, batch_size=16, no_context=True, deadline=deadline)
        np.save(out / 'teacher_train_no_context_logits.npy', train_no_context_logits, allow_pickle=False)
        write(out / 'teacher_train_no_context_logits_receipt.json', {
            'teacher_manifest_sha256': TEACHER_PIN, 'runtime_sha256': core_pin,
            'logits_sha256': sha(out / 'teacher_train_no_context_logits.npy'),
            'index_sha256': sha(out / 'train_index.json'), 'rows': len(train),
            'shape': list(train_no_context_logits.shape), 'dtype': str(train_no_context_logits.dtype),
            'inference': 'Authentic unchanged Model.predict(no_context=True); current global+tail retained',
            'distillation_split': 'TRAIN_ONLY', 'no_parameter_change': True})
        np.save(out / 'teacher_cal_eval_logits.npy', cal_logits, allow_pickle=False)
        np.save(out / 'teacher_cal_no_context_eval_logits.npy', cal_no_context, allow_pickle=False)
        user_only_cal = [dict(row, input=dict(row['input'], previous_utterances=[turn for turn in row['input']['previous_utterances'] if turn['speaker'] == 'USER'])) for row in cal]
        cal_user_only = teacher.predict(user_only_cal, batch_size=16, deadline=deadline)
        np.save(out / 'teacher_cal_user_only_eval_logits.npy', cal_user_only, allow_pickle=False)
        probe = train[:16]
        repeat = teacher.predict(probe, batch_size=16, deadline=deadline)
        report['teacher_repeat_parity_max_abs'] = float(np.abs(repeat - train_logits[:16]).max())
        del teacher
        if device == 'cuda':
            torch.cuda.empty_cache()
        phase = time.monotonic()
        def features(rows):
            result = []
            for row in rows:
                check_deadline(deadline, 'portable observed features')
                result.append(runtime.student_features(row['input']['current_utterance'],
                                                       row['input']['previous_utterances']))
            return np.asarray(result, dtype='float32')
        xtrain, xcal = features(train), features(cal)
        report['feature_seconds'] = time.monotonic() - phase
        write(out / 'feature_receipt.json', {
            'feature_dim': 768, 'observed_allowlist': ['current_utterance', 'previous_utterances.speaker', 'previous_utterances.text'],
            'all_current_characters_admitted': True, 'tail': 'last512 plus full global',
            'max_current_chars_TRAIN': max(len(r['input']['current_utterance']) for r in train),
            'TRAIN_current_over512': sum(len(r['input']['current_utterance']) > 512 for r in train),
            'TRAIN_current_over4096': sum(len(r['input']['current_utterance']) > 4096 for r in train),
            'CAL_current_over512': sum(len(r['input']['current_utterance']) > 512 for r in cal),
            'feature_seconds': report['feature_seconds'], 'no_metadata_or_labels_as_features': True})
        variant_models = {}
        variant_float = {}
        ablations = {}
        for name in ['mixed', 'hard', 'soft', 'mixed_no_context', 'hard_no_context', 'soft_no_context']:
            context = not name.endswith('_no_context')
            f = xtrain.copy()
            if not context:
                f[:, 512:] = 0
            distill_logits = train_logits if context else train_no_context_logits
            weight, bias, receipt = fit(f, train, distill_logits,
                                       name.split('_')[0], deadline, a.epochs)
            model = export(weight, bias, manifest['thresholds'])
            if not context:
                # Unused context weights are explicitly zeroed for portable parity.
                weight[:, 512:] = 0
                model = export(weight, bias, manifest['thresholds'])
                model['context_mode'] = 'current_only'
            receipt['teacher_context_projection'] = 'observed_prior' if context else 'current_only'
            variant_models[name] = model
            variant_float[name] = (weight, bias)
            qweight = np.asarray(model['weights']) * np.asarray(model['scales'])[:, None]
            cf = xcal.copy()
            if not context:
                cf[:, 512:] = 0
            prob = 1 / (1 + np.exp(-np.clip(cf @ qweight.T + np.asarray(model['bias']), -40, 40)))
            float_prob = 1 / (1 + np.exp(-np.clip(cf @ weight.T + bias, -40, 40)))
            ablations[name] = {'training': receipt, 'CAL_raw': metric(prob, cal, [.5] * 11),
                               'CAL_frozen_teacher_thresholds': metric(prob, cal, MIN_THRESHOLDS),
                               'quantization_probability_max_abs': float(np.abs(prob - float_prob).max())}
            if name == 'mixed':
                write(out / 'model.json', model)
                print(json.dumps({'phase': 'FIRST_RUNNABLE_REAL_STUDENT', 'seconds': time.monotonic() - started,
                                  'model': str(out / 'model.json'), 'TRAIN_rows': len(train)}), flush=True)
        for variant_name, variant_model in variant_models.items():
            (out / ('ablation_' + variant_name + '.json')).write_text(json.dumps(variant_model, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf8')
        model = variant_models['mixed_no_context']
        qweight = np.asarray(model['weights']) * np.asarray(model['scales'])[:, None]
        portable_xcal = xcal.copy()
        portable_xcal[:, 512:] = 0
        prob = 1 / (1 + np.exp(-np.clip(portable_xcal @ qweight.T + np.asarray(model['bias']), -40, 40)))
        # Deterministic existing-CAL group split. No threshold feedback from risk half.
        fit_indices = [i for i, r in enumerate(cal) if int(hashlib.sha256(r['group'].encode()).hexdigest()[:8], 16) % 2 == 0]
        risk_indices = [i for i in range(len(cal)) if i not in set(fit_indices)]
        fit_rows = [cal[i] for i in fit_indices]
        risk_rows = [cal[i] for i in risk_indices]
        if not fit_rows or not risk_rows:
            raise ValueError('Nonempty group CAL halves required')
        # Own student cutoffs fitted on quantized CAL-fit with a conservative
        # analytic int8 margin. Two L2-unit 256 blocks have total L1 <=32,
        # so rounded per-head int8 error is bounded by 16*scale. Full prior
        # versions would require 24*scale. No teacher active cutoff is copied.
        margins = [float(16 * scale + 1e-12) for scale in model['scales']]
        thresholds = [1.01] * 11
        base_thresholds = [1.01] * 11
        cutoffs = [1000000.0] * 11
        for j in [0, 1, 2, 5, 6, 7, 8, 9, 10]:
            candidates = []
            for threshold in [.5, .6, .7, .8, .9, .95, .99]:
                cutoff = float(np.log(threshold / (1 - threshold)))
                effective = float(1 / (1 + np.exp(-(cutoff + margins[j]))))
                head = metric(prob[fit_indices], fit_rows, [effective] * 11)['heads'][LABELS[j]]
                if head['TP'] + head['FP'] >= 10 and head['precision'] is not None and head['precision'] >= .95:
                    candidates.append((head['recall'] or 0, threshold))
            if candidates:
                base_thresholds[j] = max(candidates)[1]
                cutoffs[j] = float(np.log(base_thresholds[j] / (1 - base_thresholds[j])))
                thresholds[j] = float(1 / (1 + np.exp(-(cutoffs[j] + margins[j]))))
        model['thresholds'] = thresholds
        model['calibration_base_thresholds'] = base_thresholds
        model['logit_cutoffs'] = cutoffs
        model['quant_logit_margins'] = margins
        model['calibration_rule'] = 'Own quantized CAL-fit .95 empirical precision, >=10 predicted positives; analytic logit margin16*scale; disabled heads remain disabled'
        write(out / 'model.json', model)
        teacher_prob = 1 / (1 + np.exp(-np.clip(cal_logits, -40, 40)))
        teacher_nocontext_prob = 1 / (1 + np.exp(-np.clip(cal_no_context, -40, 40)))
        teacher_useronly_prob = 1 / (1 + np.exp(-np.clip(cal_user_only, -40, 40)))
        contextual_model = variant_models['mixed']
        contextual_weight = np.asarray(contextual_model['weights']) * np.asarray(contextual_model['scales'])[:, None]
        xcal_useronly = features(user_only_cal)
        shifted_prob = 1 / (1 + np.exp(-np.clip(xcal_useronly @ contextual_weight.T + np.asarray(contextual_model['bias']), -40, 40)))
        report.update(ablations=ablations, CAL_teacher=metric(teacher_prob, cal, MIN_THRESHOLDS),
                      CAL_teacher_no_context=metric(teacher_nocontext_prob, cal, MIN_THRESHOLDS),
                      CAL_teacher_USER_only=metric(teacher_useronly_prob, cal, MIN_THRESHOLDS),
                      CAL_contextual_student_USER_only=metric(shifted_prob, cal, MIN_THRESHOLDS),
                      CAL_student=metric(prob, cal, thresholds), CAL_fit=metric(prob[fit_indices], fit_rows, thresholds),
                      CAL_risk=metric(prob[risk_indices], risk_rows, thresholds), thresholds=thresholds,
                      calibration={'fit_rows': len(fit_rows), 'risk_rows': len(risk_rows),
                                   'group_intersection': 0, 'precision_target': .95,
                                   'min_positive_predictions_fit': 10, 'risk_used_to_tune': False,
                                   'own_base_thresholds': base_thresholds, 'effective_thresholds': thresholds,
                                   'quant_logit_margins': margins, 'teacher_active_cutoffs_copied': False,
                                   'qualified': False, 'reason': 'Existing CAL, exploratory small sample; no independent final qualification'},
                      teacher_student_probability_MAE=float(np.abs(prob - teacher_prob).mean()),
                      teacher_student_decision_agreement=float(((prob >= np.asarray(MIN_THRESHOLDS)) ==
                                                                (teacher_prob >= np.asarray(MIN_THRESHOLDS))).mean()))
        report['projection'] = {'export': 'current_only', 'choice_basis': 'broker observed USER raw history constraint; chosen before projection CAL results, not test performance',
                                'primary_teacher_logits': 'actual frozen V2 no_context=True; TRAIN only',
                                'full_teacher_unchanged': True, 'fabricated_assistant_context': False,
                                'CAL_nonempty_prior': sum(bool(r['input']['previous_utterances']) for r in cal),
                                'CAL_USER_only_nonempty_prior': sum(bool(r['input']['previous_utterances']) for r in user_only_cal)}
        float_weight, float_bias = variant_float['mixed_no_context']
        float_cal_logits = portable_xcal @ float_weight.T + float_bias
        quant_cal_logits = portable_xcal @ qweight.T + np.asarray(model['bias'])
        measured_error = np.abs(float_cal_logits - quant_cal_logits).max(0)
        if any(measured_error[j] > margins[j] for j in range(11)):
            raise ValueError('Analytic quantization margin violation')
        report['quantization'] = {'per_head_logit_error_max_CAL': measured_error.tolist(),
                                  'per_head_analytic_bound': margins, 'bound_basis': 'L2 unit blocks; Cauchy L1<=16/block; two active blocks; rounded weight error<=.5*scale',
                                  'CAL_feature_L1_max': float(np.abs(portable_xcal).sum(1).max()),
                                  'near_boundary_abstention': True}
        # Portable runtime parity against independent NumPy dequantized dot products.
        runtime_prob = []
        times = []
        statuses = {}
        for row in cal:
            check_deadline(deadline, 'portable CAL parity')
            tick = time.perf_counter()
            prediction = runtime.student_predict(row['input']['current_utterance'],
                                                  row['input']['previous_utterances'], model)
            times.append((time.perf_counter() - tick) * 1000)
            runtime_prob.append(prediction['scores'])
            statuses[prediction['status']] = statuses.get(prediction['status'], 0) + 1
            if prediction['bank_authority'] is not False or any(v in prediction['labels'] for v in LABELS[3:5] + LABELS[7:]):
                raise ValueError('Portable bank-authority invariant')
        parity = float(np.abs(np.asarray(runtime_prob) - prob).max())
        if parity > 1e-5:
            raise ValueError('Portable probability parity failure')
        report['portable_parity_max_abs'] = parity
        report['portable_latency_ms'] = {'rows': len(times), 'median': float(np.median(times)),
                                         'p95': float(np.percentile(times, 95)), 'max': max(times),
                                         'includes_model_validation': True}
        report['portable_status_counts'] = statuses
        report['runtime_verification'] = verify_runtime(runtime, runtime_path, model, cal)
        write(out / 'verification_receipt.json', report['runtime_verification'])
        # Closure has only inline JSON weights and the verified json/re runtime.
        raw = json.dumps(model, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        (out / 'model.json').write_text(raw + '\n', encoding='utf8')
        (out / 'runtime.py').write_text(runtime_path.read_text(encoding='utf8'), encoding='utf8')
        (out / 'train_source.py').write_text(Path(__file__).read_text(encoding='utf8'), encoding='utf8')
        inline = runtime_path.read_text(encoding='utf8') + '\nLIVE_STUDENT_MODEL = json.loads(' + repr(raw) + ')\n'
        if '{{' in inline or '}}' in inline:
            inline = inline.replace('{{', '{ {').replace('}}', '} }')
        if len(inline.encode('utf8')) > 60000:
            raise ValueError('Portable source closure exceeds 60KB')
        (out / 'inline_live.py').write_text(inline, encoding='utf8')
        closure = module(out / 'inline_live.py', 'student_inline_closure')
        input0 = cal[0]['input']
        if closure.student_predict(input0['current_utterance'], input0['previous_utterances'], closure.LIVE_STUDENT_MODEL) != runtime.student_predict(input0['current_utterance'], input0['previous_utterances'], model):
            raise ValueError('Inline closure parity failure')
        for source in sources:
            if sha(ROOT / source['path']) != source['sha256']:
                raise ValueError('Frozen source changed during run')
        if sha(teacher_dir / 'manifest.json') != TEACHER_PIN or sha(core_path) != core_pin:
            raise ValueError('Frozen teacher changed during run')
        risk_enabled = report['CAL_risk']['enabled_domain_macro_F1']
        base_enabled = ablations['hard_no_context']['CAL_frozen_teacher_thresholds']['enabled_domain_macro_F1']
        report.update(status='COMPLETED', seconds=time.monotonic() - started,
                      promotion='NONE_DIAGNOSTIC_SHADOW',
                      benefit={'risk_enabled_macro_F1': risk_enabled, 'hard_feature_baseline_enabled_macro_F1': base_enabled,
                               'qualified_benefit': False, 'reason': 'CAL only; parent sealed qualification pending; classic remains authority'},
                      model_bytes=(out / 'model.json').stat().st_size,
                      compact_model_bytes=len(raw.encode('utf8')),
                      runtime_bytes=runtime_path.stat().st_size,
                      inline_source_bytes=(out / 'inline_live.py').stat().st_size,
                      runtime_sha256=sha(runtime_path), trainer_sha256=sha(Path(__file__)),
                      model_sha256=sha(out / 'model.json'), inline_sha256=sha(out / 'inline_live.py'))
        design_path = ROOT / 'analysis/final-sprint-live-layer-design-20261011.json'
        report['design_review'] = {'sha256': sha(design_path), 'path': design_path.relative_to(ROOT).as_posix(),
            'deviations': ['User-requested ord FNV; design proposed UTF8-byte hash',
                           'L2 rather than L1; analytic int8 logit margin16*scale for two active blocks',
                           'lower(), word/bigram/character3, no number masking; tail512 chars rather than64 tokens',
                           'Required API probability scores via builtin power sigmoid; design proposed logit-only',
                           'User-bounded6000 TRAIN/1024 CAL; fixed100 full-batch epochs lr.04 AdamW weight_decay.01',
                           'Unweighted hard BCE; .5 hard/.5 temperature2 soft objective, not proposed class weights/.2 KD'],
            'parent_owned': ['extractor_copy ingress, no attested engine raw claim', 'Recipient/DOB/phone bypass; security answers excluded from history',
                             'Same-turn broker/freshness and classic bank actions', 'Actual platform witness and sealed qualification'],
            'actual_export_context': 'current_only', 'live_deployment_claim': False}
        report['exposure_audit'] = {'trainer_only_frozen_TRAIN_CAL': True, 'EVAL96_rows_opened': False, 'fresh64_rows_opened': False,
            'runtime_worker_incidental_legacy_fixture_exposure': True,
            'details': 'Runtime worker broad *.py search surfaced repayment-semantic/build_packet.py HELDOUT H04/H06 and S02-S05 snippets; not used for features, fit, cutoffs or verification. Output truncated; complete scanned-file inventory unavailable.',
            'worker_stopped': True, 'qualification_claim': False,
            'design_read_contains_previously_exposed96_aggregate': True, 'aggregate_used_for_tuning': False}
        write(out / 'training_receipt.json', report)
        write(out / 'evaluation_receipt.json', {k: v for k, v in report.items()
              if k.startswith('CAL') or k in ['ablations', 'thresholds', 'calibration', 'portable_parity_max_abs',
                                              'portable_latency_ms', 'portable_status_counts', 'teacher_student_probability_MAE',
                                              'teacher_student_decision_agreement', 'teacher_repeat_parity_max_abs', 'promotion', 'benefit',
                                              'projection', 'quantization', 'runtime_verification', 'design_review', 'exposure_audit']})
        pins = {p.name: sha(p) for p in out.iterdir() if p.is_file()}
        write(out / 'manifest.json', {'schema': 'live_v2_student.bundle.v1', 'files': pins,
                                     'teacher_manifest_sha256': TEACHER_PIN, 'bank_authority': False,
                                     'runtime_sha256': sha(runtime_path), 'trainer_sha256': sha(Path(__file__)),
                                     'trainer_only_TRAIN_CAL_admission': True,
                                     'runtime_worker_incidental_legacy_fixture_exposure': True,
                                     'flat_runtime_model_export': {'runtime': 'runtime.py', 'model': 'model.json'},
                                     'context_mode': 'current_only', 'promotion': 'NONE_DIAGNOSTIC_SHADOW'})
        write(ROOT / 'analysis/final-sprint-v2-student-20261011.current.json', report)
        print(json.dumps({'status': 'COMPLETED', 'seconds': report['seconds'], 'rows': len(train),
                          'inline_bytes': report['inline_source_bytes'], 'CAL_enabled_macro_F1': report['CAL_student']['enabled_domain_macro_F1'],
                          'promotion': report['promotion']}), flush=True)
    except BaseException as error:
        report.update(status='FAILED', seconds=time.monotonic() - started,
                      error_class=type(error).__name__, error=str(error), promotion='NONE')
        write(out / 'training_receipt.json', report)
        raise


if __name__ == '__main__':
    main()
