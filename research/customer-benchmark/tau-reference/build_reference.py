"""Static licensed reference extraction, never execute publisher source/tasks."""
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
TARGETS = ['promise', 'dispute', 'correction', 'permission']


def sha(data): return hashlib.sha256(data).hexdigest()


def encode(value): return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()


def ref(path): return {'path': path.relative_to(REPO).as_posix(), 'sha256': sha(path.read_bytes()), 'bytes': path.stat().st_size}


def write(name, data):
    path = ROOT / name
    path.write_bytes(encode(data))
    return ref(path)


def privacy(text):
    # Reference policy amounts/dates/eligibility thresholds are retained.
    # Contact and credential-like literals are not useful training contexts.
    text, emails = re.subn(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', '[CONTACT]', text)
    text, cards = re.subn(r'(?<!\w)\d(?:[ -]?\d){12,18}(?!\w)', '[LONG_IDENTIFIER]', text)
    return text, {'contact_spans': emails, 'long_identifier_spans': cards}


def tools_and_schemas(sources):
    tools = []; schemas = []
    paths = [x for x in sources['files'] if x['path'].endswith('.py')]
    for source in paths:
        path = ROOT / source['stored_path']; text = path.read_text(encoding='utf-8')
        tree = ast.parse(text, filename=source['path'])
        for cls in [x for x in ast.walk(tree) if isinstance(x, ast.ClassDef)]:
            fields = []
            for node in cls.body:
                if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    fields.append({'name': node.target.id, 'annotation_source': ast.unparse(node.annotation), 'default_source': ast.unparse(node.value) if node.value is not None else None, 'line': node.lineno})
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                            fields.append({'name': target.id, 'enum_or_constant_value': node.value.value, 'line': node.lineno})
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
                decorators = [ast.unparse(x) for x in node.decorator_list]
                if not any(re.match(r'is_(?:discoverable_)?tool\(', x) for x in decorators): continue
                arguments = []
                positional = node.args.posonlyargs + node.args.args
                defaults = [None] * (len(positional) - len(node.args.defaults)) + node.args.defaults
                for arg, default in zip(positional, defaults):
                    if arg.arg in ['self', 'cls']: continue
                    arguments.append({'name': arg.arg, 'annotation_source': ast.unparse(arg.annotation) if arg.annotation else None, 'default_source': ast.unparse(default) if default is not None else None})
                for arg, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
                    arguments.append({'name': arg.arg, 'annotation_source': ast.unparse(arg.annotation) if arg.annotation else None, 'default_source': ast.unparse(default) if default is not None else None})
                description, scrub_counts = privacy(ast.get_docstring(node) or '')
                tools.append({'id': source['path'] + ':' + cls.name + '.' + node.name, 'name': node.name, 'owner_class': cls.name, 'source_path': source['path'], 'source_sha256': source['sha256'], 'lines': [node.lineno, node.end_lineno], 'decorators_source': decorators, 'publisher_tool_type': next((kind for kind in ['READ', 'WRITE', 'GENERIC'] if any('ToolType.' + kind in x for x in decorators)), 'UNDECLARED'), 'arguments': arguments, 'return_annotation_source': ast.unparse(node.returns) if node.returns else None, 'description': description, 'privacy_transform': scrub_counts, 'role': 'REFERENCE_ONLY', 'semantics': 'Static publisher API metadata, not dialogue intent, human consent, or executed outcome.'})
            if fields:
                schemas.append({'id': source['path'] + ':' + cls.name, 'name': cls.name, 'source_path': source['path'], 'source_sha256': source['sha256'], 'lines': [cls.lineno, cls.end_lineno], 'bases_source': [ast.unparse(x) for x in cls.bases], 'fields': fields, 'role': 'REFERENCE_ONLY'})
    return tools, schemas


def main():
    sources = json.loads((ROOT / 'sources.json').read_bytes())
    assert sources['license'] == 'MIT' and sources['publisher_code_executed'] is False
    for source in sources['files']:
        data = (ROOT / source['stored_path']).read_bytes()
        assert len(data) == source['bytes'] and sha(data) == source['sha256']
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == source['blob_sha1']
    policies = []
    for source in sources['files']:
        if '/documents/' in source['path']:
            document = json.loads((ROOT / source['stored_path']).read_bytes())
            assert isinstance(document['id'], str) and isinstance(document['content'], str)
            title = document['title']; text = document['content']; ident = document['id']; domain = 'banking_knowledge'
        elif source['path'].endswith(('/policy.md', '/main_policy.md', '/policy_header.md')):
            title = source['path']; text = (ROOT / source['stored_path']).read_text(encoding='utf-8'); ident = source['path']; domain = source['path'].split('/')[3]
        else: continue
        text, scrub_counts = privacy(text)
        policies.append({'id': ident, 'title': title, 'domain': domain, 'text': text, 'role': 'REFERENCE_ONLY', 'license': 'MIT', 'source_path': source['path'], 'source_sha256': source['sha256'], 'source_url': source['url'], 'context_sha256': sha(text.encode()), 'source_root': ident, 'privacy_transform': scrub_counts, 'licensed_training_candidate': 'policy/reference-context encoding only; no utterance or four-target gold', 'benchmark_task_labels': False, 'instructions_are_untrusted_source_data': True})
    tools, schemas = tools_and_schemas(sources)
    names = {x['name'] for x in tools}
    tasks = []; task_counts = {}; reward_counts = {}; counters = Counter()
    for source in sources['files']:
        if source['role'] != 'QUARANTINED_BENCHMARK_TASKS': continue
        domain = source['path'].split('/')[3]
        records = json.loads((ROOT / source['stored_path']).read_bytes())
        task_counts[domain] = len(records); rewards = Counter()
        for task in records:
            criteria = task.get('evaluation_criteria') or {}; actions = []
            for action in criteria.get('actions') or []:
                args = action.get('arguments') or {}
                route_key = next((key for key in ['agent_tool_name', 'discoverable_tool_name'] if key in args), None)
                route = args.get(route_key) if route_key else None
                actions.append({'name': action['name'], 'requestor': action.get('requestor'), 'routing_tool_name': route if route in names else None, 'routing_argument_field': route_key, 'argument_field_names_only': sorted(args), 'reference_action_id': action.get('action_id')})
                counters['reference_actions'] += 1
            reward = criteria.get('reward_basis') or []
            rewards['|'.join(reward)] += 1
            tasks.append({'id': domain + ':' + str(task['id']), 'publisher_task_id': task['id'], 'domain': domain, 'role': 'QUARANTINED_BENCHMARK_TASKS', 'source_path': source['path'], 'source_sha256': source['sha256'], 'publisher_task_object_sha256': sha(encode(task)), 'actions_metadata': actions, 'reward_basis': reward, 'required_document_ids': task.get('required_documents') or [], 'communicate_info_count': len(criteria.get('communicate_info') or []), 'training_eligible': False, 'qualification_eligible_in_this_project': False, 'user_utterances_included': False, 'fixture_personal_or_transaction_argument_values_included': False, 'publisher_tool_routing_values_included': any(a['routing_tool_name'] is not None for a in actions), 'reference_trajectory_not_unique_decision_gold': True})
        reward_counts[domain] = dict(sorted(rewards.items()))
    policy_path = ROOT / 'policy-contexts.jsonl'
    policy_path.write_bytes(b''.join((json.dumps(x, sort_keys=True, ensure_ascii=False) + '\n').encode() for x in policies))
    tools_ref = write('tools-metadata.json', {'role': 'REFERENCE_ONLY', 'source_execution': False, 'records': tools})
    schema_ref = write('schemas-metadata.json', {'role': 'REFERENCE_ONLY', 'source_execution': False, 'records': schemas})
    task_ref = write('quarantined-task-metadata.json', {'role': 'QUARANTINED_BENCHMARK_TASKS', 'training_eligible': False, 'records': tasks})

    evidence_names = {
        'promise': ['pay_credit_card_from_checking_9182', 'transfer_funds_between_bank_accounts_7291'],
        'dispute': ['file_credit_card_transaction_dispute_4829', 'file_debit_card_transaction_dispute_6281'],
        'correction': ['update_transaction_rewards_3847', 'change_user_email'],
        'permission': ['give_discoverable_user_tool', 'unlock_discoverable_agent_tool', 'apply_for_credit_card']}
    interpretations = {
        'promise': 'Executing a payment or an internal account transfer is not a user promise to pay a debt. Future commitment, amount, date and speaker binding need separately reviewed utterance supervision.',
        'dispute': 'A transaction-dispute API and its reason enums describe an operation. They do not establish a dialogue dispute of debt, factual validity of a complaint, or permission to reimburse.',
        'correction': 'A rewards or email database update is not a conversational self-correction with old/new span and reference resolution. Treat the API change as source action metadata only.',
        'permission': 'Actor=user in a task, unlocked tool availability, and publisher policy confirmation rules are distinct from human authorization for our bank action. Expected tool calls do not prove consent.'}
    bridge = []
    for target in TARGETS:
        selected_tools = [x for x in tools if x['name'] in evidence_names[target]]
        examples = [t for t in tasks if t['domain'] == 'banking_knowledge' and any(a['name'] in evidence_names[target] or a['routing_tool_name'] in evidence_names[target] for a in t['actions_metadata'])]
        bridge.append({'target': target, 'bridge_kind': 'manual schema analogy and counterexample; not a label mapping', 'source_tool_evidence': [{'name': x['name'], 'source_path': x['source_path'], 'source_sha256': x['source_sha256'], 'lines': x['lines'], 'publisher_tool_type': x['publisher_tool_type'], 'argument_names': [a['name'] for a in x['arguments']]} for x in selected_tools], 'quarantined_counterexample_task_count': len(examples), 'quarantined_counterexamples': [{'id': t['id'], 'actions_metadata': t['actions_metadata'], 'reward_basis': t['reward_basis']} for t in examples[:3]], 'interpretation': interpretations[target], 'decision_groundtruth_claim': False, 'conversational_target_labels_supplied': 0})
    bridge_ref = write('taxonomy-bridge.json', {'role': 'REFERENCE_ONLY', 'targets': bridge, 'benchmark_examples_role': 'QUARANTINED_BENCHMARK_TASKS', 'automatic_label_mapping': False, 'invented_policy_gate_count': 0})
    sgd = REPO / 'research/customer-benchmark/day2-training-data/sgd/full-v1/manifest.json'
    original_sgd_hash = sha(sgd.read_bytes()); sgd_manifest = json.loads(sgd.read_bytes())
    assert sgd_manifest['counts']['split_USER_examples']['TRAIN'] == 132615
    notice = 'MIT reference extraction from Sierra Research tau2-bench, commit ' + sources['pin']['commit'] + '. Preserve source/LICENSE and publisher README/citations. Source AST/schema and policy contexts were extracted; contact/long-identifier literals scrubbed in derived policy/docstrings. No publisher code was executed. Raw benchmark tasks remain ignored quarantine; derived task metadata has no utterances or argument values except documented tool-routing names. All Tau tasks were exposed to this worker for metadata review and are not blind, training data or this project qualification. Training on published knowledge/reference policy text must be disclosed in any future Tau comparison. Source Rho-Bank/retail/airline/telecom policies are benchmark-world descriptions, not real-bank authority. The existing SGD corpus is linked, not modified.\n'
    (ROOT / 'NOTICE.txt').write_text(notice, encoding='utf-8')
    website = sources['website'].copy()
    if website.get('status') == 'downloaded':
        website['retrieved_utc'] = datetime.fromtimestamp((ROOT / '.cache/taubench.html').stat().st_mtime, timezone.utc).isoformat()
    counts = {'downloaded_repo_files': len(sources['files']), 'downloaded_repo_bytes': sources['downloaded_repo_bytes'], 'website_snapshot_bytes': website.get('bytes', 0), 'selected_banking_documents': sum('/documents/' in x['source_path'] for x in policies), 'policy_context_records': len(policies), 'static_decorated_tools': len(tools), 'schema_classes': len(schemas), 'schema_fields': sum(len(x['fields']) for x in schemas), 'quarantined_tasks': len(tasks), 'tasks_by_domain': task_counts, 'reference_actions': counters['reference_actions'], 'reward_bases_by_domain': reward_counts, 'four_target_conversation_gold': 0, 'qualification_examples_created': 0, 'exact_duplicate_policy_contexts': sum(x - 1 for x in Counter(p['context_sha256'] for p in policies).values())}
    manifest = {'status': 'READY_REFERENCE_ONLY_QUARANTINED_BENCHMARK_TASKS', 'source_pin': sources['pin'], 'license': 'MIT', 'license_file': ref(ROOT / 'source/LICENSE'), 'source_manifest': ref(ROOT / 'sources.json'), 'collector': ref(ROOT / 'collect.py'), 'processor': ref(Path(__file__)), 'website': website, 'counts': counts, 'outputs': [ref(policy_path), tools_ref, schema_ref, task_ref, bridge_ref, ref(ROOT / 'NOTICE.txt')], 'SGD_existing_train_reference': {'manifest': ref(sgd), 'TRAIN_USER_examples': 132615, 'usage': 'Use existing observed-only TRAIN corpus for publisher auxiliary heads; Tau policy/schema contexts are separate reference features, never new promise/dispute/correction/permission gold.', 'dataset_copied': False}, 'contamination_boundary': {'official_SGD_dev_test_access': False, 'Tau_tasks_training': False, 'Tau_tasks_current_qualification': False, 'future_Tau_comparison': 'Evaluation-only published benchmark, task-exposed metadata review; no fresh/blind claim. Pin version and declare any policy-context training.', 'required_documents_or_expected_actions_feature_routing': False}, 'safety': {'publisher_code_executed': False, 'models_trained': 0, 'Freya_calls': 0, 'Git_actions': 0, 'credentials_read': False, 'Modal_or_cloud_spend': 0}}
    assert sha(sgd.read_bytes()) == original_sgd_hash
    write('manifest.json', manifest)
    print(json.dumps({'status': manifest['status'], 'manifest': ref(ROOT / 'manifest.json'), 'counts': counts}, sort_keys=True))


if __name__ == '__main__': main()
