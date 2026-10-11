"""Producer regression evidence only; independent V2 review remains pending."""
from collections import Counter
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SGD = REPO / 'research/customer-benchmark/day2-training-data/sgd'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def main():
    producer = load('sgd_v2_regression_producer', SGD / 'process-v2.py')
    reader = load('sgd_v2_regression_reader', SGD / 'batches-v2.py')
    witness_path = REPO / 'analysis/day2-sgd-independent-review-witnesses.json'
    witnesses = json.loads(witness_path.read_bytes())['actual_TRAIN_recoverability_partialword_examples']
    wanted = {(w['record_id'], w['service'], w['value_sha256']) for w in witnesses}
    found = set(); updates_masked = 0
    schemas = {s['service_name']: s for s in json.loads((SGD / 'service-schema.json').read_bytes())}
    for path in sorted((SGD / '.cache').glob('train__dialogues_*.json')):
        for dialog in json.loads(path.read_bytes()):
            if not any('sgd:' + dialog['dialogue_id'] + ':' in x[0] for x in wanted):
                continue
            observed = producer.base.observed(dialog)[0]; previous = {}
            for index, turn in enumerate(dialog['turns']):
                if turn['speaker'] != 'USER': continue
                inp = producer.input_for(observed, index)
                visible = '\n'.join(x['text'] for x in inp['earlier_context']) + '\n' + inp['utterance']
                record = 'sgd:' + dialog['dialogue_id'] + ':' + str(index)
                for frame in turn['frames']:
                    target = producer.base.frame_targets(frame, schemas, previous.get(frame['service']), visible, Counter())
                    names = [s['name'] for s in schemas[frame['service']]['slots']]
                    for slot, values in target['slot_values'].items():
                        for value in values:
                            key = (record, frame['service'], value['source_value_sha256'])
                            if key in wanted:
                                assert not value['value_recoverability_mask'] and value['text'] is None
                                update = target['belief_updates'][names.index(slot)]
                                assert not update['update_mask']
                                if update['publisher_map_update'] in ['KEEP', 'SET']: updates_masked += 1
                                found.add(key)
                previous = {f['service']: f.get('state') for f in turn['frames']}
        if found == wanted: break
    assert found == wanted and len(found) == 15
    # Exact invalid types must fail before opening a manifest/index.
    invalid = [17.5, True, False, 0, -1, 513, '17', None]
    for size in invalid:
        stream = reader.iter_batches(REPO / 'nonexistent-manifest-for-boundary-test', batch_size=size)
        try: next(stream)
        except ValueError: pass
        else: raise AssertionError('Invalid batch size admitted')
        finally: stream.close()
    v1 = json.loads((SGD / 'full-v1/manifest.json').read_bytes())
    first = next(x for x in v1['outputs'] if x['split'] == 'TRAIN')
    with (REPO / first['path']).open('rb') as handle:
        actual_rows = list(itertools.islice(handle, 64))
    # Ignored actual-TRAIN fixture for cache drift; never a fit corpus.
    fixture = REPO / 'local-runs/customer-benchmark-day2-sgd/v2-regression-fixture'
    fixture.mkdir(exist_ok=True)
    shard = fixture / 'train.jsonl'; original = b''.join(actual_rows)
    shard.write_bytes(original)
    m = {'schema_version': 'sgd.training-packet.v2', 'status': 'prepared_awaiting_independent_review_not_fit_authorized', 'outputs': [{'path': shard.relative_to(REPO).as_posix(), 'split': 'TRAIN', 'sha256': hashlib.sha256(original).hexdigest(), 'rows': 64, 'bytes': len(original)}]}
    manifest = fixture / 'manifest.json'; manifest.write_text(json.dumps(m), encoding='utf-8')
    stream = reader.iter_batches(manifest, batch_size=17)
    batches = list(stream)
    assert [len(b) for b in batches] == [17, 17, 17, 13]
    assert batches[0][0]['sampling']['state_reset_before_row']
    # Completed SQLite cache exists. Same-size source mutation must be rejected.
    tampered = original.replace(b'USER', b'USXR', 1)
    assert len(tampered) == len(original) and tampered != original
    shard.write_bytes(tampered)
    rejected = False
    try: reader.index_for(manifest, 'TRAIN')
    except ValueError: rejected = True
    finally: shard.write_bytes(original)
    assert rejected
    report = {'status': 'producer_regressions_passed_independent_review_pending', 'assignment_start_utc': '2026-10-11T09:51:28Z', 'deadline_utc': '2026-10-11T09:59:28Z', 'original_staging_process_state': 'interrupted; no matching process remained before continuation', 'original_staging_shards_preserved': 'local-runs/customer-benchmark-day2-sgd/full-v2-interrupted-staging-20261011/', 'source_witness_sha256': hashlib.sha256(witness_path.read_bytes()).hexdigest(), 'actual_TRAIN_partialword_witnesses_now_unknown': len(found), 'witness_KEEP_SET_masks_false': updates_masked, 'typed_invalid_batch_sizes_rejected_before_IO': len(invalid), 'actual_TRAIN_fixture_batch_sizes': [len(b) for b in batches], 'cached_index_same_size_shard_drift_rejected': rejected, 'producer_self_tests': producer.self_test(), 'V1_manifest_unchanged': hashlib.sha256((SGD / 'full-v1/manifest.json').read_bytes()).hexdigest() == producer.V1_SHA, 'independent_review': 'pending; no head fitting authorized', 'model_fits': 0, 'official_dev_test_read': False}
    (REPO / 'analysis/day2-sgd-v2-regression.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, sort_keys=True))


if __name__ == '__main__': main()
