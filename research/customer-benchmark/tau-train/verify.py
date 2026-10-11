"""Local byte/projection/partition regressions; not heldout qualification."""
import copy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path): return json.loads(path.read_bytes())
def ref(path): return {'path': path.relative_to(REPO).as_posix(), 'sha256': sha(path), 'bytes': path.stat().st_size}
def module(name):
    spec = importlib.util.spec_from_file_location('owned_tau_' + name, ROOT / (name + '.py'))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value); return value
def main():
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append({'name': name, 'pass': True})
    processor = module('process'); batches = module('batches')
    manifest = load(ROOT / 'manifest.json'); sources = load(ROOT / 'sources.json')
    check('pin and byte budget', sources['commit'] == processor.COMMIT and sources['total_selected_bytes'] < 10000000)
    for source in sources['files']:
        data = (ROOT / source['stored_path']).read_bytes()
        check('source bytes ' + source['path'], len(data) == source['bytes'] and hashlib.sha256(data).hexdigest() == source['sha256'] and hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == source['blob_sha1'])
    for output in manifest['outputs'] + manifest['frozen_reference_preserved'] + [manifest['source_manifest'], manifest['license_file'], manifest['processor'], manifest['collector'], manifest['SGD_existing_TRAIN_link']]:
        check('pinned output ' + output['path'], all(ref(REPO / output['path'])[key] == output[key] for key in ['path', 'sha256', 'bytes']))
    closure = load(ROOT / 'partition-and-closure.json'); membership = {r['id']: r for r in closure['records']}
    scenarios = list(batches.iter_train_scenario_specs()); actions = list(batches.pinned_rows('train-publisher-action-annotations.jsonl'))
    contexts = list(batches.pinned_rows('train-policy-contexts.jsonl')); docs = list(batches.pinned_rows('policy-contexts.jsonl'))
    check('actual counts', (len(scenarios), len(actions), len(contexts), len(docs)) == (103, 103, 716, 701))
    check('official partitions', manifest['partitions']['airline']['official_TRAIN_tasks'] == 30 and manifest['partitions']['retail']['official_TRAIN_tasks'] == 74 and manifest['counts']['official_TEST_excluded'] == 60)
    check('banking official task TRAIN unavailable', manifest['partitions']['banking_knowledge']['official_TRAIN_tasks'] == 0 and not sources['partition_filename_inventory']['banking_knowledge'])
    check('all bank knowledge contexts present', sum('/documents/' in d['source_path'] for d in docs) == 698)
    groups = {}
    for r in closure['records']: groups.setdefault(r['closure_root'], set()).add(r['official_partition'])
    check('cross-TEST groups wholly excluded', all(groups[r['group_root']] == {'TRAIN'} for r in scenarios))
    check('unique IDs and source action targets match scenarios', len({r['id'] for r in scenarios}) == 103 and {r['id'] for r in scenarios} == {r['id'] for r in actions})
    forbidden = {'evaluation_criteria', 'required_documents', 'initial_state', 'expected_actions', 'reference_actions', 'task', 'simulation_run'}
    check('scenario runtime fields clean and independent masks', all(not forbidden.intersection(r) and r['runtime_observation'] == {'messages': [], 'current_observed_utterance': None} and all(v['value'] is None and v['mask'] is False for v in r['financial_target_masks'].values()) and all(v['value'] is None and v['mask'] is False for v in r['semantic_act_masks'].values()) for r in scenarios))
    check('offline targets never runtime features', all(r['runtime_feature_eligible'] is False and r['publisher_partition'] == 'TRAIN' for r in actions))
    check('observed rows honestly zero', manifest['counts']['observed_conversational_TRAIN_rows'] == manifest['counts']['generated_conversational_rows'] == manifest['counts']['financial_supervised_rows'] == 0)
    raw_map = {}
    for domain in ['airline', 'retail']:
        for raw in load(ROOT / '.cache/raw/data/tau2/domains' / domain / 'tasks.json'): raw_map[domain + ':' + str(raw['id'])] = raw
    for row in scenarios:
        raw = raw_map[row['id']]; spec, redactions = processor.scenario(raw)
        check('scenario source projection ' + row['id'], row['generator_spec'] == spec and row['privacy_transform'] == redactions and row['source_task_object_sha256'] == hashlib.sha256(processor.encode(raw)).hexdigest())
        mutated = copy.deepcopy(raw); mutated['evaluation_criteria'] = {'actions': [{'name': 'POISON_EXPECTED_ACTION', 'arguments': {'payload': 'LEAK'}}]}; mutated['initial_state'] = {'db': {'secret': 'LEAK'}}; mutated['required_documents'] = ['POISON_DOC']; mutated['annotations'] = {'future': 'LEAK'}
        check('current oracle mutation cannot change generator conditioning ' + row['id'], processor.scenario(mutated) == (spec, redactions))
    for row in contexts:
        features = batches.policy_features(row)
        check('policy input allowlist ' + row['id'], set(features) == {'reference_text'} and row['source_auxiliary_targets']['source_domain']['mask'] is True and not forbidden.intersection(features))
        mutated = copy.deepcopy(row); mutated['expected_actions'] = ['POISON']; mutated['generator_spec'] = {'instructions': 'POISON'}
        check('oracle metadata excluded from policy features ' + row['id'], batches.policy_features(mutated) == features)
    count = 0
    for invalid in [True, False, 0, -1, 17.5, '64', None, 513]:
        try: list(batches.iter_policy_batches(invalid))
        except ValueError: count += 1
    check('actual typed batch bounds reject all invalid values', count == 8)
    packet_batches = list(batches.iter_policy_batches(64))
    check('actual batch replay 716 rows', len(packet_batches) == 12 and sum(map(len, packet_batches)) == 716 and len(packet_batches[-1]) == 12)
    before = {r['path']: sha(REPO / r['path']) for r in manifest['outputs']}
    before_manifest = sha(ROOT / 'manifest.json'); processor.build()
    check('deterministic full replay', sha(ROOT / 'manifest.json') == before_manifest and before == {p: sha(REPO / p) for p in before})
    witnesses = [r for r in closure['records'] if r['exclusion']]
    report = {'status': 'PASS_LOCAL_TRAIN_PACKET_CHECKS', 'checks_passed': len(checks), 'checks': checks, 'manifest': ref(ROOT / 'manifest.json'), 'completed_utc': datetime.now(timezone.utc).isoformat(), 'independent_review': False, 'heldout_qualification': False, 'cross_TEST_exclusion_witnesses': witnesses, 'batch_replay': {'rows': 716, 'batch_size': 64, 'batches': 12, 'last_batch': 12}, 'no_model_fit': True}
    (ROOT / 'verification.json').write_text(json.dumps(report, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'checks_passed': len(checks), 'verification': ref(ROOT / 'verification.json'), 'exclusion_witnesses': witnesses}, ensure_ascii=True))

if __name__ == '__main__': main()
