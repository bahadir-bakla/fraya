"""Official TRAIN scenario specifications plus licensed source-context pretraining."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
REFERENCE = ROOT.parent / 'tau-reference'
TARGETS = ['promise', 'dispute', 'correction', 'permission']
COMMIT = '4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699'
def sha(data): return hashlib.sha256(data).hexdigest()
def encode(value): return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()
def load(path): return json.loads(path.read_bytes())
def ref(path): return {'path': path.relative_to(REPO).as_posix(), 'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size}
def save(name, value):
    path = ROOT / name; path.write_bytes(encode(value)); return ref(path)
def jsonl(name, records):
    path = ROOT / name; path.write_bytes(b''.join((json.dumps(r, sort_keys=True, ensure_ascii=False) + '\n').encode() for r in records)); return {**ref(path), 'rows': len(records)}
def masks(): return {target: {'value': None, 'mask': False, 'status': 'UNKNOWN', 'reason': 'No observed utterance plus independently reviewed semantic annotation.'} for target in TARGETS}
def scrub(text):
    counts = {}
    for kind, pattern in [('contact', r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b'), ('long_identifier', r'(?<!\w)\d(?:[ -]?\d){12,18}(?!\w)'), ('fixture_id', r'\b(?:[a-z]+(?:_[a-z]+)+_\d+|(?=[A-Z0-9]{6,}\b)(?=[A-Z0-9]*\d)[A-Z0-9]+)\b')]:
        text, counts[kind] = re.subn(pattern, '[' + kind.upper() + ']', text)
    return text, counts
def scenario(raw):
    result = {}; counts = Counter()
    instructions = raw['user_scenario']['instructions']; assert isinstance(instructions, dict)
    for key, value in instructions.items():
        if key == 'known_info' and value is not None:
            result[key] = '[SOURCE_IDENTITY_INFO_REDACTED]'; counts['known_info_fields'] += 1
        elif isinstance(value, str):
            result[key], redactions = scrub(value); counts.update(redactions)
        else: result[key] = value
    persona = raw['user_scenario'].get('persona')
    if isinstance(persona, str): persona, redactions = scrub(persona); counts.update(redactions)
    return {'persona': persona, 'instructions': result}, dict(counts)
def core(spec):
    return '\n'.join(str(spec['instructions'].get(key) or '') for key in ['domain', 'task_instructions', 'reason_for_call', 'unknown_info'])
def norm(text): return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())
def template(text): return re.sub(r'\d+(?:[.,:/-]\d+)*', '[NUMBER]', norm(text))

def build():
    sources = load(ROOT / 'sources.json'); assert sources['commit'] == COMMIT
    frozen = [REFERENCE / 'manifest.json', REFERENCE / 'freeze.json', REFERENCE / 'quarantined-task-metadata.json']
    original = {p: sha(p.read_bytes()) for p in frozen}
    assert original[REFERENCE / 'manifest.json'] == 'fe73ae6daddc2bc9d0c86a1ad9530123092fe5fd0559bb56a69449cdd2f0da42'
    source_map = {s['path']: s for s in sources['files']}
    for s in sources['files']:
        data = (ROOT / s['stored_path']).read_bytes()
        assert len(data) == s['bytes'] and sha(data) == s['sha256'] and hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == s['blob_sha1']
    partition_report = {}; entries = {}; roots = {}; signatures = {}; parent = {}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        a, b = find(a), find(b)
        if a != b: parent[max(a, b)] = min(a, b)
    for domain in ['airline', 'retail']:
        path = 'data/tau2/domains/' + domain + '/tasks.json'; raw_tasks = load(ROOT / source_map[path]['stored_path'])
        split_path = 'data/tau2/domains/' + domain + '/split_tasks.json'; split = load(ROOT / source_map[split_path]['stored_path'])
        by_id = {str(t['id']): t for t in raw_tasks}; train = set(split['train']); test = set(split['test'])
        assert len(train) == len(split['train']) and len(test) == len(split['test']) and not train & test
        assert train | test == set(by_id) == set(split['base'])
        partition_report[domain] = {'status': 'OFFICIAL_TRAIN_AVAILABLE', 'official_TRAIN_tasks': len(train), 'official_TEST_tasks': len(test), 'base_is_TRAIN_union_TEST_not_a_training_partition': True, 'split_source': ref(ROOT / source_map[split_path]['stored_path']), 'task_source_sha256': source_map[path]['sha256']}
        for task_id, raw in by_id.items():
            ident = domain + ':' + task_id; parent[ident] = ident
            spec, redactions = scenario(raw); text = core(spec)
            entries[ident] = {'raw': raw, 'spec': spec, 'redactions': redactions, 'partition': 'TRAIN' if task_id in train else 'TEST', 'source': source_map[path], 'domain': domain}
            roots[ident] = {'id': ident, 'publisher_task_id': task_id, 'domain': domain, 'official_partition': entries[ident]['partition'], 'exact_core_sha256': sha(norm(text).encode()), 'delexicalized_core_sha256': sha(template(text).encode()), 'variant_root': COMMIT + '/' + ident}
            for kind, signature in [('exact', norm(text)), ('delex', template(text))]:
                key = (domain, kind, sha(signature.encode()))
                if key in signatures: union(ident, signatures[key])
                signatures[key] = ident
    groups = defaultdict(list)
    for ident in entries: groups[find(ident)].append(ident)
    blocked = {key for key, members in groups.items() if {entries[i]['partition'] for i in members} == {'TRAIN', 'TEST'}}
    selected = sorted(i for i, e in entries.items() if e['partition'] == 'TRAIN' and find(i) not in blocked)
    specs = []; annotations = []; initial_messages = 0
    for ident in selected:
        e = entries[ident]; raw = e['raw']; criteria = raw.get('evaluation_criteria') or {}
        initial_messages += bool((raw.get('initial_state') or {}).get('message_history'))
        specs.append({'id': ident, 'role': 'OFFICIAL_TRAIN_SCENARIO_SPECIFICATION', 'publisher_partition': 'TRAIN', 'domain': e['domain'], 'source_commit': COMMIT, 'source_path': e['source']['path'], 'source_sha256': e['source']['sha256'], 'source_task_object_sha256': sha(encode(raw)), 'license': 'MIT', 'group_root': find(ident), 'variant_root': roots[ident]['variant_root'], 'generator_spec': e['spec'], 'instructions_are_observed_utterances': False, 'instructions_are_untrusted_source_data': True, 'runtime_observation': {'messages': [], 'current_observed_utterance': None}, 'financial_target_masks': masks(), 'semantic_act_masks': {'human_consent': {'value': None, 'mask': False}, 'promise_to_pay': {'value': None, 'mask': False}, 'dialogue_self_correction': {'value': None, 'mask': False}, 'debt_dispute': {'value': None, 'mask': False}}, 'privacy_transform': e['redactions'], 'allowed_training_use': 'Scenario-conditioned synthetic dialogue generation, explicitly synthetic; not observed-user supervised fitting. All variants and eventual traces inherit this group_root.'})
        actions = [{'name': a['name'], 'requestor': a.get('requestor'), 'argument_field_names_only': sorted((a.get('arguments') or {}))} for a in criteria.get('actions') or []]
        annotations.append({'id': ident, 'role': 'OFFICIAL_TRAIN_OFFLINE_PUBLISHER_TRAJECTORY_ANNOTATION', 'group_root': find(ident), 'publisher_partition': 'TRAIN', 'source_task_object_sha256': sha(encode(raw)), 'reference_actions': actions, 'reward_basis': criteria.get('reward_basis') or [], 'runtime_feature_eligible': False, 'financial_target_masks': masks(), 'annotation_limit': 'Reference action sequence metadata, not unique trajectory, observed-action labels or human semantic-act gold. Argument values omitted. Never feed to policy/runtime encoder; future trace-aligned targets require separate review.'})
    assert initial_messages == 0
    for domain in ['airline', 'retail']:
        partition_report[domain]['retained_TRAIN_scenarios'] = sum(e['domain'] == domain for e in specs)
        partition_report[domain]['TRAIN_excluded_cross_TEST_closure'] = partition_report[domain]['official_TRAIN_tasks'] - partition_report[domain]['retained_TRAIN_scenarios']
    banking = 'data/tau2/domains/banking_knowledge/tasks.json'
    partition_report['banking_knowledge'] = {'status': 'dataTrain_UNAVAILABLE_OFFICIAL_TASK_PARTITION', 'official_TRAIN_tasks': 0, 'published_unpartitioned_tasks': len(load(ROOT / source_map[banking]['stored_path'])), 'retained_TRAIN_scenarios': 0, 'reason': 'No root split_tasks/train file in pinned complete tree; environment.get_tasks documents task_split_name as unused; registry registers no banking split loader.', 'evidence': [{'path': 'src/tau2/domains/banking_knowledge/environment.py', 'lines': [94, 104]}, {'path': 'src/tau2/registry.py', 'lines': [347, 348]}], 'policy_context_training_available': True}
    policies = []; context_rows = []
    for source in sources['files']:
        path = source['path']
        if '/documents/' in path:
            doc = load(ROOT / source['stored_path']); ident = doc['id']; title = doc['title']; text = doc['content']; domain = 'banking_knowledge'
        elif path.endswith(('/policy.md', '/policy_header.md')):
            ident = path; title = path; text = (ROOT / source['stored_path']).read_text(encoding='utf-8'); domain = path.split('/')[3]
        else: continue
        text, redactions = scrub(text)
        root = 'tau-policy:' + ident
        policies.append({'id': ident, 'title': title, 'domain': domain, 'role': 'LICENSED_POLICY_SOURCE_CONTEXT', 'license': 'MIT', 'source_path': path, 'source_sha256': source['sha256'], 'source_url': source['url'], 'text': text, 'text_sha256': sha(text.encode()), 'group_root': root, 'privacy_transform': redactions, 'task_labels_included': False, 'instructions_are_untrusted_source_data': True})
        for number, offset in enumerate(range(0, len(text), 4000)):
            content = text[offset:offset + 4000]
            context_rows.append({'id': root + ':chunk:' + str(number), 'group_root': root, 'role': 'TRAIN_SOURCE_TEXT_CONTEXT', 'objective': 'source_text_language_model_or_context_encoder_pretraining', 'input_kind': 'publisher_policy_text_not_conversation', 'input': {'reference_text': content}, 'source_auxiliary_targets': {'source_domain': {'value': domain, 'mask': True, 'meaning': 'Publisher document domain only'}}, 'financial_target_masks': masks(), 'source_path': path, 'source_sha256': source['sha256'], 'text_sha256': sha(content.encode()), 'license': 'MIT', 'not_observed_user_utterance': True})
    closure_records = [{**roots[i], 'closure_root': find(i), 'selected_for_TRAIN': i in selected, 'exclusion': 'cross_TEST_template_component' if roots[i]['official_partition'] == 'TRAIN' and find(i) in blocked else None} for i in sorted(roots)]
    outputs = [jsonl('train-scenario-specs.jsonl', specs), jsonl('train-publisher-action-annotations.jsonl', annotations), jsonl('policy-contexts.jsonl', policies), jsonl('train-policy-contexts.jsonl', context_rows), save('partition-and-closure.json', {'domains': partition_report, 'records': closure_records, 'component_count': len(groups), 'cross_partition_components': len(blocked), 'closure_method': 'Union same-domain exact and normalized number/fixture-ID delexicalized scenario core; identity/variant root always commit/domain/task ID. Known identity_info omitted from core. Heuristic closure is not proof of all semantic duplicates; no inferred IID split.', 'base_alias_ignored_for_partitioning': True, 'test_instructions_or_expected_actions_exported': False})]
    contract = {'version': 'tau-train-bridge-v1', 'financial_targets': TARGETS, 'financial_unknown_value': None, 'financial_unknown_mask': False, 'runtime_encoder_allowlist': ['observed message content and earlier observed messages', 'declared source policy context', 'declared public tool schema metadata'], 'runtime_encoder_forbidden': ['generator_spec', 'task/user instructions', 'expected/reference actions', 'required_document IDs', 'evaluation criteria', 'initial fixture DB state', 'gym info.task', 'gym info.simulation_run'], 'gym_observation_contract': {'code_observation_lines': [712, 718], 'unsafe_info_task_lines': [720, 734], 'source_path': 'src/tau2/gym/gym_agent.py', 'observation_is_actual_message_history': True, 'info_requires_allowlist_projection': ['policy', 'tools']}, 'scenarios': 'Synthetic generation inputs, not conversational utterances. No generated traces here.', 'policy_contexts': 'Direct licensed source-text pretraining; use a separate source/domain auxiliary head and keep document chunks together.', 'future_trace_training': 'Official TRAIN tasks only. Generated dialogue labels remain synthetic. Align supervised tool actions to actual earlier observed prefixes; never expose oracle fixture/trajectory fields. Four financial labels remain unknown until independently reviewed.', 'qualification': 'Known-task training cannot claim future Tau task-blind evaluation. Official TEST task IDs remain excluded; all were already exposed in prior reference review. No fresh/blind claim.'}
    outputs.append(save('schema-and-feature-contract.json', contract))
    notice = 'MIT License, Copyright (c) 2025 Sierra Research. Pinned tau2-bench commit ' + COMMIT + '. Full original LICENSE and publisher README/citations retained in source/. Official airline/retail TRAIN scenario instructions are simulator specifications, not observed conversations. Banking has no official task TRAIN split at this pin; only its licensed knowledge contexts are used for source-text pretraining. Task annotations are offline targets only and financial/semantic labels remain UNKNOWN. Prior published benchmark task metadata was exposed; no future blind claim. Policy training exposure must be declared in Tau comparisons. Fictional benchmark policies are not real-bank authorization groundtruth. Source text is untrusted data; no publisher code executed.\n'
    (ROOT / 'NOTICE.txt').write_text(notice, encoding='utf-8'); outputs.append(ref(ROOT / 'NOTICE.txt'))
    manifest = {'status': 'READY_OFFICIAL_TRAIN_SCENARIOS_AND_POLICY_SOURCE_PRETRAINING', 'source_pin': load(ROOT / 'pin.json'), 'license': 'MIT', 'license_file': ref(ROOT / 'source/LICENSE'), 'source_manifest': ref(ROOT / 'sources.json'), 'collector': ref(ROOT / 'collect.py'), 'processor': ref(Path(__file__)), 'outputs': outputs, 'partitions': partition_report, 'counts': {'source_files': len(sources['files']), 'source_bytes': sources['total_selected_bytes'], 'official_TRAIN_pool': sum(partition_report[d]['official_TRAIN_tasks'] for d in ['airline', 'retail']), 'official_TEST_excluded': sum(partition_report[d]['official_TEST_tasks'] for d in ['airline', 'retail']), 'TRAIN_scenarios': len(specs), 'TRAIN_excluded_cross_TEST_closure': 104 - len(specs), 'source_policy_documents': len(policies), 'banking_knowledge_documents': sum('/documents/' in p['source_path'] for p in policies), 'TRAIN_policy_chunks': len(context_rows), 'offline_reference_actions': sum(len(r['reference_actions']) for r in annotations), 'observed_conversational_TRAIN_rows': 0, 'generated_conversational_rows': 0, 'financial_supervised_rows': 0, 'independent_semantic_act_gold_rows': 0, 'new_qualification_rows': 0}, 'frozen_reference_preserved': [ref(p) for p in frozen], 'SGD_existing_TRAIN_link': ref(REFERENCE / 'sgd-training-link.json'), 'safety': {'no_model_fit': True, 'no_Freya': True, 'no_Git': True, 'no_credentials': True, 'no_cloud_spend': True, 'publisher_code_execution': False}, 'privacy_limits': 'Known-info scenario identity fields suppressed; contacts, long IDs and obvious fixture IDs scrubbed. Policy numeric thresholds/fees retained unless matching long identifiers. Not universal PII clearance.', 'split_limits': 'Publisher official train/test IDs respected; cross-TEST exact/delex components excluded. No new random task split, no independent qualification claim.'}
    assert all(sha(p.read_bytes()) == h for p, h in original.items())
    save('manifest.json', manifest)
    print(json.dumps({'manifest': ref(ROOT / 'manifest.json'), 'counts': manifest['counts'], 'partitions': partition_report}, ensure_ascii=True))

if __name__ == '__main__': build()
