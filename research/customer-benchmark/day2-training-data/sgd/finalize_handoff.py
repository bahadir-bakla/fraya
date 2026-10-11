"""Add an independently pinned final handoff; never rewrite the frozen packet.

Only publisher TRAIN-derived data is scanned for counts and integrity. No model
outputs are opened, no model is imported, and no fitting is performed.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
FULL = HERE / 'full-v1'
MANIFEST_SHA = '7176ce8bf20c7e6adce899a276f7de0c042e0e33eb63999462264ca6c1843513'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def ref(path):
    return {'path': path.relative_to(REPO).as_posix(), 'sha256': sha(path)}


def add_only(path, data):
    content = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    if path.exists():
        if path.read_bytes() != content:
            raise RuntimeError(f'Existing supplemental file differs; choose a new version: {path}')
    else:
        path.write_bytes(content)


def main():
    assert sha(FULL / 'manifest.json') == MANIFEST_SHA
    manifest = json.loads((FULL / 'manifest.json').read_bytes())
    validation = json.loads((FULL / 'freeze-validation.json').read_bytes())
    assert validation['status'] == 'passed' and validation['manifest_sha256'] == MANIFEST_SHA
    schema = json.loads((HERE / 'service-schema.json').read_bytes())
    for key in ['processor', 'collector', 'service_schema', 'source_inventory', 'split_plan']:
        assert sha(REPO / manifest[key]['path']) == manifest[key]['sha256']
    split_counts = {s: Counter() for s in ['TRAIN', 'CAL', 'EVAL']}
    for shard in manifest['outputs']:
        count = split_counts[shard['split']]
        h = hashlib.sha256(); rows = 0; size = 0
        with (REPO / shard['path']).open('rb') as handle:
            for line in handle:
                h.update(line); size += len(line); rows += 1
                row = json.loads(line)
                count['USER_examples'] += 1
                count['bank_policy_row_mask_true'] += row['bank_policy_target_mask']
                count['ledger_row_mask_true'] += row['ledger_target_mask']
                for frame in row['targets']['frames']:
                    count['publisher_frames'] += 1
                    count['service_frames:' + frame['service']] += 1
                    for head, mask in frame['head_masks'].items():
                        count['head_mask_true:' + head] += bool(mask)
                        count['head_mask_false:' + head] += not bool(mask)
                    count['DELETE_mask_true'] += frame['DELETE_mask']
                    for update in frame['belief_updates']:
                        count['belief_update:' + (update['publisher_map_update'] if update['update_mask'] else 'MASKED')] += 1
                    for values in frame['slot_values'].values():
                        for value in values:
                            count['state_value_targets'] += 1
                            count['state_value_recoverable'] += value['value_recoverability_mask']
                    for action in frame['actions']:
                        count['publisher_action:' + action['act']] += 1
                        count['canonical_value_mask_true'] += action['canonical_value_target_mask']
                        for value in action['values']:
                            count['action_value_targets'] += 1
                            count['action_value_recoverable'] += value['value_recoverability_mask']
        assert rows == shard['rows'] and size == shard['bytes'] and h.hexdigest() == shard['sha256']
    for split, count in split_counts.items():
        assert count['USER_examples'] == manifest['counts']['split_USER_examples'][split]
        assert count['bank_policy_row_mask_true'] == count['ledger_row_mask_true'] == count['DELETE_mask_true'] == count['canonical_value_mask_true'] == 0
    counts = {'manifest_sha256': MANIFEST_SHA, 'scope': 'publisher TRAIN ancestry; annotation counts only; no model metrics', 'splits': {s: dict(sorted(c.items())) for s, c in split_counts.items()}}
    add_only(FULL / 'head-mask-counts.json', counts)
    heads = {s['service_name']: {'namespace': 'sgd::' + s['service_name'], 'active_intent_labels_by_id': ['NONE'] + [i['name'] for i in s['intents']], 'slot_labels_by_id': [slot['name'] for slot in s['slots']]} for s in schema}
    handoff = {
        'status': 'ready_for_authorized_publisher_head_minibatch_fit',
        'frozen_manifest': ref(FULL / 'manifest.json'),
        'frozen_processor': manifest['processor'],
        'frozen_collector': manifest['collector'],
        'frozen_split_plan': manifest['split_plan'],
        'raw_source_inventory': manifest['source_inventory'],
        'raw_file_hashes': ref(HERE / 'sources.json'),
        'source': manifest['source'],
        'source_files': len(manifest['source_files']),
        'all_downloaded_files': 130,
        'raw_verified_bytes': 439402926,
        'over_400MB_reason': 'Pinned publisher inventory establishes full requested official TRAIN requires 439402926 bytes; bounded collector ceiling 450000000 bytes.',
        'counts': manifest['counts'],
        'split_shards': {s: [x for x in manifest['outputs'] if x['split'] == s] for s in ['TRAIN', 'CAL', 'EVAL']},
        'processed_shards': len(manifest['outputs']),
        'processed_total_bytes': sum(x['bytes'] for x in manifest['outputs']),
        'processed_max_shard_bytes': max(x['bytes'] for x in manifest['outputs']),
        'storage': {'raw': 'research/customer-benchmark/day2-training-data/sgd/.cache/ (ignored)', 'derived': 'local-runs/customer-benchmark-day2-sgd/full-v1/ (ignored)'},
        'schema': manifest['service_schema'],
        'heads_by_service': heads,
        'actual_head_mask_counts': ref(FULL / 'head-mask-counts.json'),
        'mask_contract': {
            'service_supervision_masks': 'Per-row publisher target availability only. False is unknown, never a negative service label. Never use to select input schemas.',
            'frame_head_masks': 'targets.frames[].head_masks: active_intent, requested_slots, published_slot_map_presence, publisher_actions supervise only when true.',
            'active_intent': 'Service-local CE IDs from heads_by_service; NONE is an actual publisher label.',
            'slot_vectors': 'requested_slots and published_slot_map_presence align to each service-local slot_labels_by_id.',
            'publisher_actions': 'Actual USER action annotations; canonical_value_target_mask is always false.',
            'values': 'targets.frames[].slot_values and actions[].values use text/null and value_recoverability_mask; hashes are bookkeeping, never features.',
            'belief_update': 'Per-slot update_mask controls publisher_map_update KEEP/SET; prior publisher state is supervision only, never runtime input.',
            'unknown_DELETE': 'Missing frames/state/fields stay unknown. DELETE_mask always false.',
            'bank_policy_permission_ledger': 'All related row/frame masks false; no authority, permission, ledger or real-bank policy gold.'
        },
        'input_contract': manifest['feature_protocol'],
        'batch_reader': ref(HERE / 'validated_batches.py'),
        'underlying_batch_reader': ref(HERE / 'batches.py'),
        'batch_api': {'call': 'validated_batches.iter_batches(manifest_path, batch_size=128, seed=20261011, split="TRAIN")', 'feature_view': 'validated_batches.input_view(row)', 'batch_size_max': 512, 'state_reset': 'Before every row with sampling.state_reset_before_row=true, clear/detach predicted recurrent state and caches; first row of each fresh iterator always resets. Reset metadata is not a feature.', 'order': 'Deterministic group/conversation shuffle; USER turns chronological within each conversation.', 'weight': 'sampling.row_group_loss_weight is 1/group_rows; sampling metadata stays outside input.', 'heldout': 'CAL/EVAL streams require allow_heldout=True for evaluation only; never fit weights on those streams.'},
        'validator': ref(HERE / 'validate.py'),
        'freeze_validation': ref(FULL / 'freeze-validation.json'),
        'validation': validation,
        'privacy_recoverability_limits': validation['limits'],
        'ancestry_limits': manifest['ancestry_limits'],
        'partial_preview': {'path': 'research/customer-benchmark/day2-training-data/sgd/partial-0008/', 'not_independent_qualification': True, 'used_for_fit_by_data_worker': False, 'retire_from_fit_queue': True},
        'license_and_attribution': manifest['license_files'],
        'redistribution': 'Derived packet CC-BY-SA-4.0; preserve LICENSE.txt, NOTICE.txt and publisher attribution/citation with any distribution.',
        'official_dev_test': 'untouched; never downloaded or read by this data pipeline',
        'model_fits_by_data_worker': 0,
        'prior_frozen_packets': 'Original BANKING77 v1, three-source v2 and SGD full-v1 bytes not changed for head implementations.',
        'finalizer': ref(Path(__file__).resolve())
    }
    add_only(FULL / 'final-ready-handoff.json', handoff)
    assert sha(FULL / 'manifest.json') == MANIFEST_SHA
    print(json.dumps({'status': handoff['status'], 'manifest': handoff['frozen_manifest'], 'handoff': ref(FULL / 'final-ready-handoff.json'), 'validation': handoff['freeze_validation'], 'mask_counts': handoff['actual_head_mask_counts'], 'processed_bytes': handoff['processed_total_bytes'], 'max_shard_bytes': handoff['processed_max_shard_bytes']}, sort_keys=True))


if __name__ == '__main__':
    main()
