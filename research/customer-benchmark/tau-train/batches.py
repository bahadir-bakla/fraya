"""CPU policy-source batches; no task gold or instructions in runtime features."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]

def positive_integer(value, name, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(name + ' must be an actual integer in 1..' + str(maximum))
    return value

def pinned_rows(filename):
    manifest = json.loads((ROOT / 'manifest.json').read_bytes())
    candidates = [r for r in manifest['outputs'] if Path(r['path']).name == filename]
    if len(candidates) != 1: raise ValueError('file is not uniquely pinned')
    record = candidates[0]; path = (REPO / record['path']).resolve()
    if path != (ROOT / filename).resolve(): raise ValueError('noncanonical packet path')
    data = path.read_bytes()
    if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError('packet bytes changed')
    lines = data.splitlines()
    if len(lines) != record['rows']: raise ValueError('row count changed')
    for line in lines: yield json.loads(line)

def policy_features(row):
    if row.get('role') != 'TRAIN_SOURCE_TEXT_CONTEXT' or row.get('input_kind') != 'publisher_policy_text_not_conversation':
        raise ValueError('not an eligible source-text record')
    if set(row['input']) != {'reference_text'} or type(row['input']['reference_text']) is not str:
        raise ValueError('runtime source-text feature allowlist violation')
    text = row['input']['reference_text']
    if hashlib.sha256(text.encode()).hexdigest() != row['text_sha256']:
        raise ValueError('text hash mismatch')
    if not all(v['value'] is None and v['mask'] is False for v in row['financial_target_masks'].values()):
        raise ValueError('unreviewed financial supervision')
    return {'reference_text': text}

def iter_policy_batches(batch_size=64):
    positive_integer(batch_size, 'batch_size', 512)
    batch = []
    for row in pinned_rows('train-policy-contexts.jsonl'):
        batch.append({'id': row['id'], 'group_root': row['group_root'], 'input': policy_features(row), 'targets': {'tau_source_domain': row['source_auxiliary_targets']['source_domain'], **row['financial_target_masks']}})
        if len(batch) == batch_size: yield batch; batch = []
    if batch: yield batch

def iter_train_scenario_specs():
    for row in pinned_rows('train-scenario-specs.jsonl'):
        if row['publisher_partition'] != 'TRAIN' or row['role'] != 'OFFICIAL_TRAIN_SCENARIO_SPECIFICATION':
            raise ValueError('not official TRAIN scenario')
        if row['runtime_observation'] != {'messages': [], 'current_observed_utterance': None}:
            raise ValueError('unverified observed dialogue inserted')
        yield row

if __name__ == '__main__':
    batches = list(iter_policy_batches())
    print(json.dumps({'policy_rows': sum(map(len, batches)), 'batch_count_64': len(batches), 'last_batch_size': len(batches[-1]), 'scenario_specs': sum(1 for _ in iter_train_scenario_specs()), 'model_fit': False}))
