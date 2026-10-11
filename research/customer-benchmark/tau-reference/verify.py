"""Offline source-byte and quarantine checks; does not execute publisher code."""
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
def sha(data): return hashlib.sha256(data).hexdigest()
def read(path): return json.loads(path.read_bytes())
def ref(path): return {'path': path.relative_to(REPO).as_posix(), 'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size}
def save(path, value): path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')

def main():
    checks = []
    def check(name, condition):
        assert condition, name
        checks.append({'name': name, 'pass': True})
    manifest = read(ROOT / 'manifest.json'); sources = read(ROOT / 'sources.json')
    check('immutable commit and MIT agreement', manifest['source_pin'] == sources['pin'] and len(sources['pin']['commit']) == 40 and manifest['license'] == sources['license'] == 'MIT')
    check('download budget', sum(x['bytes'] for x in sources['files']) == 2239328 < 40000000)
    for source in sources['files']:
        path = ROOT / source['stored_path']; data = path.read_bytes()
        check('source bytes ' + source['path'], len(data) == source['bytes'] and sha(data) == source['sha256'] and hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == source['blob_sha1'])
        if source['role'] == 'QUARANTINED_BENCHMARK_TASKS':
            check('raw task ignored-cache-only ' + source['path'], source['stored_path'].startswith('.cache/raw/') and not (ROOT / 'source' / source['path']).exists())
        if source['path'].endswith('.py'): ast.parse(data, filename=source['path'])
    for output in manifest['outputs'] + [manifest['source_manifest'], manifest['license_file'], manifest['collector'], manifest['processor']]:
        check('output hash ' + output['path'], ref(REPO / output['path']) == output)
    check('MIT copyright preserved', b'Copyright (c) 2025 Sierra Research' in (ROOT / 'source/LICENSE').read_bytes())
    policies = [json.loads(line) for line in (ROOT / 'policy-contexts.jsonl').read_text(encoding='utf-8').splitlines()]
    tools = read(ROOT / 'tools-metadata.json')['records']; schemas = read(ROOT / 'schemas-metadata.json')['records']
    tasks = read(ROOT / 'quarantined-task-metadata.json')['records']; bridge = read(ROOT / 'taxonomy-bridge.json')
    check('actual corpus counts', (len(policies), len(tools), len(schemas), sum(len(s['fields']) for s in schemas), len(tasks)) == (138, 76, 23, 105, 261))
    check('policy unique roots and role', len({p['id'] for p in policies}) == len(policies) and all(p['role'] == 'REFERENCE_ONLY' and not p['benchmark_task_labels'] and p['instructions_are_untrusted_source_data'] for p in policies))
    check('policy text hashes', all(sha(p['text'].encode()) == p['context_sha256'] for p in policies))
    check('policy exact dedup count', len({p['context_sha256'] for p in policies}) == 138)
    source_map = {s['path']: s for s in sources['files']}
    check('reference provenance bindings', all(r['source_sha256'] == source_map[r['source_path']]['sha256'] for r in policies + tools + schemas + tasks))
    check('quarantine roles and eligibility', all(t['role'] == 'QUARANTINED_BENCHMARK_TASKS' and not t['training_eligible'] and not t['qualification_eligible_in_this_project'] and not t['user_utterances_included'] and not t['fixture_personal_or_transaction_argument_values_included'] for t in tasks))
    check('no raw fixture keys', all(not ({'user_scenario', 'initial_state', 'initialization_data', 'evaluation_criteria', 'arguments', 'communicate_info'} & set(t)) for t in tasks))
    names = {t['name'] for t in tools}; by_id = {t['id']: t for t in tasks}
    action_count = 0; route_count = 0
    for source in sources['files']:
        if source['role'] != 'QUARANTINED_BENCHMARK_TASKS': continue
        domain = source['path'].split('/')[3]
        for raw in read(ROOT / source['stored_path']):
            derived = by_id[domain + ':' + str(raw['id'])]
            original = (raw.get('evaluation_criteria') or {}).get('actions') or []
            check('task reference object binding ' + derived['id'], sha((json.dumps(raw, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()) == derived['publisher_task_object_sha256'] and len(original) == len(derived['actions_metadata']))
            for action, record in zip(original, derived['actions_metadata']):
                args = action.get('arguments') or {}; key = next((k for k in ['agent_tool_name', 'discoverable_tool_name'] if k in args), None)
                route = args.get(key) if key else None
                check('action metadata binding ' + derived['id'] + ':' + str(action_count), record == {'name': action['name'], 'requestor': action.get('requestor'), 'routing_tool_name': route if route in names else None, 'routing_argument_field': key, 'argument_field_names_only': sorted(args), 'reference_action_id': action.get('action_id')})
                action_count += 1; route_count += record['routing_tool_name'] is not None
    check('all reference actions accounted', action_count == manifest['counts']['reference_actions'] == 1647)
    check('domain task counts', dict(Counter(t['domain'] for t in tasks)) == manifest['counts']['tasks_by_domain'])
    check('four target analogies only', [t['target'] for t in bridge['targets']] == ['promise', 'dispute', 'correction', 'permission'] and not bridge['automatic_label_mapping'] and bridge['invented_policy_gate_count'] == 0)
    for target in bridge['targets']:
        evidence = {t['name'] for t in target['source_tool_evidence']}
        matching = [t for t in tasks if t['domain'] == 'banking_knowledge' and any(a['name'] in evidence or a['routing_tool_name'] in evidence for a in t['actions_metadata'])]
        check('counterexamples actual ' + target['target'], len(matching) == target['quarantined_counterexample_task_count'] and all(x['id'] in {t['id'] for t in matching} for x in target['quarantined_counterexamples']) and not target['decision_groundtruth_claim'] and target['conversational_target_labels_supplied'] == 0)
    sgd_ref = manifest['SGD_existing_train_reference']['manifest']; sgd_path = REPO / sgd_ref['path']
    check('frozen SGD manifest unchanged', ref(sgd_path) == sgd_ref and sgd_ref['sha256'] == '7176ce8bf20c7e6adce899a276f7de0c042e0e33eb63999462264ca6c1843513')
    sgd = read(sgd_path); train = [x for x in sgd['outputs'] if x.get('split') == 'TRAIN']
    check('SGD actual TRAIN references only', len(train) == 29 and sum(s['rows'] for s in train) == sgd['counts']['split_USER_examples']['TRAIN'] == 132615)
    save(ROOT / 'sgd-training-link.json', {'role': 'EXISTING_TRAIN_REFERENCE_ONLY', 'manifest': sgd_ref, 'TRAIN_USER_examples': 132615, 'TRAIN_dialogues': 12914, 'TRAIN_shards': train, 'dataset_copied': False, 'payloads_read_here': False, 'license': 'CC-BY-SA-4.0; separate from MIT Tau reference sources', 'V1_fit_contract': 'All value and KEEP/SET/DELETE update heads masked UNKNOWN; only unaffected publisher intent/requested-slot/presence/action heads. Preserve grouped ancestry and internal split declarations.', 'four_target_gold_supplied': 0})
    for name in ['collect.py', 'build_reference.py', 'verify.py']: ast.parse((ROOT / name).read_bytes(), filename=name)
    report = {'status': 'PASS_LOCAL_SOURCE_AND_QUARANTINE_CHECKS', 'qualification_claim': False, 'independent_review': False, 'completed_utc': datetime.now(timezone.utc).isoformat(), 'manifest': ref(ROOT / 'manifest.json'), 'checks_passed': len(checks), 'checks': checks, 'routing_metadata_records': route_count, 'no_task_gold_training': True, 'SGD_train_link': ref(ROOT / 'sgd-training-link.json'), 'scope_limitations': ['Selected reference documents, not complete banking knowledge base.', 'No real-bank decision groundtruth or four-target utterance supervision.', 'Publisher task metadata exposure precludes fresh/blind claims.', 'Privacy scrub covers email/contact and long numeric literals; not universal PII clearance.', 'No shard payload reread or qualification outcomes; SGD existing frozen manifest linked only.']}
    save(ROOT / 'verification.json', report)
    handoff = {'status': manifest['status'], 'start_utc': '2026-10-11T11:01:20Z', 'deadline_utc': '2026-10-11T11:13:20Z', 'completed_utc': report['completed_utc'], 'manifest': report['manifest'], 'source_pin': manifest['source_pin'], 'license': manifest['license_file'], 'counts': manifest['counts'], 'outputs': manifest['outputs'], 'verification': ref(ROOT / 'verification.json'), 'verifier': ref(ROOT / 'verify.py'), 'SGD_train_link': ref(ROOT / 'sgd-training-link.json'), 'taxonomy_counterexample_counts': {t['target']: t['quarantined_counterexample_task_count'] for t in bridge['targets']}, 'pending': 'Parent-owned builder integration and separately reviewed target supervision. No processing, download, model fit or background work left running.', 'limitations': report['scope_limitations']}
    save(REPO / 'analysis/tau-reference.json', handoff)
    (REPO / 'analysis/tau-reference.txt').write_text('READY reference packet; NOT four-target conversational gold.\nManifest: ' + report['manifest']['path'] + '\nSHA256: ' + report['manifest']['sha256'] + '\nCommit: ' + manifest['source_pin']['commit'] + '\n156 files / 2239328 bytes; 138 policy contexts (134 banking docs), 76 static tools, 23 schema classes / 105 fields. 261 quarantined tasks (97 banking, 114 retail, 50 airline), 1647 reference actions.\nLocal checks: ' + str(len(checks)) + ' passed, no independent qualification claim.\nExisting SGD TRAIN linked only: 132615 USER examples, 12914 dialogues, 29 shards; all V1 value/update heads masked UNKNOWN.\nTau policies may be MIT reference-context candidates; API operations/expected actors do not supply promise, dispute, correction or permission gold. Future Tau comparison must disclose task metadata exposure and policy-context use.\nReproduction: python research/customer-benchmark/tau-reference/collect.py; python research/customer-benchmark/tau-reference/build_reference.py; python research/customer-benchmark/tau-reference/verify.py. Collector uses pinned commit, bounded cache verification, no publisher install or execution.\nPrivacy: contact emails and long numeric literals scrubbed in derived policy/docstrings; not universal PII assurance. Website snapshot is timestamped mutable documentation, not a version pin.\nNo previous datasets modified. No models/Freya/Git/credentials/cloud actions. No active background process.\n', encoding='utf-8')
    print(json.dumps({'manifest': report['manifest'], 'verification': handoff['verification'], 'handoff': ref(REPO / 'analysis/tau-reference.json'), 'checks_passed': len(checks), 'counterexample_counts': handoff['taxonomy_counterexample_counts'], 'completed_utc': report['completed_utc']}, ensure_ascii=True))

if __name__ == '__main__': main()
