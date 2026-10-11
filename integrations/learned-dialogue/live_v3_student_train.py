"""V3 PORTABLE STUDENT: two full frozen TRAIN passes, local only.

This is a 768-feature int8 linear classifier, not a MiniLM encoder. Existing
CAL supplies cutoffs and reporting only. No EVAL file is admitted or opened.
"""
import argparse
import collections
import hashlib
import importlib.util
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'live_v3_student'
PIN = '7eca3b016b47ec20f1b1fd9e207c71a0c72ece9bf91f4e2c28ecd411dcb59189'
SEED = 20261011
NTRAIN = 168821
NCAL = 16896
EPOCHS = 2
LABELS = ['proposal', 'dispute', 'correction', 'current_affirm', 'current_withdraw',
          'uncertain', 'reported_third_party', 'AFFIRM', 'NEGATE', 'INFORM', 'REQUEST']


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def write(path, obj):
    path.write_bytes((json.dumps(obj, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf8'))


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check(deadline, phase):
    if time.monotonic() >= deadline:
        raise TimeoutError('V3 bounded deadline: ' + phase)


def admitted(row, split):
    if row['split'] != split or type(row['id']) is not str or type(row['group']) is not str:
        raise ValueError('Frozen row identity/split')
    values = []
    masks = []
    for target, mask, n in [('domain_labels', 'domain_mask', 7), ('aux_labels', 'aux_mask', 4)]:
        if type(row[target]) is not list or len(row[target]) != n or any(type(v) not in (int, float) or v not in (0, 1) for v in row[target]):
            raise ValueError('Frozen binary targets')
        if type(row[mask]) is not list or len(row[mask]) != n or any(type(v) is not bool for v in row[mask]):
            raise ValueError('Frozen boolean masks')
        values.extend(row[target]); masks.extend(row[mask])
    inp = row['input']
    if type(inp) is not dict or set(inp) != {'current_utterance', 'previous_utterances'}:
        raise ValueError('Observed input allowlist')
    return values, masks


def frozen_sources():
    teacher = HERE / 'minilm_ft_v2/model'
    if sha(teacher / 'manifest.json') != PIN:
        raise ValueError('Frozen V2 manifest changed')
    teacher_manifest = json.loads((teacher / 'manifest.json').read_text(encoding='utf8'))
    for name, pin in teacher_manifest['files'].items():
        if sha(teacher / name) != pin:
            raise ValueError('Frozen V2 file changed: ' + name)
    training = json.loads((teacher / 'training.json').read_text(encoding='utf8'))
    result = []
    for packet in ['minilm-finetune-v1', 'minilm-finetune-v2-data']:
        directory = ROOT / 'research/customer-benchmark' / packet
        freeze = json.loads((directory / 'freeze.json').read_text(encoding='utf8'))
        pins = {x['path']: x for x in freeze['files']}
        for split in ['train', 'cal']:
            path = directory / (split + '.jsonl')
            rel = path.relative_to(ROOT).as_posix()
            actual = sha(path)
            teacher_pin = next(v for k, v in training['input_sha256'].items() if k.replace('\\', '/').endswith(rel))
            if actual != teacher_pin or actual != pins[rel]['sha256'] or path.stat().st_size != pins[rel]['bytes']:
                raise ValueError('Frozen TRAIN/CAL source changed: ' + rel)
            result.append({'path': rel, 'sha256': actual, 'bytes': path.stat().st_size,
                           'split': split.upper(), 'packet': packet, 'freeze_sha256': sha(directory / 'freeze.json')})
    core_pin = next(v for k, v in training['source_sha256'].items() if k.replace('\\', '/') == 'minilm_ft_v2/runtime/minilm_ft_core.py')
    if sha(HERE / 'minilm_ft_v2/runtime/minilm_ft_core.py') != core_pin:
        raise ValueError('Frozen authentic V2 runtime changed')
    return result, teacher_manifest, core_pin


def cached_teacher():
    import numpy as np
    directory = HERE / 'live_v2_student/current_only_run'
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf8'))
    names = ['train_index.json', 'teacher_train_no_context_logits.npy', 'teacher_train_no_context_logits_receipt.json']
    for name in names:
        if sha(directory / name) != manifest['files'][name]:
            raise ValueError('Pinned cached teacher artifact changed')
    receipt = json.loads((directory / names[2]).read_text(encoding='utf8'))
    if receipt['teacher_manifest_sha256'] != PIN or receipt['rows'] != 6000 or receipt['distillation_split'] != 'TRAIN_ONLY':
        raise ValueError('Authentic cached V2 TRAIN provenance')
    if receipt['logits_sha256'] != sha(directory / names[1]) or receipt['index_sha256'] != sha(directory / names[0]):
        raise ValueError('Cached logits/index closure')
    index = json.loads((directory / names[0]).read_text(encoding='utf8'))
    logits = np.load(directory / names[1], allow_pickle=False)
    if logits.shape != (6000, 11) or not np.isfinite(logits).all():
        raise ValueError('Cached teacher logits shape/finite')
    lookup = {(r['source_path'], r['line']): (i, r) for i, r in enumerate(index)}
    if len(lookup) != 6000:
        raise ValueError('Cached teacher duplicate source rows')
    pins = {name: sha(directory / name) for name in names}
    return lookup, logits, {'directory': directory.relative_to(ROOT).as_posix(), 'files': pins,
                           'teacher_manifest_sha256': PIN, 'rows': 6000,
                           'projection': 'authentic frozen V2 no_context=True', 'new_teacher_forward': False}


def fit(x, y, mask, indices, deadline, report, arm, kd=None, epochs=EPOCHS):
    import numpy as np
    import torch
    torch.manual_seed(SEED)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    head = torch.nn.Linear(768, 11, device=device)
    with torch.no_grad():
        head.weight.zero_(); head.bias.zero_()
    optimizer = torch.optim.AdamW(head.parameters(), lr=.02, weight_decay=.001)
    positive = (y[indices] * mask[indices]).sum(0)
    negative = ((1 - y[indices]) * mask[indices]).sum(0)
    pos_weight = torch.tensor(np.clip(np.sqrt(negative / np.maximum(1, positive)), 1, 5), dtype=torch.float32, device=device)
    seen = np.zeros(len(x), dtype=bool)
    curves = []
    steps = 0
    rng = np.random.default_rng(SEED)
    phase = time.monotonic()
    for epoch in range(epochs):
        order = rng.permutation(indices)
        epoch_seen = np.zeros(len(x), dtype=bool)
        total_loss = 0.0
        batches = 0
        for start in range(0, len(order), 512):
            check(deadline, arm + ' optimization')
            selected = order[start:start + 512]
            tx = torch.from_numpy(np.asarray(x[selected])).to(device)
            ty = torch.from_numpy(y[selected]).to(device)
            tm = torch.from_numpy(mask[selected].astype('float32')).to(device)
            known = tm.sum(0).clamp(min=1)
            active = (tm.sum(0) > 0).float()
            def reduce(elements):
                mean = (elements * tm).sum(0) / known
                return mean[:7].sum() / active[:7].sum().clamp(min=1) + .25 * mean[7:].sum() / active[7:].sum().clamp(min=1)
            optimizer.zero_grad(set_to_none=True)
            z = head(tx)
            hard = reduce(torch.nn.functional.binary_cross_entropy_with_logits(z, ty, reduction='none', pos_weight=pos_weight))
            if kd is not None:
                teacher = torch.from_numpy(kd[selected]).to(device)
                soft = 4 * reduce(torch.nn.functional.binary_cross_entropy_with_logits(z / 2, torch.sigmoid(teacher / 2), reduction='none'))
                loss = hard + .2 * soft
            else:
                loss = hard
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite actual optimizer loss')
            loss.backward(); torch.nn.utils.clip_grad_norm_(head.parameters(), 1); optimizer.step()
            epoch_seen[selected] = True; seen[selected] = True
            total_loss += float(loss.detach()); batches += 1; steps += 1
            if arm == 'full_hard' and (steps % 50 == 0 or start + 512 >= len(order)):
                report.update(phase='FULL_TRAIN_OPTIMIZATION', optimizer_steps=steps,
                              unique_TRAIN_rows_seen=int(seen.sum()), completed_epochs=len(curves),
                              elapsed_seconds=time.monotonic() - report['_started'], current_epoch=epoch,
                              current_epoch_rows_seen=int(epoch_seen.sum()))
                write(OUT / 'progress_receipt.json', {k: v for k, v in report.items() if k != '_started'})
                print(json.dumps({'arm': arm, 'epoch': epoch, 'steps': steps,
                                  'unique_rows_seen': int(seen.sum()), 'seconds': report['elapsed_seconds']}), flush=True)
        if int(epoch_seen[indices].sum()) != len(indices):
            raise ValueError('An admitted TRAIN row was omitted')
        curves.append({'epoch': epoch, 'actual_rows_seen': len(indices), 'batches': batches,
                       'mean_loss': total_loss / batches, 'order_sha256': hashlib.sha256(order.astype('int64').tobytes()).hexdigest(),
                       'seen_bitmap_sha256': hashlib.sha256(np.packbits(epoch_seen).tobytes()).hexdigest()})
    weight = head.weight.detach().cpu().numpy(); bias = head.bias.detach().cpu().numpy()
    if np.any(weight[:, 512:] != 0):
        raise ValueError('Unused prior block must remain exactly zero')
    return weight, bias, {'arm': arm, 'epochs': epochs, 'actual_unique_rows_seen': int(seen.sum()),
                         'actual_row_exposures': len(indices) * epochs, 'optimizer_steps': steps,
                         'curves': curves, 'seconds': time.monotonic() - phase,
                         'pos_weight': pos_weight.cpu().tolist(), 'batch_size': 512,
                         'lr': .02, 'weight_decay': .001, 'gradient_clip': 1,
                         'objective': 'masked positive-weighted mean domain-head BCE + .25 mean source-act-head BCE',
                         'KD': 'hard + .2*T*T*same-mask soft BCE; T=2' if kd is not None else None,
                         'CAL_gradient_rows': 0, 'device': device}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--seconds', type=int, default=840)
    args = p.parse_args()
    if not 1 <= args.seconds <= 900:
        raise ValueError('Local run cap <=900 seconds')
    started = time.monotonic(); deadline = started + args.seconds
    if OUT.exists():
        raise ValueError('Refuse overwrite; inspect the existing owned run first')
    OUT.mkdir()
    report = {'status': 'RUNNING', 'phase': 'PREFLIGHT', 'owned_pid': os.getpid(),
              'schema': 'live_v3_student.readiness.v1', 'model_kind': 'V3_PORTABLE_STUDENT_NOT_MINILM',
              'seed': SEED, 'declared_full_TRAIN_rows': NTRAIN, 'declared_full_epochs': EPOCHS,
              'unique_TRAIN_rows_seen': 0, 'deadline_seconds': args.seconds,
              'default_enabled': False, 'bank_authority': False, 'financial_authorization': 'UNKNOWN',
              'cloud_launches': 0, 'EVAL_rows_opened': 0, 'teacher_manifest_sha256': PIN,
              'selection_contract': 'Full-data hard model chosen before CAL; matched cached6k KD is auxiliary only',
              '_started': started}
    write(OUT / 'progress_receipt.json', {k: v for k, v in report.items() if k != '_started'})
    try:
        import numpy as np
        import torch
        torch.set_num_threads(4)
        report['local_device'] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'
        # Exact archived source closure, without writing to any V2 artifact.
        helper_source = HERE / 'live_v2_student/deployment_current_only/train_source.py'
        helper_manifest = json.loads((helper_source.parent / 'manifest.json').read_text(encoding='utf8'))
        if sha(helper_source) != helper_manifest['files']['train_source.py']:
            raise ValueError('Archived helper source changed')
        (OUT / 'training_helpers.py').write_bytes(helper_source.read_bytes())
        helpers = load_module(OUT / 'training_helpers.py', 'v3_archived_training_helpers')
        runtime_source = helper_source.parent / 'runtime.py'
        if sha(runtime_source) != helper_manifest['files']['runtime.py']:
            raise ValueError('Frozen portable feature source changed')
        text = runtime_source.read_text(encoding='utf8').replace('STUDENT != V2', 'V3 PORTABLE STUDENT != full MiniLM V2').replace('live_v2_student.v1', 'live_v3_student.v1')
        text = text.replace('model["context_mode"] not in ("current_only", "observed_prior")', 'model["context_mode"] != "current_only"')
        (OUT / 'runtime.py').write_bytes(text.encode('utf8'))
        runtime = load_module(OUT / 'runtime.py', 'v3_portable_runtime')
        sources, teacher_manifest, core_pin = frozen_sources()
        lookup, cached_logits, cache_receipt = cached_teacher()
        report['source_pins'] = sources
        write(OUT / 'source_manifest.json', {'sources': sources, 'teacher_manifest_sha256': PIN,
              'teacher_files_verified': teacher_manifest['files'], 'teacher_runtime_sha256': core_pin,
              'feature_source_sha256': sha(runtime_source), 'archived_training_helpers_sha256': sha(OUT / 'training_helpers.py')})
        write(OUT / 'cached_teacher_receipt.json', cache_receipt)
        x = np.lib.format.open_memmap(OUT / 'train_features.npy', mode='w+', dtype='float32', shape=(NTRAIN, 768))
        cx = np.lib.format.open_memmap(OUT / 'cal_features.npy', mode='w+', dtype='float32', shape=(NCAL, 768))
        y = np.zeros((NTRAIN, 11), dtype='float32'); mask = np.zeros((NTRAIN, 11), dtype=bool)
        cy = np.zeros((NCAL, 11), dtype='float32'); cmask = np.zeros((NCAL, 11), dtype=bool)
        groups = {'TRAIN': set(), 'CAL': set()}; ids = set(); rows = []
        counters = {'TRAIN': 0, 'CAL': 0}; source_counts = {}
        teacher_rows = np.full(6000, -1, dtype='int64')
        cache = collections.OrderedDict(); cache_hits = 0
        lengths = {'TRAIN': {'max': 0, 'over512': 0, 'over4096': 0}, 'CAL': {'max': 0, 'over512': 0, 'over4096': 0}}
        phase = time.monotonic()
        streams = {s: open(OUT / (s.lower() + '_index.jsonl'), 'w', encoding='utf8', newline='\n') for s in ['TRAIN', 'CAL']}
        try:
            for source_number, source in enumerate(sources):
                split = source['split']; source_counts[source['path']] = 0
                with open(ROOT / source['path'], encoding='utf8') as stream:
                    for line_number, line in enumerate(stream, 1):
                        check(deadline, 'full source features')
                        if not line.strip():
                            continue
                        row = json.loads(line); values, masks = admitted(row, split)
                        current = row['input']['current_utterance']; previous = row['input']['previous_utterances']
                        if not runtime._valid_input(current, previous):
                            raise ValueError('Frozen observed text validation')
                        if row['id'] in ids:
                            raise ValueError('Duplicate admitted ID')
                        ids.add(row['id']); groups[split].add(row['group'])
                        at = counters[split]; counters[split] += 1; source_counts[source['path']] += 1
                        length = len(current); lengths[split]['max'] = max(lengths[split]['max'], length)
                        lengths[split]['over512'] += length > 512; lengths[split]['over4096'] += length > 4096
                        if current in cache:
                            feature = cache.pop(current); cache[current] = feature; cache_hits += 1
                        else:
                            feature = np.asarray(runtime.student_features(current, previous, no_context=True), dtype='float32')
                            cache[current] = feature
                            if len(cache) > 2048:
                                cache.popitem(last=False)
                        destination, targets, masks_out = (x, y, mask) if split == 'TRAIN' else (cx, cy, cmask)
                        destination[at] = feature; targets[at] = values; masks_out[at] = masks
                        input_hash = hashlib.sha256(json.dumps(row['input'], sort_keys=True, ensure_ascii=False).encode('utf8')).hexdigest()
                        row_hash = hashlib.sha256(line.encode('utf8')).hexdigest()
                        index = {'index': at, 'source_number': source_number, 'source_path': source['path'], 'source_sha256': source['sha256'],
                                 'line': line_number, 'id': row['id'], 'group': row['group'], 'split': split,
                                 'row_sha256': row_hash, 'observed_sha256': input_hash,
                                 'current_feature_input_sha256': hashlib.sha256(current.encode('utf8')).hexdigest(),
                                 'domain_labels': row['domain_labels'], 'domain_mask': row['domain_mask'],
                                 'aux_labels': row['aux_labels'], 'aux_mask': row['aux_mask']}
                        streams[split].write(json.dumps(index, ensure_ascii=False, separators=(',', ':')) + '\n')
                        if split == 'TRAIN' and (source['path'], line_number) in lookup:
                            teacher_at, old = lookup[(source['path'], line_number)]
                            for key in ['source_path', 'source_sha256', 'line', 'id', 'group', 'split', 'row_sha256', 'observed_sha256',
                                        'domain_labels', 'domain_mask', 'aux_labels', 'aux_mask']:
                                if index[key] != old[key]:
                                    raise ValueError('Cached teacher identity/input/mask mismatch: ' + key)
                            teacher_rows[teacher_at] = at
                        if split == 'CAL':
                            rows.append(row)
                        if counters[split] % 10000 == 0:
                            report.update(phase='FULL_SOURCE_FEATURES', features_rows=dict(counters),
                                          elapsed_seconds=time.monotonic() - started)
                            write(OUT / 'progress_receipt.json', {k: v for k, v in report.items() if k != '_started'})
                            print(json.dumps({'phase': report['phase'], 'rows': counters, 'seconds': report['elapsed_seconds']}), flush=True)
        finally:
            for stream in streams.values():
                stream.close()
        x.flush(); cx.flush()
        if counters != {'TRAIN': NTRAIN, 'CAL': NCAL} or groups['TRAIN'] & groups['CAL'] or np.any(teacher_rows < 0):
            raise ValueError('Full row/group/cache admission proof failed')
        report.update(TRAIN_rows=NTRAIN, CAL_rows=NCAL, source_row_counts=source_counts,
                      TRAIN_groups=len(groups['TRAIN']), CAL_groups=len(groups['CAL']), TRAIN_CAL_group_intersection=0,
                      feature_seconds=time.monotonic() - phase, feature_cache_hits=cache_hits, current_lengths=lengths,
                      feature_matrix_bytes=int(x.nbytes), masks={'TRAIN': {'known': mask.sum(0).tolist(), 'positive': (y * mask).sum(0).tolist()},
                                                              'CAL': {'known': cmask.sum(0).tolist(), 'positive': (cy * cmask).sum(0).tolist()}},
                      cached_teacher_rows_matched=6000, full_current_text_admitted=True)
        write(OUT / 'admission_receipt.json', {k: v for k, v in report.items() if k != '_started'})
        np.save(OUT / 'cached_teacher_TRAIN_indices.npy', teacher_rows, allow_pickle=False)
        weight, bias, fit_receipt = fit(x, y, mask, np.arange(NTRAIN), deadline, report, 'full_hard')
        report['full_fit'] = fit_receipt
        report['unique_TRAIN_rows_seen'] = fit_receipt['actual_unique_rows_seen']
        np.savez(OUT / 'float_weights_full_hard.npz', weight=weight, bias=bias)
        model = helpers.export(weight, bias, [1.01] * 11)
        model.update(schema='live_v3_student.v1', model_kind='V3_PORTABLE_STUDENT_HARD_LINEAR_FNV768_INT8',
                     context_mode='current_only', default_enabled=False, mode='diagnostic_shadow')
        qweight = np.asarray(model['weights'], dtype='float32') * np.asarray(model['scales'], dtype='float64')[:, None]
        cal_logits = np.asarray(cx) @ qweight.T + np.asarray(model['bias'])
        prob = 1 / (1 + np.exp(-np.clip(cal_logits, -40, 40)))
        report['CAL_raw'] = helpers.metric(prob, rows, [.5] * 11)
        # Main full hard model remains the predeclared selection.
        ablations = {}
        kd = np.zeros((NTRAIN, 11), dtype='float32'); kd[teacher_rows] = cached_logits
        if time.monotonic() + 120 < deadline:
            for arm, soft in [('matched6k_hard', None), ('matched6k_KD', kd)]:
                aw, ab, ar = fit(x, y, mask, teacher_rows, deadline, report, arm, kd=soft)
                am = helpers.export(aw, ab, [1.01] * 11)
                am.update(schema='live_v3_student.v1', model_kind='V3_PORTABLE_STUDENT_' + arm, context_mode='current_only', default_enabled=False)
                aqw = np.asarray(am['weights']) * np.asarray(am['scales'])[:, None]
                ap = 1 / (1 + np.exp(-np.clip(np.asarray(cx) @ aqw.T + np.asarray(am['bias']), -40, 40)))
                ablations[arm] = {'fit': ar, 'CAL_raw': helpers.metric(ap, rows, [.5] * 11),
                                  'matched_input_mask_id_verified_rows': 6000, 'used_for_main_selection': False}
                (OUT / (arm + '_model.json')).write_bytes(json.dumps(am, separators=(',', ':'), allow_nan=False).encode('utf8'))
        else:
            ablations['status'] = 'SKIPPED_BOUNDED_DEADLINE; full fit takes priority'
        report['matched6k_ablations'] = ablations
        fit_i = np.asarray([i for i, row in enumerate(rows) if int(hashlib.sha256(row['group'].encode()).hexdigest()[:8], 16) % 2 == 0])
        fit_set = set(fit_i.tolist()); risk_i = np.asarray([i for i in range(NCAL) if i not in fit_set])
        if not len(fit_i) or not len(risk_i):
            raise ValueError('Nonempty fixed CAL group halves')
        fit_rows = [rows[i] for i in fit_i]; risk_rows = [rows[i] for i in risk_i]
        if {r['group'] for r in fit_rows} & {r['group'] for r in risk_rows}:
            raise ValueError('CAL fit/risk group overlap')
        margins = [float(16 * s + 1e-12) for s in model['scales']]
        thresholds = [1.01] * 11; bases = [1.01] * 11; cutoffs = [1000000.0] * 11
        for j in [0, 1, 2, 5, 6, 7, 8, 9, 10]:
            candidates = []
            for base in [.5, .6, .7, .8, .9, .95, .99]:
                cutoff = float(np.log(base / (1 - base))); effective = float(1 / (1 + np.exp(-(cutoff + margins[j]))))
                known = cmask[fit_i, j]; pred = (prob[fit_i, j] >= effective) & known
                tp = int((pred & (cy[fit_i, j] == 1)).sum()); fp = int((pred & (cy[fit_i, j] == 0)).sum())
                positives = int(((cy[fit_i, j] == 1) & known).sum())
                if tp + fp >= 10 and tp / (tp + fp) >= .95:
                    candidates.append((tp / max(1, positives), base, effective, cutoff))
            if candidates:
                _, bases[j], thresholds[j], cutoffs[j] = max(candidates)
        model.update(thresholds=thresholds, calibration_base_thresholds=bases, logit_cutoffs=cutoffs,
                     quant_logit_margins=margins, calibration_rule='Own quantized CAL-fit >=.95 precision and >=10 predictions, analytic16*scale margin')
        report.update(CAL_selected=helpers.metric(prob, rows, thresholds), CAL_fit=helpers.metric(prob[fit_i], fit_rows, thresholds),
                      CAL_risk=helpers.metric(prob[risk_i], risk_rows, thresholds), thresholds=thresholds,
                      calibration={'fit_rows': len(fit_i), 'risk_rows': len(risk_i), 'group_intersection': 0,
                                   'rule': 'SHA256(group) first8 hex modulo2; fixed before gradients',
                                   'CAL_gradient_rows': 0, 'risk_used_to_tune': False, 'empirical_precision_target': .95,
                                   'qualified': False, 'min_predictions': 10, 'own_base_thresholds': bases})
        error = np.abs((np.asarray(cx) @ weight.T + bias) - cal_logits).max(0)
        if np.any(error > np.asarray(margins)):
            raise ValueError('Portable analytic weight error bound')
        report['quantization'] = {'CAL_logit_max_error_per_head': error.tolist(), 'analytic_bound_per_head': margins,
                                  'basis': 'Two256 L2-unit blocks => L1<=32; rounded per-weight error<=scale/2', 'passes': True}
        report['runtime_verification'] = helpers.verify_runtime(runtime, OUT / 'runtime.py', model, rows[:1024])
        # Fixed latency/parity sample spans both domain and source-act CAL.
        parity_i = np.linspace(0, NCAL - 1, 1024, dtype=int)
        times = []; runtime_prob = []; status_counts = {}
        for i in parity_i:
            check(deadline, 'portable parity')
            inp = rows[i]['input']; tick = time.perf_counter()
            prediction = runtime.student_predict(inp['current_utterance'], inp['previous_utterances'], model)
            times.append((time.perf_counter() - tick) * 1000); runtime_prob.append(prediction['scores'])
            status_counts[prediction['status']] = status_counts.get(prediction['status'], 0) + 1
            if prediction['bank_authority'] is not False or prediction['financial_authorization'] != 'UNKNOWN' or not set(prediction['labels']) <= set(LABELS[i] for i in [0, 1, 2, 5, 6]):
                raise ValueError('Runtime financial boundary')
        parity = float(np.abs(np.asarray(runtime_prob) - prob[parity_i]).max())
        if parity > 1e-5:
            raise ValueError('Actual portable sigmoid parity')
        report.update(portable_parity_max_abs=parity, portable_latency_ms={'rows': 1024, 'median': float(np.median(times)),
                      'p95': float(np.percentile(times, 95)), 'max': max(times), 'model_validation_included': True}, portable_status_counts=status_counts)
        raw = json.dumps(model, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        (OUT / 'model.json').write_bytes((raw + '\n').encode('utf8'))
        inline = text + '\nLIVE_STUDENT_MODEL = json.loads(' + repr(raw) + ')\n'
        if '{{' in inline or '}}' in inline or len(inline.encode('utf8')) > 60000:
            raise ValueError('Pure portable inline source closure')
        (OUT / 'inline_live.py').write_bytes(inline.encode('utf8'))
        frozen = load_module(OUT / 'inline_live.py', 'v3_frozen_inline')
        inp = rows[0]['input']
        if frozen.student_predict(inp['current_utterance'], [], frozen.LIVE_STUDENT_MODEL) != runtime.student_predict(inp['current_utterance'], [], model):
            raise ValueError('Frozen inline API closure')
        for source in sources:
            if sha(ROOT / source['path']) != source['sha256']:
                raise ValueError('Source changed during full fit')
        if sha(HERE / 'minilm_ft_v2/model/manifest.json') != PIN:
            raise ValueError('V2 teacher changed')
        report.update(status='COMPLETED', phase='FROZEN_SHADOW_HANDOFF', seconds=time.monotonic() - started,
                      actual_full_TRAIN_rows_seen=fit_receipt['actual_unique_rows_seen'], actual_full_TRAIN_exposures=fit_receipt['actual_row_exposures'],
                      epochs_completed=fit_receipt['epochs'], default_enabled=False, promotion='NONE_DIAGNOSTIC_SHADOW',
                      model_bytes=(OUT / 'model.json').stat().st_size, runtime_bytes=(OUT / 'runtime.py').stat().st_size,
                      inline_bytes=(OUT / 'inline_live.py').stat().st_size,
                      model_sha256=sha(OUT / 'model.json'), runtime_sha256=sha(OUT / 'runtime.py'),
                      trainer_sha256=sha(Path(__file__)), feature_bytes=int(x.nbytes),
                      peak_GPU_bytes=torch.cuda.max_memory_allocated() if torch.cuda.is_available() else 0,
                      risk_gate={'pass': False, 'reason': 'Default remains disabled; source/live/fresh qualification parent-owned; empirical CAL is not qualification'},
                      inherited_legacy_fixture_exposure='V2 runtime worker reported incidental unrelated heldout snippets; no such sources opened or used in V3',
                      new_semantic_probes=0)
        del report['_started']
        (OUT / 'train_source.py').write_bytes(Path(__file__).read_bytes())
        write(OUT / 'training_receipt.json', report)
        write(OUT / 'readiness_receipt.json', report)
        write(OUT / 'progress_receipt.json', report)
        pins = {path.name: sha(path) for path in OUT.iterdir() if path.is_file()}
        write(OUT / 'manifest.json', {'schema': 'live_v3_student.bundle.v1', 'files': pins,
              'model_kind': 'V3_PORTABLE_STUDENT_NOT_MINILM', 'default_enabled': False,
              'bank_authority': False, 'financial_authorization': 'UNKNOWN', 'teacher_manifest_sha256': PIN,
              'runtime_sha256': sha(OUT / 'runtime.py'), 'model_sha256': sha(OUT / 'model.json'),
              'flat_runtime_model_export': {'runtime': 'runtime.py', 'model': 'model.json'},
              'TRAIN_rows_seen': NTRAIN, 'epochs': EPOCHS, 'context_mode': 'current_only', 'promotion': 'NONE_DIAGNOSTIC_SHADOW'})
        write(ROOT / 'analysis/final-sprint-v3-student-20261011.json', report)
        print(json.dumps({'status': 'COMPLETED', 'seconds': report['seconds'], 'TRAIN_rows_seen': NTRAIN,
                          'epochs': EPOCHS, 'inline_bytes': report['inline_bytes'], 'CAL_macro_F1': report['CAL_raw']['domain_macro_F1']}), flush=True)
    except BaseException as error:
        report.update(status='FAILED', seconds=time.monotonic() - started, error_class=type(error).__name__, error=str(error), default_enabled=False)
        report.pop('_started', None); write(OUT / 'readiness_receipt.json', report); write(OUT / 'progress_receipt.json', report)
        raise


if __name__ == '__main__':
    main()
